import asyncio
import unittest
from unittest.mock import AsyncMock

from asteramisk.ui.voice_ui import MAX_PAUSE_SECONDS, VoiceUI, _Silence


class VoiceSleepTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ui = object.__new__(VoiceUI)
        self.ui.is_active = True
        self.ui.text_out_queue = asyncio.Queue()
        self.ui._ensure_answered = AsyncMock()
        self.ui._check_go_back = AsyncMock()

        async def wait_for_back_or(awaitable):
            return await awaitable

        self.ui._wait_for_back_or = wait_for_back_or

    async def test_sleep_queues_silence_without_waiting_for_playback(self):
        await self.ui.sleep(1.25)

        queued = await self.ui.text_out_queue.get()
        self.assertEqual(queued, _Silence(1.25))
        self.ui._ensure_answered.assert_awaited_once()
        self.ui._check_go_back.assert_awaited_once()

    async def test_sleep_rejects_invalid_duration(self):
        for duration in (-1, float("inf"), "1", MAX_PAUSE_SECONDS + 1):
            with self.assertRaises(ValueError):
                await self.ui.sleep(duration)

    async def test_sleep_allows_one_hour(self):
        await self.ui.sleep(MAX_PAUSE_SECONDS)

        queued = await self.ui.text_out_queue.get()
        self.assertEqual(queued, _Silence(float(MAX_PAUSE_SECONDS)))


if __name__ == "__main__":
    unittest.main()
