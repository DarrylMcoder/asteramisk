from google.cloud import speech_v1 as speech
from google.api_core.exceptions import OutOfRange

from asteramisk.internal.async_class import AsyncClass
from asteramisk.internal.audiosocket_connection import AudioSocketConnectionAsync

import logging
logger = logging.getLogger(__name__)

class TranscribeEngine(AsyncClass):
    client = None

    async def __create__(self):
        # Use a global class level client rather than being a singleton
        # This is because we need to track the state of transcription per call (stream or instance)
        if self.client is None:
            self.client = speech.SpeechAsyncClient()
        self.is_transcribing = False

    async def _transcribe_request_generator(self, stream: AudioSocketConnectionAsync, hint_phrases: list = [], hint_boost: float = 10.0):
        yield speech.StreamingRecognizeRequest(
            streaming_config=speech.StreamingRecognitionConfig(
                config=speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                    speech_contexts=[
                        speech.SpeechContext(
                            phrases=hint_phrases,
                            boost=hint_boost
                        )
                    ],
                    model="phone_call",
                    sample_rate_hertz=8000,
                    enable_automatic_punctuation=True,
                    language_code="en-US",
                    use_enhanced=True,
                ),
            )
        )
        while stream.connected and self.is_transcribing:
            audio = await stream.read()
            yield speech.StreamingRecognizeRequest(audio_content=audio)

    async def transcribe_from_stream(self, stream: AudioSocketConnectionAsync, hint_phrases: list = [], hint_boost: float = 10.0):
        """
        Transcribe audio from a stream
        :param stream: AudioSocketConnectionAsync The stream to transcribe from
        :param hint_phrases: list Biases the transcription towards these phrases
        :param hint_boost: float How much to boost the likelihood of these phrases, higher is more likely
        :return: str The transcribed text
        """
        self.is_transcribing = True
        try:
            responses = await self.client.streaming_recognize(
                requests=self._transcribe_request_generator(stream, hint_phrases, hint_boost),
            )

            async for response in responses:
                if response.results and response.results[0].alternatives and response.results[0].alternatives[0].transcript:
                    if response.results[0].is_final:
                        transcript = response.results[0].alternatives[0].transcript
                        self.is_transcribing = False
                        return transcript

            return ""

        except OutOfRange as e:
            logger.error(e.message)
        finally:
            self.is_transcribing = False

    async def streaming_transcribe_from_stream(self, stream: AudioSocketConnectionAsync, hint_phrases: list = [], hint_boost: float = 10.0):
        """
        Async generator that transcribes audio from a stream, yielding the transcribed text as it is spoken
        :param stream: AudioSocketConnectionAsync The stream to transcribe from
        :param hint_phrases: list Biases the transcription towards these phrases
        :param hint_boost: float How much to boost the likelihood of these phrases, higher is more likely
        :return: str The transcribed text
        """
        self.is_transcribing = True
        responses = await self.client.streaming_recognize(
            requests=self._transcribe_request_generator(stream, hint_phrases, hint_boost),
        )
        try:
            async for response in responses:
                if response.results and response.results[0].alternatives and response.results[0].alternatives[0].transcript:
                    if response.results[0].is_final:
                        transcript = response.results[0].alternatives[0].transcript
                        yield transcript

        except OutOfRange as e:
            logger.error(e.message)
        finally:
            self.is_transcribing = False
