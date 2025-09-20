from google.cloud import speech_v1 as speech

from asteramisk.internal.async_class import AsyncClass
from asteramisk.internal.audiosocket_connection import AudioSocketConnectionAsync

class TranscribeEngine(AsyncClass):
    client = None

    async def __create__(self):
        # Use a global class level client rather than being a singleton
        # This is because we need to track the state of transcription per call (stream or instance)
        if self.client is None:
            self.client = speech.SpeechAsyncClient()
        self.is_transcribing = False

    async def _transcribe_request_generator(self, stream: AudioSocketConnectionAsync):
        try:
            yield speech.StreamingRecognizeRequest(
                streaming_config=speech.StreamingRecognitionConfig(
                    config=speech.RecognitionConfig(
                        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                        model="phone_call",
                        sample_rate_hertz=8000,
                        enable_automatic_punctuation=True,
                        language_code="en-US",
                        use_enhanced=True,
                    ),
                )
            )
            while stream.connected and self.is_transcribing:
                print("Transcribe loop. Waiting for audio...")
                audio = await stream.read()
                print("Transcribe loop. Got audio.")
                yield speech.StreamingRecognizeRequest(audio_content=audio)
        except GeneratorExit:
            # Exit silently when the generator is closed
            pass

    async def transcribe_from_stream(self, stream: AudioSocketConnectionAsync):
        """
        Transcribe audio from a stream
        :param stream: AudioSocketConnectionAsync The stream to transcribe from
        :return: str The transcribed text
        """
        self.is_transcribing = True
        responses = await self.client.streaming_recognize(
            requests=self._transcribe_request_generator(stream),
        )

        async for response in responses:
            if response.results and response.results[0].alternatives and response.results[0].alternatives[0].transcript:
                if response.results[0].is_final:
                    transcript = response.results[0].alternatives[0].transcript
                    self.is_transcribing = False
                    return transcript

        return ""

    async def streaming_transcribe_from_stream(self, stream: AudioSocketConnectionAsync):
        """
        Async generator that transcribes audio from a stream, yielding the transcribed text as it is spoken
        :param stream: AudioSocketConnectionAsync The stream to transcribe from
        :return: str The transcribed text
        """
        try:
            self.is_transcribing = True
            responses = await self.client.streaming_recognize(
                requests=self._transcribe_request_generator(stream),
            )

            async for response in responses:
                if response.results and response.results[0].alternatives and response.results[0].alternatives[0].transcript:
                    if response.results[0].is_final:
                        transcript = response.results[0].alternatives[0].transcript
                        yield transcript

            # Not sure if we even get here
            self.is_transcribing = False

        except GeneratorExit:
            self.is_transcribing = False
