import os
import io
import wave
import uuid
import asyncio
from gtts import gTTS
from pydub import AudioSegment
from contextlib import suppress
from google.cloud import texttospeech_v1 as texttospeech

from asteramisk.config import config
from asteramisk.internal.lru_cache import LRUCache
from asteramisk.internal.async_singleton import AsyncSingleton

import logging
logger = logging.getLogger(__name__)

class TTSEngine(AsyncSingleton):
    async def __create__(self):
        # Create the directory if it doesn't exist
        assert config.ASTERISK_SOUNDS_DIR is not None
        assert config.ASTERISK_TTS_SOUNDS_SUBDIR is not None
        if not os.path.exists(f"{config.ASTERISK_SOUNDS_DIR}/{config.ASTERISK_TTS_SOUNDS_SUBDIR}"):
            os.makedirs(f"{config.ASTERISK_SOUNDS_DIR}/{config.ASTERISK_TTS_SOUNDS_SUBDIR}")

        self._client = texttospeech.TextToSpeechAsyncClient()
        self.cache_tasks = []
        self.cache = LRUCache(maxsize=1000)
        self._cache_lock = asyncio.Lock()

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

    async def _premium_tts(self, text, voice=None):
        input = texttospeech.SynthesisInput(text=text)
        voice_params = texttospeech.VoiceSelectionParams(
            language_code='en-US',
            name=voice
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=8000
        )
        response = await self._client.synthesize_speech(input=input, voice=voice_params, audio_config=audio_config)
        return response.audio_content

    async def _free_tts(self, text):
        """ Use gTTS to convert text to audio and return the audio content """
        def sync_tts():
            tts = gTTS(
                tld='ca',
                text=text,
                lang='en'
            )
            mp3_fp = io.BytesIO()
            tts.write_to_fp(mp3_fp)
            mp3_fp.seek(0)
            # Convert mp3 to raw
            audio = AudioSegment.from_mp3(mp3_fp)
            audio_8khz = audio.set_frame_rate(8000)
            raw_audio = audio_8khz.set_channels(1).set_sample_width(2).raw_data

            del tts
            del audio
            mp3_fp.close()
            return raw_audio

        return await asyncio.to_thread(sync_tts)

    async def tts(self, text, voice=None, save_to_cache=True):
        """
        Asynchronously convert text to audio and stream it to the given stream
        """
        logger.debug("TTSEngine.tts: converting text to audio")
        # Check if the audio is cached
        cached_audio = await self.get_from_cache(text, voice)
        if cached_audio is not None:
            logger.debug("TTSEngine.tts: using cached audio file")
            return cached_audio

        # Not cached, convert text to audio
        audio = None
        if not voice or not config.GOOGLE_APPLICATION_CREDENTIALS:
            # Voice not specified or no credentials, so use gTTS which is free and requires no credentials
            audio = await self._free_tts(text)
        else:
            # Use google cloud tts which requires credentials
            audio = await self._premium_tts(text, voice)

        # Trim the chirp 
        if audio and len(audio) > 0:
            audio_segment = AudioSegment(
                data=audio,
                sample_width=2,
                frame_rate=8000,
                channels=1
            )
            # Trim chirp (first 80 ms)
            audio = audio_segment[80:].raw_data
        if save_to_cache:
            async with self._cache_lock:
                # Make sure cache_tasks list doesn't grow too long by removing completed tasks
                self.cache_tasks = [task for task in self.cache_tasks if not task.done()]
                self.cache_tasks.append(asyncio.create_task(self.save_to_cache(audio, text, voice)))
        if not audio or len(audio) == 0:
            logger.error("TTSEngine.tts: no audio returned")
        return audio

    async def tts_to_stream(self, text, stream, voice=None):
        audio = await self.tts(text, voice)
        await stream.write(audio)
        return

    async def tts_to_file(self, text, voice=None, ast_filename=True):
        """
        Convert text to audio and save it to a file
        :param text: The text to convert to audio
        :param voice: The voice to use, e.g. 'en-US-Wavenet-A'
        :param ast_filename: The format of the filename that is returned, If True, the filename will be
        relative to the asterisk sound directory, and ready for direct use in asterisk. If False, the filename
        will be the full path to the file.
        :return: The filename of the audio file.
        """
        audio = await self.tts(text, voice, save_to_cache=False)
        filename = await self.save_to_cache(audio, text, voice)
        logger.info(f"TTSEngine.tts_to_file: saved audio file to {filename}")
        if ast_filename:
            filename = f"{config.ASTERISK_TTS_SOUNDS_SUBDIR}/{filename}"
        else:
            filename = f"{config.ASTERISK_SOUNDS_DIR}/{config.ASTERISK_TTS_SOUNDS_SUBDIR}/{filename}.wav"
        return filename

    async def save_to_wav(self, audio, filename, sample_width=2, channels=1, sample_rate=8000):
        def _save_to_wav():
            full_path = f"{config.ASTERISK_SOUNDS_DIR}/{config.ASTERISK_TTS_SOUNDS_SUBDIR}/{filename}.wav"
            with wave.open(full_path, "wb") as f:
                f.setnchannels(channels)
                f.setsampwidth(sample_width)
                f.setframerate(sample_rate)
                f.writeframes(audio)
            return filename
        return await asyncio.to_thread(_save_to_wav)

    async def read_from_wav(self, filename):
        def _read_from_wav():
            with wave.open(f"{config.ASTERISK_SOUNDS_DIR}/{config.ASTERISK_TTS_SOUNDS_SUBDIR}/{filename}.wav", "rb") as f:
                return f.readframes(f.getnframes())
        return await asyncio.to_thread(_read_from_wav)

    async def exists_in_cache(self, text, voice='gtts-en-ca') -> bool:
        text = self._clean_text(text)
        text_and_voice = f"{text}-{voice}"
        return text_and_voice in self.cache and os.path.exists(f"{config.ASTERISK_SOUNDS_DIR}/{config.ASTERISK_TTS_SOUNDS_SUBDIR}/{self.cache[text_and_voice]}.wav")

    async def get_from_cache(self, text, voice='gtts-en-ca'):
        text = self._clean_text(text)
        text_and_voice = f"{text}-{voice}"
        if text_and_voice in self.cache:
            filename = self.cache[text_and_voice]
            filepath = f"{config.ASTERISK_SOUNDS_DIR}/{config.ASTERISK_TTS_SOUNDS_SUBDIR}/{filename}.wav"
            if os.path.exists(filepath):
                return await self.read_from_wav(filename)
        return None

    async def save_to_cache(self, audio_content, text, voice='gtts-en-ca'):
        """ Save the audio content to the cache """
        logger.debug("TTSEngine.save_to_cache: saving audio file to cache")
        # Create the file
        text = self._clean_text(text)
        text_and_voice = f"{text}-{voice}"
        filename = text_and_voice
        if len(filename) > 200:
            filename = uuid.uuid4().hex
        # Save it so it can later be read and played
        await self.save_to_wav(audio_content, filename, sample_width=2, channels=1, sample_rate=8000)
        self.cache[text_and_voice] = filename
        return filename

    async def close(self):
        """
        Close the TTSEngine and wait for all cache tasks to finish
        """
        logger.debug("TTSEngine.close")
        async with self._cache_lock:
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*self.cache_tasks)
            self.cache_tasks = []
