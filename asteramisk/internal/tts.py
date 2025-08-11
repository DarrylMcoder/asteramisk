import os
import uuid
import asyncio
from gtts import gTTS
from pydub import AudioSegment
from google.cloud import texttospeech_v1 as texttospeech

from asteramisk.config import config
from asteramisk.internal.async_class import AsyncClass

import logging
logger = logging.getLogger(__name__)

class TTSEngine(AsyncClass):

    cache = {}
    _sounds_subdir = config.ASTERISK_TTS_SOUNDS_SUBDIR

    async def __create__(self):
        # Create the directory if it doesn't exist
        if not os.path.exists(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}"):
            os.makedirs(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}")

    def _clean_text(self, text) -> str:
        """ Make text more like file name, space to dash, lowercase, remove special characters and punctuation, newlines, tabs """
        clean_text = text.lower()
        clean_text = clean_text.replace(" ", "-")
        clean_text = clean_text.replace("?", "")
        clean_text = clean_text.replace(":", "")
        clean_text = clean_text.replace("'", "")
        clean_text = clean_text.replace('"', "")
        clean_text = clean_text.replace("/", "")
        clean_text = clean_text.replace("!", "")
        clean_text = clean_text.replace(".", "")
        clean_text = clean_text.replace(",", "")
        clean_text = clean_text.replace("\n", "")
        clean_text = clean_text.replace("\t", "")
        clean_text = clean_text.replace("--", "-")
        return clean_text

    async def convert_async(self, text, voice=None) -> str:
        """
        Asynchronously convert text to audio file using google tts api and save it to asterisk sounds directory
        This method needs access to the actual file system of the asterisk server
        In docker this is done by mounting the asterisk sounds directory as a volume in both containers
        Or you can simply run the python script directly on the asterisk server, with sufficient permissions
        :param text: Text to convert
        :param voice: Voice to use
        :return: Path to audio file relative to asterisk sounds directory
        The value returned can be used directly in Asterisk Playback command
        """
        return await asyncio.to_thread(self._convert, text, voice)

    def _convert(self, text, voice=None):
        """
        Synchronously convert text to audio file using google tts api and save it to asterisk sounds directory
        Use convert_async if you are in an asyncronous context, which you should be if you are using this library
        """
        # convert text to audio file using google tts api and save it to asterisk sounds directory
        # make text more like file name, space to dash, lowercase, remove special characters and punctuation, newlines, tabs
        if voice is None:
            if os.getenv("GOOGLE_TTS_VOICE") is not None:
                voice = os.getenv("GOOGLE_TTS_VOICE")
            else:
                # Use the default free voice
                return self._convert_old(text)

        clean_text = self._clean_text(text)

        text_and_voice = f"{clean_text}-{voice}"
        
        if os.path.exists(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}/{text_and_voice}.gsm"):
            return f"{self._sounds_subdir}/{text_and_voice}"
        elif text_and_voice in self.cache and os.path.exists(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}/{self.cache[text_and_voice]}.gsm"):
            return f"{self._sounds_subdir}/{self.cache[text_and_voice]}"
        else:
            # Create the file
            filename = text_and_voice
            if len(filename) > 200:
                filename = uuid.uuid4().hex
            self.cache[text_and_voice] = filename
            texttospeech_client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                name=voice,
                language_code="en-US",
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            response = texttospeech_client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )
            # Save the audio content to a file
            with open(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}/{filename}.mp3", "wb") as out:
                out.write(response.audio_content)

            # convert mp3 to gsm
            sound = AudioSegment.from_mp3(f"/usr/share/asterisk/sounds/{self._sounds_subdir}/{filename}.mp3")
            sound = sound.set_frame_rate(8000)
            sound.export(f"/usr/share/asterisk/sounds/{self._sounds_subdir}/{filename}.gsm", format="gsm")

            # delete mp3 file
            os.remove(f"/usr/share/asterisk/sounds/{self._sounds_subdir}/{filename}.mp3")

        return f"{self._sounds_subdir}/{filename}"

    def _convert_old(self, text):
        # convert text to audio file using tts api and save it to asterisk sounds directory
        # make text more like file name, space to dash, lowercase, remove special characters and punctuation, newlines, tabs

        clean_text = self._clean_text(text)

        text_and_voice = f"{clean_text}-google-tts"

        if os.path.exists(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}/{text_and_voice}.gsm"):
            return f"{self._sounds_subdir}/{text_and_voice}"
        elif text_and_voice in self.cache and os.path.exists(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}/{self.cache[text_and_voice]}.gsm"):
            return f"{self._sounds_subdir}/{self.cache[text_and_voice]}"
        else:
            # Create the file
            filename = text_and_voice
            if len(filename) > 200:
                filename = uuid.uuid4().hex
            self.cache[text_and_voice] = filename
            gTTS(
                tld='ca',
                text=text,
                lang='en'
            ).save(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}/{filename}.mp3")

            # convert mp3 to gsm
            sound = AudioSegment.from_mp3(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}/{filename}.mp3")
            sound = sound.set_frame_rate(8000)
            sound.export(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}/{filename}.gsm", format="gsm")

            # remove mp3
            os.remove(f"{config.ASTERISK_SOUNDS_DIR}/{self._sounds_subdir}/{filename}.mp3")

        return f"{self._sounds_subdir}/{self.cache[text_and_voice]}"
