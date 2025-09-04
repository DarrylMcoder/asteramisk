import aiohttp
import uuid
import aioari
import asyncio
from contextlib import asynccontextmanager, suppress

from .ui import UI
from asteramisk.internal.tts import TTSEngine
from asteramisk.internal.transcriber import TranscribeEngine
from asteramisk.internal.ari_client import AriClient
from asteramisk.internal.audiosocket import AudiosocketAsync, AudioSocketConnectionAsync
from asteramisk.config import config


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
            external_host=f"{config.ASTERISK_HOST}:{config.AUDIOSOCKET_PORT}",
            encapsulation="audiosocket",
            app="general",
            transport="tcp",
            format="slin",
            data=stream_id)

        self.bridge: aioari.model.Bridge = await self.ari.bridges.create(type="mixing")

        await self.bridge.addChannel(channel=self.external_media_channel.id)
        await self.bridge.addChannel(channel=self.channel.id)
        self.audconn: AudiosocketConnectionAsync = await audiosocket.accept(stream_id)
        self.channel.on_event('StasisEnd', self._on_channel_stasis_end)
        self.channel.on_event('ChannelDtmfReceived', self._on_channel_dtmf_received)
        self.tts_engine: TTSEngine = await TTSEngine.create()
        self.transcribe_engine: TranscribeEngine = await TranscribeEngine.create()
        self.dtmf_queue = asyncio.Queue(1)
        self.dtmf_callbacks = {}
        self.text_out_queue = asyncio.Queue(1)
        self.out_media_task = asyncio.create_task(self._out_media_exchanger())
        await super().__create__()

    @asynccontextmanager
    async def event_set(self, event: asyncio.Event):
        event.set()
        try:
            yield
        finally:
            event.clear()

    @property
    def ui_type(self):
        return self.UIType.VOICE

    @property
    def _unique_id(self):
        return self.channel.json["name"]

    async def answer(self):
        """ Answers the call """
        logger.debug("VoiceUI.answer")
        await self.channel.answer()
        self.answered = True

    async def hangup(self):
        logger.debug("VoiceUI.hangup")
        await self.audconn.hangup()
        await self.external_media_channel.hangup()
        await self.channel.hangup()
        await self.bridge.destroy()
        self.out_media_task.cancel()

    async def say(self, text) -> None:
        """
        Speak text to the user, waiting for speech to finish before returning
        :param text: Text to speak
        :raise: GoBackException: if the user presses *
        :raise: GotoMainException: if the user presses #
        """
        logger.debug(f"VoiceUI.say: {text}")
        # Ensure the call is answered, since we can't hean anything otherwise
        await self._ensure_answered()
        # Simply add the text to the queue, the _out_media_exchanger will pick it up
        await self.text_out_queue.put(text)

    async def prompt(self, text):
        """
        Prompt the user for input
        :param text: Text to prompt the user
        :return: The user's input
        """
        logger.debug(f"VoiceUI.prompt: {text}")
        # Ensure the call is answered, since we can't hean anything otherwise
        await self._ensure_answered()
        # Wait till the queue is empty
        await self.text_out_queue.join()
        # Also wait till the last item in the queue has finished playing
        await self.audconn.drain_send_queue()
        await self.text_out_queue.put(text)
        return await self.transcribe_engine.transcribe_from_stream(self.audconn)

    async def gather(self, text, num_digits) -> str:
        """
        Prompt the user for dtmf input
        :param text: Text to prompt the user
        :return: The user's input
        """
        await self._ensure_answered()
        await self.text_out_queue.join()
        await self.audconn.drain_send_queue()
        await self.text_out_queue.put(text)
        return await self._get_dtmf(num_digits=num_digits)

    async def ask_yes_no(self, text) -> bool:
        """
        Ask the user a yes/no question
        :param text: Text to prompt the user
        :return: True if the user answers yes or False if the user answers no
        """
        prompt = f"{text} Press 1 for yes or 2 for no"
        digits = await self.gather(prompt, 1)
        return digits == '1'

    async def input_stream(self):
        """
        Returns an async generator that yields transcriptions as they come
        """
        async for transcript in self.transcribe_engine.streaming_transcribe_from_stream(self.audconn):
            yield transcript

    async def control_say(self, text):
        # Speak text, allowing rewind and fast forward
        filename = await self.tts_engine.tts_to_file(text=text, voice=self.voice, ast_filename=True)
        playback = await self.channel.play(media="sound:%s" % filename)
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
            
    async def _on_channel_stasis_end(self, objs, event):
        logger.debug("VoiceUI._on_channel_stasis_end")
        await self.audconn.hangup()
        await asyncio.sleep(0.1)
        await self.audconn.close()
        with suppress(aiohttp.web_exceptions.HTTPNotFound):
            await self.external_media_channel.hangup()
        await self.bridge.destroy()
        self.out_media_task.cancel()
        self.connected = False

    async def _on_channel_dtmf_received(self, objs, event):
        logger.debug(f"VoiceUI._on_channel_dtmf_received: {event['digit']}")
        digit = event['digit']
        if digit in self.dtmf_callbacks:
            # If there's a callback for this digit, run it
            await self.dtmf_callbacks[digit]()
        else:
            # Otherwise, put it in the queue to be received as user input
            await self.dtmf_queue.put(digit)

    async def _on_audconn_error(self, error):
        logger.error(f"VoiceUI._on_audconn_error: {error}")
        await self.hangup()

    async def _ensure_answered(self):
        if not self.answered:
            logger.warning("VoiceUI._ensure_answered: Call was not explicitly answered. Answering now...")
            await self.answer()

    async def _get_transcript(self):
        return await self.transcribe_engine.transcribe_from_stream(self.audconn)

    async def _clear_dtmf_queue(self):
        while True:
            try:
                await self.dtmf_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _get_dtmf(self, num_digits=None, timeout=2):
        # Clear stale data from the queue as it could have been there a long time already
        await self._clear_dtmf_queue()
        digits = ""
        if num_digits:
            while len(digits) < num_digits:
                try:
                    digits += await asyncio.wait_for(self.dtmf_queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
        else:
            while True:
                try:
                    digits += await asyncio.wait_for(self.dtmf_queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
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
        except Exception as e:
            logger.exception(f"VoiceUI._out_media_exchanger: {e}")

