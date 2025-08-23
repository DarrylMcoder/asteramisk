import uuid
import aioari
import asyncio
from google.cloud import texttospeech_v1 as texttospeech

from .ui import UI
from asteramisk.config import config
from asteramisk.internal.tts import TTSEngine
from asteramisk.internal.ari_client import AriClient
from asteramisk.internal.audiosockets import AudioSocket

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

    async def __create__(self, channel: aioari.model.Channel, audio_socket: AudioSocket, external_media_channel: aioari.model.Channel, bridge: aioari.model.Bridge, voice=config.SYSTEM_VOICE):
        self.texttospeech_client = texttospeech.TextToSpeechAsyncClient()
        self.ari = await AriClient.create()
        self.tts = await TTSEngine.create()
        self.text_queue = asyncio.Queue(maxsize=1)
        self.channel = channel
        self.audio_socket = audio_socket
        self.external_media_channel = external_media_channel
        self.bridge = bridge
        self.voice = voice
        self.channel.on_event('StasisEnd', lambda *args: self.hangup)
        await super().__create__()

    @property
    def ui_type(self):
        return self.UIType.VOICE

    async def _media_exchange(self):
        while True:
            packet = await self.audio_socket.read()
            await self.audio_socket.write(packet)

    async def answer(self):
        """ Answers the call """
        await self.channel.answer()

    async def hangup(self):
        """ Hangs up the call """
        await self.channel.hangup()

    async def say(self, text) -> None:
        """
        Say text to the user
        :param text: Text to say
        """
        await self.text_queue.put(text)

    async def record(self, prompt=None, filename=None, timeout=10000, playbeep=True, silence=2500):
        """
        Record audio
        :param prompt: Text to prompt
        :param filename: Name of the file to save recording to, if None a random name will be generated. Only the name, not the extension or path
        :param timeout: Maximum length of recording in milliseconds
        :param playbeep: Play a beep before recording
        :param silence: Milliseconds of silence before recording is stopped
        :return: Full path to the saved file
        """
        logger.info(f"{self._unique_id}: recording: {prompt}")
        if prompt:
            await self.say(prompt)
        if not filename:
            filename = str(uuid.uuid4())
        await self.send_command(f"RECORD FILE recordings/{filename} gsm # {timeout} 0 {'beep' if playbeep else ''} s={silence}")
        #filename = f"/usr/share/asterisk/sounds/recordings/{filename}.gsm"
        filename = f"/var/lib/asterisk/sounds/custom/{filename}.gsm"
        return filename

    async def prompt(self, text) -> str:
        """
        Prompt the user for input
        :param text: Text to prompt the user
        :return: The user's input
        """
        recording_filename = await self.record(prompt=text)
        return await self.transcriber.transcribe(recording_filename)

    async def gather(self, text, num_digits) -> str:
        """
        Prompt the user for dtmf input
        :param text: Text to prompt the user
        :return: The user's input
        """
        filename = await self.tts.convert_async(text, self.voice_name)
        return await self._get_data(filename, num_digits)

    async def ask_yes_no(self, text) -> bool:
        """
        Ask the user a yes/no question
        :param text: Text to prompt the user
        :return: True if the user answers yes or False if the user answers no
        """
        prompt = f"{text} Press 1 for yes or 2 for no"
        digits = await self.gather(prompt, 1)
        return digits == '1'


