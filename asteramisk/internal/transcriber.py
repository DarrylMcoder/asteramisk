import asyncio

from google.cloud import speech_v1 as speech
from google.api_core.exceptions import OutOfRange
from google.protobuf import duration_pb2

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

    async def _transcribe_request_generator(self, stream: AudioSocketConnectionAsync, hint_phrases: list = [], hint_boost: float = 10.0, speech_start_timeout: float = None, speech_started: asyncio.Event = None):
        voice_activity_timeout = None
        if speech_start_timeout is not None:
            timeout = duration_pb2.Duration()
            timeout.FromMilliseconds(round(speech_start_timeout * 1000))
            voice_activity_timeout = speech.StreamingRecognitionConfig.VoiceActivityTimeout(
                speech_start_timeout=timeout,
            )
        logger.debug(
            "Starting Google speech request stream with speech_start_timeout=%s",
            speech_start_timeout,
        )
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
                interim_results=speech_started is not None,
                enable_voice_activity_events=speech_start_timeout is not None or speech_started is not None,
                voice_activity_timeout=voice_activity_timeout,
            )
        )
        while stream.connected and self.is_transcribing:
            audio = await stream.read()
            yield speech.StreamingRecognizeRequest(audio_content=audio)

    async def _transcribe_from_stream(self, stream: AudioSocketConnectionAsync, hint_phrases: list = [], hint_boost: float = 10.0, speech_start_timeout: float = None, speech_started: asyncio.Event = None):
        try:
            responses = await self.client.streaming_recognize(
                requests=self._transcribe_request_generator(stream, hint_phrases, hint_boost, speech_start_timeout, speech_started),
            )

            async for response in responses:
                if response.speech_event_type != speech.StreamingRecognizeResponse.SpeechEventType.SPEECH_EVENT_UNSPECIFIED:
                    logger.debug(
                        "Google speech event: %s",
                        response.speech_event_type.name,
                    )
                if response.speech_event_type == speech.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_TIMEOUT:
                    logger.debug("Google reported speech activity timeout")
                    return ""
                if response.results and response.results[0].alternatives and response.results[0].alternatives[0].transcript:
                    if speech_started is not None:
                        speech_started.set()
                    if response.results[0].is_final:
                        transcript = response.results[0].alternatives[0].transcript
                        return transcript

            logger.debug("Google speech response stream ended without a transcript")
            return ""

        except OutOfRange as e:
            logger.error(e.message)

    async def transcribe_from_stream(self, stream: AudioSocketConnectionAsync, hint_phrases: list = [], hint_boost: float = 10.0, speech_start_timeout: float = None, speech_started: asyncio.Event = None):
        """
        Transcribe audio from a stream
        :param stream: AudioSocketConnectionAsync The stream to transcribe from
        :param hint_phrases: list Biases the transcription towards these phrases
        :param hint_boost: float How much to boost the likelihood of these phrases, higher is more likely
        :param speech_start_timeout: Seconds to wait for speech to begin
        :param speech_started: Event set when a non-empty transcript is available
        :return: str The transcribed text
        """
        # Wrapper method to set the is_transcribing flag
        # Cant be done in the internal method because the streaming_transcribe_from_stream method also uses it
        self.is_transcribing = True
        logger.debug("Transcription started")
        try:
            return await self._transcribe_from_stream(stream, hint_phrases, hint_boost, speech_start_timeout, speech_started)
        finally:
            self.is_transcribing = False
            logger.debug("Transcription stopped")

    async def streaming_transcribe_from_stream(self, stream: AudioSocketConnectionAsync, hint_phrases: list = [], hint_boost: float = 10.0):
        """
        Async generator that transcribes audio from a stream, yielding the transcribed text as it is spoken
        :param stream: AudioSocketConnectionAsync The stream to transcribe from
        :param hint_phrases: list Biases the transcription towards these phrases
        :param hint_boost: float How much to boost the likelihood of these phrases, higher is more likely
        :return: str The transcribed text
        """

        self.is_transcribing = True
        try:
            while self.is_transcribing:
                transcript = await self._transcribe_from_stream(stream, hint_phrases, hint_boost)
                yield transcript

        finally:
            self.is_transcribing = False
