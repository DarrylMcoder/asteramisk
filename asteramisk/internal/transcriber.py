from google.cloud import speech_v1 as speech

from asteramisk.internal.async_singleton import AsyncSingleton
from asteramisk.internal.audiosocket_connection import AudioSocketConnectionAsync

class TranscribeEngine(AsyncSingleton):

    async def __create__(self):
        self.client = speech.SpeechAsyncClient()

    async def _transcribe_request_generator(self, stream: AudioSocketConnectionAsync):
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
        while True:
            if not stream.connected:
                return
            audio = await stream.read()
            yield speech.StreamingRecognizeRequest(audio_content=audio)


    async def transcribe_from_stream(self, stream: AudioSocketConnectionAsync):
        """
        Transcribe audio from a stream
        :param stream: AudioSocketConnectionAsync The stream to transcribe from
        :return: str The transcribed text
        """
        async for response in await self.client.streaming_recognize(
            requests=self._transcribe_request_generator(stream),
        ):
            if response.results and response.results[0].alternatives and response.results[0].alternatives[0].transcript:
                if response.results[0].is_final:
                    transcript = response.results[0].alternatives[0].transcript
                    return transcript

        return ""

    async def streaming_transcribe_from_stream(self, stream: AudioSocketConnectionAsync):
        """
        Async generator that transcribes audio from a stream, yielding the transcribed text as it is spoken
        :param stream: AudioSocketConnectionAsync The stream to transcribe from
        :return: str The transcribed text
        """
        async for response in await self.client.streaming_recognize(
            requests=self._transcribe_request_generator(stream),
        ):
            if response.results and response.results[0].alternatives and response.results[0].alternatives[0].transcript:
                if response.results[0].is_final:
                    transcript = response.results[0].alternatives[0].transcript
                    yield transcript
