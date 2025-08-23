import uuid
import aioari
import asyncio
from google.cloud import texttospeech_v1 as texttospeech

from .ui import UI
from asteramisk.config import config
from asteramisk.internal.tts import TTSEngine
from asteramisk.internal.ari_client import AriClient
from asteramisk.internal.audiosocket_connection import AudioSocketConnectionAsync

import logging
logger = logging.getLogger(__name__)

class VoiceUI(UI):
    """
    A voice user interface for Asterisk
    Provides methods such as answer(), hangup(), say(), ask_yes_no(), prompt(), and gather()
    API should be the same as the base UI class and any other UI subclasses (TextUI, etc.)
    """
    # Generate a list of 1000 available ports
    external_media_ports = [x for x in range(50000, 51000)]

    async def __create__(self, channel: aioari.model.Channel, audconn: AudioSocketConnectionAsync = None, external_media_channel: aioari.model.Channel = None, bridge: aioari.model.Bridge = None, voice=config.SYSTEM_VOICE):
        self.texttospeech_client = texttospeech.TextToSpeechAsyncClient()
        self.ari = await AriClient.create()
        self.tts = await TTSEngine.create()
        self.channel = channel
        self.audconn = audconn
        self.voice = voice
        self.channel.on_event('StasisEnd', lambda *args: self.hangup)
        await super().__create__()

    @property
    def ui_type(self):
        return self.UIType.VOICE

    async def answer(self):
        """ Answers the call """
        await self.channel.answer()

    async def hangup(self):
        """ Hangs up the call """
        await self.channel.hangup()
