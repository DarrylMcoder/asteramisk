import aiohttp
import uuid
import aioari
import asyncio
import websockets
from contextlib import suppress
from agents import Agent, TContext
from agents.realtime import RealtimeAgent, RealtimeRunner

from asteramisk.config import config
from asteramisk.ui import UI
from asteramisk.exceptions import HangupException
from asteramisk.internal.tts import TTSEngine
from asteramisk.internal.transcriber import TranscribeEngine
from asteramisk.internal.ari_client import AriClient
from asteramisk.internal.audiosocket import AudiosocketAsync
from asteramisk.internal.audiosocket_connection import AudioSocketConnectionAsync


import logging
logger = logging.getLogger(__name__)

class VoiceUI(UI):
    """
    A voice user interface for Asterisk
    Provides methods such as answer(), hangup(), say(), ask_yes_no(), prompt(), and gather()
    API should be the same as the base UI class and any other UI subclasses (TextUI, etc.)
    """
    async def __create__(self, channel: aioari.model.Channel, voice=config.SYSTEM_VOICE):
        logger.debug("VoiceUI.__create__")
        self.channel = channel
        self.voice = voice
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

        self.bridge: aioari.model.Bridge = await self.ari.bridges.create(type="mixing")

        await self.bridge.addChannel(channel=self.external_media_channel.id)
        await self.bridge.addChannel(channel=self.channel.id)
        self.audconn: AudioSocketConnectionAsync = await audiosocket.accept(stream_id)
        self.channel.on_event('StasisEnd', lambda *args: asyncio.create_task(self._on_channel_stasis_end(*args)))
        self.channel.on_event('ChannelDtmfReceived', lambda *args: asyncio.create_task(self._on_channel_dtmf_received(*args)))
        self.tts_engine: TTSEngine = await TTSEngine.create()
        self.transcribe_engine: TranscribeEngine = await TranscribeEngine.create()
        self.dtmf_queue = asyncio.Queue(10)
        self.dtmf_callbacks = {}
        self.text_out_queue = asyncio.Queue(1)
        self.out_media_task = asyncio.create_task(self._out_media_exchanger())
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

    async def hangup(self, drain_first=False):
        """
        Hangs up the call.
        :param drain_first: If True, wait for the audio to finish playing before hanging up
        """
        logger.debug("VoiceUI.hangup")
        if drain_first:
            # Wait for the audio to finish playing
            await self._done_speaking()

        # Stop the agent if connected
        await self.disconnect_openai_agent()

        # Cancel the main task, which handles any cleanup in its finally block
        self.out_media_task.cancel()
        with suppress(asyncio.CancelledError):
            await self.out_media_task
        self.out_media_task = None

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

        # Simply add the text to the queue, the _out_media_exchanger will pick it up
        await self.text_out_queue.put(text)

    async def prompt(self, text):
        """
        Prompt the user for input
        :param text: Text to prompt the user
        :return: The user's input
        """
        logger.debug(f"VoiceUI.prompt: {text}")
        await self._done_speaking()
        await self.say(text)
        transcription = await self.transcribe_engine.transcribe_from_stream(self.audconn)
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

    async def connect_openai_agent(self, agent, talk_first: bool = True, model: str = None, voice: str = None, context: TContext = None) -> asyncio.Task:
        """
        Connects the voice UI to an OpenAI agent
        Example usage:
        .. code-block:: python
            from asteramisk.ui import VoiceUI
            from asteramisk.server import Server

            async def call_handler(ui: VoiceUI):
                await ui.answer()
                await ui.say("Passing control to OpenAI agent")
                bob = RealtimeAgent(
                    name="Bob",
                    instructions="Your agent instructions"
                )
                await ui.connect_openai_agent(bob, model="gpt-4o-realtime-preview", voice="Cedar")
                # Control of the conversation is now passed to the OpenAI agent
                # You can use OpenAI's tool calling to manage your conversation flow
                # You can still use the UI, but the agent is also in the conversation so it would likely be better not to play any audio

        :param agent: The OpenAI agent to connect to, either an agents.Agent or agents.realtime.RealtimeAgent
        :param talk_first: Whether or not the agent should speak first
        :param model: The OpenAI model to use
        :param voice: The OpenAI realtime voice to use. Only has an effect if agent is an agents.realtime.RealtimeAgent
        :return: A task that will run the OpenAI agent. You can await this task to wait for the agent to finish
        """
        async def _run_agent_task():
            logger.debug("VoiceUI.connect_openai_agent._run_agent_task")
            nonlocal model # We might change the model so we need to declare it a nonlocal
            try:
                if isinstance(agent, Agent):
                    await self._run_text_agent(agent=agent, talk_first=talk_first, model=model)
                elif isinstance(agent, RealtimeAgent):
                    await self.audconn.set_resampling(rate=24000, channels=1, audio_format="s16le")
                    if model is None:
                        # Use the cheaper mini model rather than the default GPT-4o
                        model = config.DEFAULT_REALTIME_GPT_MODEL
                    runner = RealtimeRunner(starting_agent=agent, config={
                        "model_settings": {
                            "model_name": model,
                            "modalities": ["text", "audio"],
                            "voice": voice
                        }
                    })
                    async with await runner.run(context=context) as session:
                        if talk_first:
                            # The agent is expected to speak first. E.g. answering a phone call
                            with suppress(websockets.exceptions.ConnectionClosed):
                                # Clean up should be handled elsewhere so just swallow the exception
                                await session.send_message("New call, greet the caller.")
                        async def dtmf_event_handler(objs, event):
                            with suppress(websockets.exceptions.ConnectionClosed, AssertionError):
                                # AssertionError, not connected
                                await session.send_message(event['digit'])
                        self.channel.on_event('ChannelDtmfReceived', dtmf_event_handler)
                        async def audio_loop():
                            # Directly pass audio from the UI to the OpenAI session
                            while self.is_active:
                                logger.debug("audio_loop: Waiting for audio")
                                audio = await self.audconn.read()
                                try:
                                    await session.send_audio(audio)
                                except websockets.exceptions.ConnectionClosed:
                                    break
                        self._audio_task = asyncio.create_task(audio_loop())
                        async for event in session:
                            logger.debug(event.type)
                            if event.type == "audio":
                                audio = event.audio.data
                                await self.audconn.write(audio)
                            elif event.type == "audio_interrupted":
                                # Audio was interrupted, stop speaking and listen
                                await self.audconn.clear_send_queue()
                            elif event.type == "raw_model_event":
                                logger.debug(f"  {event.data.type}")
                                if event.data.type == "raw_server_event":
                                    logger.debug(f"     {event.data.data['type']}")
                            elif event.type == "error":
                                logger.error(f"OpenAI session error: {event}")
                else:
                    raise ValueError("agent must be an agents.Agent or agents.realtime.RealtimeAgent")
            finally:
                # Clean up agent resources
                if hasattr(self, "_audio_task") and self._audio_task is not None:
                    self._audio_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._audio_task
                    self._audio_task = None
                # Stop resampling which is only used for agents
                await self.audconn.stop_resampling()
        # end _run_agent_task

        # Wait for any previously queued audio to finish before connecting
        await self._done_speaking()
        # Disconnect any previous agent
        await self.disconnect_openai_agent()
        # Run the agent in a separate task
        self._agent_task = asyncio.create_task(_run_agent_task())
        return self._agent_task

    async def disconnect_openai_agent(self):
        """
        Disconnects the voice UI from any currently connected OpenAI agent.
        Currently quite buggy so use with caution.
        Once connected, agents generally run until the conversation ends.
        """
        # Wait till the agent has finished speaking
        await self._done_speaking()
        # Disconnect the agent
        if hasattr(self, "_agent_task") and self._agent_task is not None:
            self._agent_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._agent_task
            self._agent_task = None

    ### Voice UI specific methods ###

    async def control_say(self, text):
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

    async def _on_channel_stasis_end(self, objs, event):
        logger.debug("VoiceUI._on_channel_stasis_end")
        logger.info("Caller has hung up, so we are also hanging up")
        # The call has ended, clean up
        await self.hangup()

    async def _on_channel_dtmf_received(self, objs, event):
        logger.debug(f"VoiceUI._on_channel_dtmf_received: {event['digit']}")
        digit = event['digit']
        if digit in self.dtmf_callbacks:
            # If there's a callback for this digit, run it
            await self.dtmf_callbacks[digit]()
        else:
            # Otherwise, put it in the queue to be received as user input
            await self.dtmf_queue.put(digit)
            logger.debug(f"VoiceUI._on_channel_dtmf_received: {digit} added to queue")

    ### Private methods ###

    async def _ensure_answered(self):
        if not self.answered:
            logger.warning("VoiceUI._ensure_answered: Call was not explicitly answered. Answering now...")
            await self.answer()

    async def _done_speaking(self):
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
        finally:
            logger.debug("VoiceUI._out_media_exchanger: Exiting")
            await self.audconn.close()
            await self.tts_engine.close()
            # Clean up ARI resources
            with suppress(aiohttp.web_exceptions.HTTPNotFound):
                await self.bridge.destroy()
            with suppress(aiohttp.web_exceptions.HTTPNotFound):
                await self.external_media_channel.hangup()
            with suppress(aiohttp.web_exceptions.HTTPNotFound):
                await self.channel.hangup()
            self.is_active = False
