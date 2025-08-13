import uuid

from .ui import UI
from asteramisk.internal.async_agi import AsyncAsteriskGatewayInterface
from asteramisk.exceptions import GoBackException, GoToMainException, AGIException
from asteramisk.config import config
from asteramisk.internal.tts import TTSEngine
from asteramisk.internal.transcriber import TranscribeEngine

import logging
logger = logging.getLogger(__name__)

class VoiceUI(UI):
    """
    A voice user interface for Asterisk
    Provides methods such as answer(), hangup(), say(), ask_yes_no(), prompt(), and gather()
    API should be the same as the base UI class and any other UI subclasses (TextUI, etc.)
    """
    async def __create__(self, channel, voice=config.SYSTEM_VOICE):
        self.agi = await AsyncAsteriskGatewayInterface.create(channel)
        self.transcriber = await TranscribeEngine.create()
        self.tts = await TTSEngine.create()
        self.voice = voice
        await super().__create__()

    @property
    def ui_type(self):
        return self.UIType.VOICE

    async def send_command(self, command):
        """
        Sends an AGI command to Asterisk
        :param: command: Command to send
        :return: dict: Result of the AGI command
        """
        return await self.agi.send_command(command)

    async def answer(self):
        """ Answers the call """
        await self.agi.connect()
        await self.send_command('ANSWER')

    async def hangup(self):
        """ Hangs up the call """
        await self.send_command('HANGUP')
        await self.agi.close()

    async def _get_data(self, filename, num_digits=None) -> str:
        """
        Get data from Asterisk. Sends GET DATA AGI command
        :param filename: Name of the file to play
        :param num_digits: Number of digits to wait for
        :return: DTMF digits
        """
        # So we don't have to wait long if we're just waiting in case of goback
        # Because i use this function for situations like play where we don't want any return data
        if num_digits is None:
            timeout = 10
            num_digits = 1
        else:
            timeout = 2000
        response = await self.send_command(f"GET DATA {filename} {timeout} {num_digits}")
        if 'error' in response and 'msg' in response:
            raise AGIException(response['msg'])
        digits = response['result'][0]
        if digits == '*':
            raise GoBackException
        if digits == '#':
            raise GoToMainException
        return digits

    async def play(self, filename) -> None:
        """
        Play file
        :param filename: Name of the file to play, without the extension
        File must be in asterisk sounds directory
        e.g. "recordings/recording".
        :raise GoBackException: If the user presses *
        :raise GoToMainException: If the user presses #
        """
        await self._get_data(filename)
        return

    async def say(self, text) -> None:
        """
        Speak text to the user
        :param text: Text to speak
        :raise: GoBackException: if the user presses *
        :raise: GotoMainException: if the user presses #
        """
        filename = await self.tts.convert_async(text, self.voice)
        await self.play(filename)
        return

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


