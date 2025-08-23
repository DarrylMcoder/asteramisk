import uuid
<<<<<<< HEAD
import asyncio
from contextlib import asynccontextmanager
from panoramisk.actions import Action
from panoramisk.manager import Manager

from .ui import UI
from asteramisk.internal.tts import TTSEngine
from asteramisk.internal.transcriber import TranscribeEngine
from asteramisk.internal.audiosocket import AudiosocketAsync
from asteramisk.internal.audiosocket_connection import AudioSocketConnectionAsync
from asteramisk.config import config
=======
import aioari
import asyncio
from google.cloud import texttospeech_v1 as texttospeech

from .ui import UI
from asteramisk.config import config
from asteramisk.internal.tts import TTSEngine
from asteramisk.internal.ari_client import AriClient
from asteramisk.internal.audiosocket_connection import AudioSocketConnectionAsync
>>>>>>> asteramisk-ari

import logging
logger = logging.getLogger(__name__)

class VoiceUI(UI):
    """
    A voice user interface for Asterisk
    Provides methods such as answer(), hangup(), say(), ask_yes_no(), prompt(), and gather()
    API should be the same as the base UI class and any other UI subclasses (TextUI, etc.)
    """
    async def __create__(self, channel: aioari.model.Channel, audconn: AudioSocketConnectionAsync = None, external_media_channel: aioari.model.Channel = None, bridge: aioari.model.Bridge = None, voice=config.SYSTEM_VOICE):
        logger.debug("VoiceUI.__create__")
        self.channel = channel
        self.audconn = audconn
        self.voice = voice
        self.ari = await AriClient.create()
        self.audconn.on('error', self._on_audconn_error)
        self.tts_engine = await TTSEngine.create()
        self.transcribe_engine = await TranscribeEngine.create()
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

    async def answer(self):
        """ Answers the call """
        logger.debug("VoiceUI.answer")
        await self.channel.answer()

    async def hangup(self):
        logger.debug("VoiceUI.hangup")
        await self.audconn.close()
        await self.channel.hangup()
        self.out_media_task.cancel()

    async def say(self, text) -> None:
        """
        Speak text to the user, waiting for speech to finish before returning
        :param text: Text to speak
        :raise: GoBackException: if the user presses *
        :raise: GotoMainException: if the user presses #
        """
        logger.debug(f"VoiceUI.say: {text}")
        # Simply add the text to the queue, the _out_media_exchanger will pick it up
        await self.text_out_queue.put(text)

    async def prompt(self, text) -> str:
        """
        Prompt the user for input
        :param text: Text to prompt the user
        :return: The user's input
        """
        logger.debug(f"VoiceUI.prompt: {text}")
        # Wait till the queue is empty
        await self.text_out_queue.join()
        # Also wait till the last item in the queue has finished playing
        await self.audconn.drain_send_queue()
        logger.debug(f"VoiceUI.prompt: audio drained")
        await self.text_out_queue.put(text)
        return await self.transcribe_engine.transcribe_from_stream(stream=self.audconn)

    async def gather(self, text, num_digits) -> str:
        """
        Prompt the user for dtmf input
        :param text: Text to prompt the user
        :return: The user's input
        """
        raise NotImplementedError

    async def ask_yes_no(self, text) -> bool:
        """
        Ask the user a yes/no question
        :param text: Text to prompt the user
        :return: True if the user answers yes or False if the user answers no
        """
        prompt = f"{text} Press 1 for yes or 2 for no"
        digits = await self.gather(prompt, 1)
        return digits == '1'

    async def _on_audconn_error(self, error):
        logger.error(f"VoiceUI._on_audconn_error: {error}")
        await self.hangup()

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

