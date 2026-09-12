import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from asteramisk.exceptions import InputTimeoutException
from asteramisk.internal.transcriber import TranscribeEngine
from asteramisk.ui.voice_ui import VoiceUI


class VoicePromptTimeoutTests(unittest.IsolatedAsyncioTestCase):
    def make_ui(self):
        ui = object.__new__(VoiceUI)
        ui.audconn = AsyncMock()
        ui.transcribe_engine = AsyncMock()
        ui._done_speaking = AsyncMock()
        return ui

    async def test_prompt_passes_configured_speech_start_timeout(self):
        ui = self.make_ui()
        ui.done_speaking = AsyncMock()
        ui.say = AsyncMock()
        ui._transcribe_with_speech_timeout = AsyncMock(return_value="hello")

        async def wait_for_back_or(awaitable):
            return await awaitable

        ui._wait_for_back_or = wait_for_back_or

        transcription = await ui.prompt("Say something")

        self.assertEqual(transcription, "hello")
        ui.done_speaking.assert_awaited_once()
        ui._transcribe_with_speech_timeout.assert_awaited_once_with([], 10.0)

    async def test_transcript_activity_triggers_barge_in(self):
        ui = self.make_ui()
        ui.stop_speaking = AsyncMock()

        async def transcribe(*args, speech_started, **kwargs):
            speech_started.set()
            await asyncio.sleep(0)
            return "hello"

        ui.transcribe_engine.transcribe_from_stream.side_effect = transcribe

        transcription = await ui._transcribe_with_speech_timeout([], 10.0)

        self.assertEqual(transcription, "hello")
        ui.stop_speaking.assert_awaited_once()

    async def test_transcriber_enables_google_speech_start_timeout(self):
        engine = object.__new__(TranscribeEngine)
        engine.is_transcribing = True
        stream = type("Stream", (), {"connected": True})()
        requests = engine._transcribe_request_generator(
            stream,
            speech_start_timeout=8,
        )

        request = await requests.__anext__()
        streaming_config = request.streaming_config
        self.assertTrue(streaming_config.enable_voice_activity_events)
        self.assertEqual(
            streaming_config.voice_activity_timeout.speech_start_timeout.seconds,
            8,
        )
        await requests.aclose()

    async def test_prompt_raises_after_three_silent_attempts(self):
        ui = self.make_ui()
        ui.done_speaking = AsyncMock()
        ui.say = AsyncMock()
        ui._transcribe_with_speech_timeout = AsyncMock(return_value="")

        async def wait_for_back_or(awaitable):
            return await awaitable

        ui._wait_for_back_or = wait_for_back_or

        with patch("asteramisk.ui.voice_ui.config.MAX_NO_INPUT_ATTEMPTS", 3):
            with self.assertRaises(InputTimeoutException):
                await ui.prompt("What would you like?")

        self.assertEqual(
            [call.args[0] for call in ui.say.await_args_list],
            [
                "What would you like?",
                "I didn't hear a response. Please try again.",
                "What would you like?",
                "I didn't hear a response. Please try again.",
                "What would you like?",
            ],
        )


if __name__ == "__main__":
    unittest.main()
