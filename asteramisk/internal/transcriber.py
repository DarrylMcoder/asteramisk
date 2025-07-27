import os
import asyncio
from pydub import AudioSegment

class TranscribeEngine:
    _instance = None

    def __init__(self):
        if not TranscribeEngine._instance:
            TranscribeEngine._instance = self
        else:
            return TranscribeEngine._instance
        self.thread = None
        self.transcript = None
        self.exception = None
        # Import locally because it complains about missing GOOGLE_APPLICATION_CREDENTIALS environment variable even when generating documentation
        from google.cloud import speech_v1 as speech
        self.client = speech.SpeechClient()

    async def transcribe_async(self, filename, hint_phrases=[]) -> str:
        """
        Asynchronously transcribe the given audio file.
        :param filename: The full path to the audio file. Must be a .gsm file, which is the format commonly used by asterisk
        :return: The transcribed text
        """
        return await asyncio.to_thread(self._transcribe, filename, hint_phrases)

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
