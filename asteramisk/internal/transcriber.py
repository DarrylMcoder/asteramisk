import os
from pydub import AudioSegment
from google.cloud import speech_v1 as speech

from asteramisk.internal.async_singleton import AsyncSingleton
from asteramisk.internal.audiosocket_connection import AudioSocketConnectionAsync

class TranscribeEngine(AsyncSingleton):

    async def __create__(self):
        self.client = speech.SpeechAsyncClient()

    async def transcribe_request_generator(self, stream: AudioSocketConnectionAsync):
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
            requests=self.transcribe_request_generator(stream),
        ):
            if response.results and response.results[0].alternatives and response.results[0].alternatives[0].transcript:
                if response.results[0].is_final:
                    transcript = response.results[0].alternatives[0].transcript
                    print(transcript)
                    # Stop any outgoing speech when we start transcribing
                    await stream.clear_send_queue()
                    return transcript

        return ""

    async def streaming_transcribe_from_stream(self, stream: AudioSocketConnectionAsync):
        """
        Async generator that transcribes audio from a stream, yielding the transcribed text as it is spoken
        :param stream: AudioSocketConnectionAsync The stream to transcribe from
        :return: str The transcribed text
        """
        async for response in await self.client.streaming_recognize(
            requests=self.transcribe_request_generator(stream),
        ):
            if response.results and response.results[0].alternatives and response.results[0].alternatives[0].transcript:
                if response.results[0].is_final:
                    transcript = response.results[0].alternatives[0].transcript
                    print(transcript)
                    # Stop any outgoing speech when we start transcribing
                    await stream.clear_send_queue()
                    yield transcript

    def _transcribe(self, filename, hint_phrases=[]):
        """
        Synchronously transcribe the given audio file.
        Use transcribe_async if you are in an asyncronous context, which you should be if you are using this library
        """
        # convert gsm to wav
        sound = AudioSegment.from_file(filename, format="gsm")
        sound.export(filename.replace(".gsm", ".wav"), format="wav")

        with open(filename.replace(".gsm", ".wav"), "rb") as audio_file:
            content = audio_file.read()

        # Import locally because it complains about missing GOOGLE_APPLICATION_CREDENTIALS environment variable even when generating documentation
        from google.cloud import speech_v1 as speech
        audio = speech.RecognitionAudio(content=content)
        # Optimize for address recognition by loading speech hints from a file
        config = speech.RecognitionConfig(
                model="phone_call",
                sample_rate_hertz=8000,
                enable_automatic_punctuation=True,
                enable_word_time_offsets=True,
                enable_word_confidence=True,
                use_enhanced=True,
                language_code="en-US",
                speech_contexts=[
                    speech.SpeechContext(
                        phrases=hint_phrases,
                        boost=15
                        )
                    ],
                )

        request = speech.RecognizeRequest(config=config, audio=audio)

        response = self.client.recognize(request=request)

        if not response.results:
            return ""

        # debug
        print("Response: ", response)
        print("Results: ", response.results)
        print("Alternatives: ", response.results[0].alternatives)
        print("Transcript: ", response.results[0].alternatives[0].transcript)

        # delete wav file
        os.remove(filename.replace(".gsm", ".wav"))
        
        transcript = ""
        for result in response.results:
            transcript += result.alternatives[0].transcript

        return transcript
