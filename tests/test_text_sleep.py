import unittest
from unittest.mock import Mock, patch

from asteramisk.ui.text_ui import TextUI


class TextSleepTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ui = object.__new__(TextUI)
        self.ui._ensure_active = Mock()

    async def test_sleep_waits_for_requested_duration(self):
        with patch("asteramisk.ui.text_ui.asyncio.sleep") as sleep:
            await self.ui.sleep(1.25)

        self.ui._ensure_active.assert_called_once()
        sleep.assert_awaited_once_with(1.25)

    async def test_sleep_rejects_invalid_duration(self):
        for duration in (-1, float("inf"), "1"):
            with self.assertRaises(ValueError):
                await self.ui.sleep(duration)


if __name__ == "__main__":
    unittest.main()
