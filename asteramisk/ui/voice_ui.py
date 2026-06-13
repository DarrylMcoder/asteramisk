import aiohttp
import uuid
import aioari
import asyncio
import samplerate
import websockets
import numpy as np
from contextlib import suppress, asynccontextmanager
from agents import Agent, Runner, TContext, SQLiteSession, RunResultStreaming
from agents.realtime import RealtimeAgent, RealtimeRunner

from asteramisk.config import config
from asteramisk.ui import UI
from asteramisk.exceptions import HangupException, GoBackException
from asteramisk.internal.tts import TTSEngine
from asteramisk.internal.transcriber import TranscribeEngine
from asteramisk.internal.ari_client import AriClient
from asteramisk.internal.audiosocket import AudiosocketAsync
from asteramisk.internal.audiosocket_connection import AudioSocketConnectionAsync


import logging
logger = logging.getLogger(__name__)

ASTERISK_SAMPLE_RATE = 8000
OPENAI_SAMPLE_RATE = 24000

class VoiceUI(UI):
    """
    A voice user interface for Asterisk
    Provides methods such as answer(), hangup(), say(), ask_yes_no(), prompt(), and gather()
    API should be the same as the base UI class and any other UI subclasses (TextUI, etc.)
    """
    async def __create__(self, channel: aioari.model.Channel, voice=None):
        logger.debug("VoiceUI.__create__")
        self.channel = channel
        self.voice = voice if voice else config.SYSTEM_VOICE
        self.answered = False
        self.is_active = True
        self.ari: aioari.Client = await AriClient.create()
        audiosocket = await AudiosocketAsync.create()
        stream_id = str(uuid.uuid4())
        self.external_media_channel: aioari.model.Channel = await self.ari.channels.externalMedia(
            external_host=f"{config.ASTERAMISK_HOST}:{audiosocket.port}", # Use the configured host and the possibly dynamic port in case no port was specified in the config
            encapsulation="audiosocket",
            app="asteramisk",
            transport="tcp",
            format="slin",
            data=stream_id)

        self._bridge: aioari.model.Bridge = await self.ari.bridges.create(type="mixing")
        self._bridged_uis = []

        await self._bridge.addChannel(channel=self.external_media_channel.id)
        await self._bridge.addChannel(channel=self.channel.id)
        self.audconn: AudioSocketConnectionAsync = await audiosocket.accept(stream_id)
        self.channel.on_event("StasisEnd", lambda *args: asyncio.create_task(self._on_channel_stasis_end(*args)))
        self.channel.on_event('ChannelDtmfReceived', lambda *args: asyncio.create_task(self._on_channel_dtmf_received(*args)))
        self.tts_engine: TTSEngine = await TTSEngine.create()
        self.transcribe_engine: TranscribeEngine = await TranscribeEngine.create()
        self.dtmf_queue = asyncio.Queue(10)
        self.dtmf_callbacks = {}
        self.text_out_queue = asyncio.Queue(1)
        self.out_media_task = asyncio.create_task(self._out_media_exchanger())
        self.to_asterisk_resampler = samplerate.Resampler('sinc_best', 1)
        self.from_asterisk_resampler = samplerate.Resampler('sinc_best', 1)

        await super().__create__()

    @property
    def ui_type(self):
        return self.UIType.VOICE

    @property
    def _unique_id(self):
        return self.channel.json["name"]

    @property
    def remote_number(self):
        """
        The phone number of the other end of the call
        """
        return self.channel.json["caller"]["number"]

    @property
    def remote_name(self):
        """
        The name (CALLERID name if available) of the other end of the call
        """
        return self.channel.json["caller"]["name"]

    @property
    def local_number(self):
        """
        The phone number of our end of the call
        """
        try:
            return self.channel.json["dialplan"]["exten"]
        except KeyError:
            return ""

    async def answer(self):
        """ Answers the call """
        logger.debug("VoiceUI.answer")
        await self.channel.answer()
        self.answered = True
        self.is_active = True

    async def hangup(self, wait=True):
        """
        Hangs up the call.
        :param wait: Whether to wait for the audio to finish playing
        """
        logger.debug("VoiceUI.hangup")
        if wait:
            # Wait for the audio to finish playing
            await self._done_speaking()

        # Cancel all tasks related to the call
        self.out_media_task.cancel()
        with suppress(asyncio.CancelledError):
            logger.debug("VoiceUI.hangup: awaiting _out_media_task")
            await self.out_media_task

        # Resources are cleaned up in _out_media_exchanger's finally block

    async def say(self, text) -> None:
        """
        Speak text to the user, waiting for speech to finish before returning
        :param text: Text to speak
        :raise: GoBackException: if the user presses *
        :raise: GotoMainException: if the user presses #
        """
        logger.debug(f"VoiceUI.say: {text}")
        # Ensure the call is answered, since we can't hear anything otherwise
        await self._ensure_answered()

        if not self.is_active:
            raise HangupException("UI is inactive, cannot say(). User probably hung up")

        # Raise the proper exception if the user presses * or #
        if hasattr(self, "_star_pressed") and self._star_pressed:
            self._star_pressed = False
            raise GoBackException("User pressed * to go back")

        # Simply add the text to the queue, the _out_media_exchanger will pick it up
        await self.text_out_queue.put(text)

    async def prompt(self, text, hint_phrases=[], hint_boost=10.0):
        """
        Prompt the user for input
        :param text: Text to prompt the user
        :param hint_phrases: list Biases the transcription towards these phrases
        :param hint_boost: float How much to boost the likelihood of these phrases, higher is more likely
        :return: The user's input
        """
        logger.debug(f"VoiceUI.prompt: {text}")
        await self._done_speaking()
        await self.say(text)
        transcription = await self.transcribe_engine.transcribe_from_stream(self.audconn, hint_phrases=hint_phrases, hint_boost=hint_boost)
        logger.debug(f"VoiceUI.prompt transcription: {transcription}")
        # Immediately stop audio playback when we get the transcription
        await self.audconn.clear_send_queue()
        if not transcription:
            await self.say("I didn't get that. Please try again.")
            return await self.prompt(text)
        return transcription

    async def gather(self, text, num_digits) -> str:
        """
        Prompt the user for dtmf input
        :param text: Text to prompt the user
        :return: The user's input
        """
        await self._done_speaking()
        await self.say(text)
        return await self._get_dtmf(num_digits=num_digits)

    async def send_dtmf(self, digits):
        """
        Send dtmf digits to the remote phone
        :param digits: The digits to send.
        """
        await self.channel.sendDTMF(dtmf=digits)

    async def ask_yes_no(self, text) -> bool:
        """
        Ask the user a yes/no question
        :param text: Text to prompt the user
        :return: True if the user answers yes or False if the user answers no
        """
        prompt = "Press 1 for yes or 2 for no"
        digits = await self.gather(f"{text} {prompt if prompt not in text else ''}", 1)
        if not digits:
            error_text = "You did not press any digit. Please try again"
            await self.say(error_text)
            return await self.ask_yes_no(text)
        if digits not in ['1', '2']:
            error_text = "Your input was invalid. Please try again. "
            await self.say(error_text)
            return await self.ask_yes_no(text)
        return digits == '1'

    async def input_stream(self):
        """
        Returns an async generator that yields transcriptions as they come
        """
        try:
            async for transcript in self.transcribe_engine.streaming_transcribe_from_stream(self.audconn):
                # Immediately stop audio playback when we get a new transcription
                await self.audconn.clear_send_queue()
                yield transcript
        except GeneratorExit:
            pass

    async def read_audio(self):
        """
        Returns audio data. Must be called repeatedly to get more audio
        :return: Audio data
        """
        return await self.audconn.read()

    async def write_audio(self, audio):
        """
        Writes audio data to be played to the remote party
        You do not need to worry about timing.
        Just dump the audio data into this method and it will be played
        :param audio: Audio data in 8000 Hz PCM
        """
        await self.audconn.write(audio)

    @asynccontextmanager
    async def run_realtime_agent(self, agent, talk_first: bool = True, model: str = None, voice: str = None, context: TContext = {}):
        """
        Connects a realtime agent to the UI
        For cheaper and slower non-realtime agents, use the run_agent method.
        :param agent: The OpenAI agents.realtime.RealtimeAgent to connect to
        :param talk_first: Whether or not to cause the agent to speak first. If False, the agent will wait for the user to speak
        :param model: The openai model to use for the agent
        :param voice: The voice to use for the agent. Some options are cedar (male) and marin (female)
        :param context: The context to use for the agent. This is passed to any agent tool calls, etc. Read about it in the OpenAI agents docs

        Use this method almost like you would use the openai agents API
        .. code-block:: python

        from asteramisk.ui import VoiceUI
        from agents.realtime import RealtimeAgent

        async def call_handler(ui: VoiceUI):
            await ui.answer()
            await ui.say("Passing control to OpenAI agent")
            agent = RealtimeAgent(
                name="Bob",
                instructions="Your agent instructions"
                tools=[]
            )
            # OpenAI docs say to use a RealtimeRunner now
            # runner = RealtimeRunner(starting_agent=agent)
            # async with await runner.run() as session:
            #     async for event in session:
            #         # Do something with the event
            #         # Handle audio, etc.
            
            # If using this library, you can use the run_agent method almost like you would use runner.run()
            async with await ui.run_agent(agent) as session:
                async for event in session:
                    # Do something with the event
                    # Audio is already handled for you
                    # Nothing really needs to be done here

        :return: An async generator that yields events from the agent
        """

        if not isinstance(agent, RealtimeAgent):
            raise ValueError("agent must be an agents.realtime.RealtimeAgent. To use a non-realtime agent, use the run_agent method instead.")

        async def asterisk_to_agent_looper(session):
            while True:
                audio = await self.audconn.read()
                # Convert to 32 bit numpy array for resampling
                audio_np = np.frombuffer(audio, dtype=np.int16).astype(np.float32)

                # Resample to 24000 Hz
                from_asterisk_ratio = OPENAI_SAMPLE_RATE / ASTERISK_SAMPLE_RATE
                resampled = self.from_asterisk_resampler.process(audio_np, from_asterisk_ratio)

                # Convert back to bytes
                resampled = resampled.astype(np.int16).tobytes()
                await session.send_audio(resampled)
        
        async def _gen():
            nonlocal model
            if model is None:
                model = config.DEFAULT_REALTIME_GPT_MODEL
            runner = RealtimeRunner(starting_agent=agent, config={
                "model_settings": {
                    "model_name": model,
                    "modalities": ["text", "audio"],
                    "voice": voice
                }
            })

            async with await runner.run(context=context) as session:
                try:
                    # Make the agent greet the caller if talk_first
                    if talk_first:
                        await session.send_message("New call, greet the caller.")

                    # Start task to send audio from Asterisk to the agent
                    asterisk_to_agent_task = asyncio.create_task(asterisk_to_agent_looper(session))
                    async for event in session:
                        if event.type == "agent_start":
                            logger.debug(f"Agent started: {event.agent.name}")
                        elif event.type == "agent_end":
                            logger.debug(f"Agent ended: {event.agent.name}")
                        elif event.type == "handoff":
                            logger.debug(f"Handoff from {event.from_agent.name} to {event.to_agent.name}")
                        elif event.type == "tool_start":
                            logger.debug(f"Tool started: {event.tool.name}")
                        elif event.type == "tool_end":
                            logger.debug(f"Tool ended: {event.tool.name}. Output: {event.output}")
                        elif event.type == "audio_end":
                            logger.debug("Audio ended")
                        elif event.type == "audio":
                            # Resample and play the audio
                            audio = event.audio.data
                            # Read from buffer as PCM 16-bit and convert to 32-bit for the resampler
                            audio_np = np.frombuffer(audio, dtype=np.int16).astype(np.int32)
                            # Calculate the resampling ratio; output_sample_rate / input_sample_rate
                            to_asterisk_ratio = ASTERISK_SAMPLE_RATE / OPENAI_SAMPLE_RATE
                            resampled = self.to_asterisk_resampler.process(audio_np, to_asterisk_ratio)
                            # Convert back to 16-bit PCM bytes for Asterisk
                            resampled = resampled.astype(np.int16).tobytes()
                            await self.write_audio(resampled)
                        elif event.type == "audio_interrupted":
                            logger.debug("Audio interrupted")
                            # Stop audio playback
                            await self.audconn.clear_send_queue()
                        elif event.type == "error":
                            pass

                        # Yield the event so the caller can use it
                        yield event

                finally:
                    # Agent session ended
                    asterisk_to_agent_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await asterisk_to_agent_task

        try:
            yield _gen()
        finally:
            # Context manager ended
            pass

    async def bridge(self, ui, absorbDTMF: bool = False, mute: bool = False):
        """
        Bridges two voice UIs together
        Media will flow between the two UIs
        :param ui: The UI to bridge to
        :param absorbDTMF: Whether to absorb (ignore or disable) DTMF events from 'ui'
        :param mute: Whether to mute audio from 'ui'
        :return: None
        """

        if ui.ui_type == self.UIType.VOICE:
            # ARI doesn't take bools but 'True'/'False' strings. 
            absorbDTMF = "True" if absorbDTMF else "False"
            mute = "True" if mute else "False"

            # Add the new UI to this UI's bridge
            await self._bridge.addChannel(channel=ui.channel.id, absorbDTMF=absorbDTMF, mute=mute)
            self._bridged_uis.append(ui)
        else:
            raise ValueError("Can only bridge VoiceUIs to VoiceUIs")


    async def unbridge(self, ui):
        """
        Disconnect a previously bridged UI.
        Media will cease to flow between them
        :param: ui: Previously bridged UI to unbridge from
        :return: None
        :raise: ValueError: If no such Ui was ever bridged
        """
        if ui not in self._bridged_uis:
            raise ValueError("No such UI was ever bridged. Unable to unbridge")
        await self._bridge.removeChannel(channel=ui.channel.id)
        self._bridged_uis.remove(ui)

    ### Voice UI specific methods ###

    async def control_say(self, text):
        logger.debug("VoiceUI.control_say")
        # Speak text, allowing rewind and fast forward
        filename = await self.tts_engine.tts_to_file(text=text, voice=self.voice, ast_filename=True)
        # Since this doesn't actually use the queue, make sure this doesn't interfere with previously queued audio
        await self._done_speaking()
        try:
            playback = await self.channel.play(media=f"sound:{filename}")
        except aiohttp.web_exceptions.HTTPNotFound as e:
            logger.error(f"Failed to play {filename}. Channel may have been destroyed")
            raise HangupException("Failed to play audio. Channel may have been destroyed") from e
        paused = False
        async def pause_toggle():
            nonlocal paused
            if paused:
                with suppress(aiohttp.web_exceptions.HTTPNotFound):
                    await playback.control(operation="unpause")
            else:
                with suppress(aiohttp.web_exceptions.HTTPNotFound):
                    await playback.control(operation="pause")
            paused = not paused

        async def rewind():
            with suppress(aiohttp.web_exceptions.HTTPNotFound):
                await playback.control(operation="reverse")

        async def forward():
            with suppress(aiohttp.web_exceptions.HTTPNotFound):
                await playback.control(operation="forward")

        self.dtmf_callbacks["4"] = rewind
        self.dtmf_callbacks["5"] = pause_toggle
        self.dtmf_callbacks["6"] = forward
        # The only way I know to wait for playback to finish is to poll until it no longer exists
        while True:
            # Sleep for 1 second, so we're not polling too often
            await asyncio.sleep(1)
            try:
                await playback.get()
            except aiohttp.web_exceptions.HTTPNotFound:
                break

        # When playback is done, remove the callbacks
        del self.dtmf_callbacks["4"]
        del self.dtmf_callbacks["5"]
        del self.dtmf_callbacks["6"]

    ### Callbacks ###

    async def _on_channel_stasis_end(self, channel, event):
        logger.debug("VoiceUI._on_channel_stasis_end")
        await self.hangup(wait=False)
        self.is_active = False

    async def _on_channel_dtmf_received(self, objs, event):
        logger.debug(f"VoiceUI._on_channel_dtmf_received: {event['digit']}")
        digit = event['digit']
        if digit == "*":
            logger.debug("VoiceUI._on_channel_dtmf_received: * pressed, setting goback flag")
            # Set the goback flag
            self._star_pressed = True
        elif digit in self.dtmf_callbacks:
            # If there's a callback for this digit, run it
            await self.dtmf_callbacks[digit]()
        else:
            # Otherwise, put it in the queue to be received as user input
            await self.dtmf_queue.put(digit)
            logger.debug(f"VoiceUI._on_channel_dtmf_received: {digit} added to queue")

    ### Private methods ###

    async def _ensure_answered(self):
        logger.debug("VoiceUI._ensure_answered")
        if not self.answered:
            logger.warning("VoiceUI._ensure_answered: Call was not explicitly answered. Answering now...")
            await self.answer()

    async def _done_speaking(self):
        logger.debug("VoiceUI._done_speaking")
        # Wait till every line of text has been sent to the player
        await self.text_out_queue.join()
        # Also wait till the last item in the queue has finished playing
        await self.audconn.drain_send_queue()

    async def _clear_dtmf_queue(self):
        while True:
            try:
                self.dtmf_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _get_dtmf(self, num_digits=None, timeout=2):
        # Clear stale data from the queue as it could have been there a long time already
        await self._clear_dtmf_queue()
        async def _timer_task():
            await self._done_speaking()
            await asyncio.sleep(timeout)
        timer_task = asyncio.create_task(_timer_task())
        digits = ""
        if num_digits:
            while len(digits) < num_digits:
                try:
                    digits += await asyncio.wait_for(self.dtmf_queue.get(), timeout=timeout)
                    # Stop sending audio if we get a digit response
                    await self.audconn.clear_send_queue()
                except asyncio.TimeoutError:
                    # Only break out of the loop if the timeout has been exceeded and we are already done playing the audio prompt
                    if timer_task.done():
                        logger.debug("VoiceUI._get_dtmf: Timed out waiting for digit")
                        await timer_task
                        break

        else:
            while True:
                try:
                    digits += await asyncio.wait_for(self.dtmf_queue.get(), timeout=timeout)
                    # Stop sending audio if we get a digit response
                    await self.audconn.clear_send_queue()
                except asyncio.TimeoutError:
                    # Only break out of the loop if the timeout has been exceeded and we are already done playing the audio prompt
                    if timer_task.done():
                        logger.debug("VoiceUI._get_dtmf: Timed out waiting for digit")
                        await timer_task
                        break

        logger.debug(f"VoiceUI._get_dtmf: Got digits: {digits}")
        return digits

    async def _out_media_exchanger(self):
        try:
            logger.debug("VoiceUI._out_media_exchanger")
            while True:
                text = await self.text_out_queue.get()
                audio = await self.tts_engine.tts(text=text, voice=self.voice)
                # Wait for the previous audio to finish playing, so that we don't get way out of sync
                await self.audconn.drain_send_queue()
                await self.audconn.write(audio)
                self.text_out_queue.task_done()
        except asyncio.CancelledError:
            logger.debug("VoiceUI._out_media_exchanger: Cancelled. Exiting")
            raise
        finally:
            logger.debug("VoiceUI._out_media_exchanger: Performing final cleanup")
            await self.audconn.close()
            await self.tts_engine.close()
            # Clean up ARI resources
            with suppress(aiohttp.web_exceptions.HTTPNotFound):
                await self._bridge.destroy()
            with suppress(aiohttp.web_exceptions.HTTPNotFound):
                await self.external_media_channel.hangup()
            with suppress(aiohttp.web_exceptions.HTTPNotFound):
                await self.channel.hangup()
            # Hangup any bridged UIs
            for ui in self._bridged_uis:
                await ui.hangup()
            # Set the active flag to false
            self.is_active = False
