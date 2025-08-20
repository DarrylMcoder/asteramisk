import uuid
import base64
import asyncio
import google.protobuf.duration_pb2
import google.cloud.speech_v1 as speech
import google.cloud.texttospeech_v1 as texttospeech
from contextlib import asynccontextmanager

from .ui import UI
from asteramisk.internal.async_agi import AsyncAsteriskGatewayInterface
from asteramisk.internal.audiosocket_connection import AsyncConnection
from asteramisk.exceptions import GoBackException, GoToMainException, AGIException
from asteramisk.config import config

import logging
logger = logging.getLogger(__name__)

class VoiceUI(UI):
    tts_client = None
    transcribe_client = None
    """
    A voice user interface for Asterisk
    Provides methods such as answer(), hangup(), say(), ask_yes_no(), prompt(), and gather()
    API should be the same as the base UI class and any other UI subclasses (TextUI, etc.)
    """
    async def __create__(self, audconn: AsyncConnection, voice=config.SYSTEM_VOICE):
        logger.debug("VoiceUI.__create__")
        self.voice = voice
        self.audconn = audconn
        self.audconn.on('error', self._on_audconn_error)
        self.is_transcribing = asyncio.Event()
        self.text_in_queue = asyncio.Queue(1)
        self.text_out_queue = asyncio.Queue(1)
        self.text_out_say_done = asyncio.Event()
        self.out_media_task = asyncio.create_task(self._out_media_exchanger())
        self.in_media_task = asyncio.create_task(self._in_media_exchanger())
        if not config.GOOGLE_APPLICATION_CREDENTIALS:
            raise Exception("VoiceUI.__create__: GOOGLE_APPLICATION_CREDENTIALS is not set")
        if not self.tts_client:
            self.tts_client = texttospeech.TextToSpeechAsyncClient()
        if not self.transcribe_client:
            self.transcribe_client = speech.SpeechAsyncClient()
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

    async def hangup(self):
        logger.debug("VoiceUI.hangup")
        await self.audconn.close()
        self.out_media_task.cancel()
        self.in_media_task.cancel()

    async def _on_audconn_error(self, error):
        logger.error(f"VoiceUI._on_audconn_error: {error}")
        await self.hangup()

    async def _out_media_exchanger(self):
        logger.debug("VoiceUI._out_media_exchanger")
        try:
            while True:
                ### Get the text in the output queue, convert it to speech, and send it out over the AudioSocket
                text = await self.text_out_queue.get()
                # Convert text to speech using google tts api
                input = texttospeech.SynthesisInput(text=text)
                voice = texttospeech.VoiceSelectionParams(language_code="en-US", name=self.voice)
                audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.LINEAR16, sample_rate_hertz=8000)
                response = await self.tts_client.synthesize_speech(input=input, voice=voice, audio_config=audio_config)
                # Send the audio over the AudioSocket
                await self.audconn.write(response.audio_content)
                await self.audconn.drain()
                self.text_out_say_done.set()
        except Exception as e:
            logger.error(f"VoiceUI._out_media_exchanger: {e}")

    async def transcribe_request_generator(self):
        yield speech.StreamingRecognizeRequest(
            streaming_config=speech.StreamingRecognitionConfig(
                config=speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=8000,
                    language_code="en-US",
                ),
                enable_voice_activity_events=True
            )
        )
        while True:
            if self.is_transcribing.is_set():
                audio = await self.audconn.read()
                yield speech.StreamingRecognizeRequest(audio_content=audio)
            else:
                break

    async def _in_media_exchanger(self):
        logger.debug("VoiceUI._in_media_exchanger")
        try:
            while True:
                ### Get the audio in the input queue, convert it to text, and put it in the input queue
                # Wait till we should be transcribing
                await self.is_transcribing.wait()
                responses = await self.transcribe_client.streaming_recognize(requests=self.transcribe_request_generator())
                async for response in responses:
                    print("Got response")
                    if response.speech_event_type == speech.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_BEGIN:
                        logger.info("Speech activity begin, clearing send queue")
                        await self.audconn.clear_send_queue()
                    if response.results and response.results[0].alternatives and response.results[0].alternatives[0].transcript:
                        logger.info(f"Got transcript: {response.results[0].alternatives[0].transcript}")
                        await self.text_in_queue.put(response.results[0].alternatives[0].transcript)

        except Exception as e:
            logger.error(f"VoiceUI._in_media_exchanger: {e}")

    async def say_no_wait(self, text) -> None:
        """
        Speak text to the user, but don't wait for it to finish before returning
        :param text: Text to speak
        :raise: GoBackException: if the user presses *
        :raise: GotoMainException: if the user presses #
        """
        logger.info(f"{self._unique_id}: speaking: {text}")
        self.text_out_say_done.clear()
        await self.text_out_queue.put(text)

    async def say(self, text) -> None:
        """
        Speak text to the user, waiting for speech to finish before returning
        :param text: Text to speak
        :raise: GoBackException: if the user presses *
        :raise: GotoMainException: if the user presses #
        """
        await self.say_no_wait(text)
        logger.info("Waiting for speech to finish")
        await self.text_out_say_done.wait()
        logger.info("Speech finished")

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
        raise NotImplementedError

    async def prompt(self, text) -> str:
        """
        Prompt the user for input
        :param text: Text to prompt the user
        :return: The user's input
        """
        await self.say_no_wait(text)
        logger.info("Said prompt")
        async with self.event_set(self.is_transcribing):
            logger.info("Waiting for user input")
            return await self.text_in_queue.get()

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


