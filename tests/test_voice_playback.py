import unittest
from unittest.mock import AsyncMock

from aiohttp.web_exceptions import HTTPNotFound

from asteramisk.ui.voice_ui import VoiceUI


class VoicePlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_controls_skip_fifteen_seconds_and_are_removed_after_playback(self):
        await self.check_playback(15000, skip_seconds=15)

    async def test_default_skip_remains_three_seconds(self):
        await self.check_playback(3000)

    async def test_invalid_interval_fails_before_playback(self):
        ui = object.__new__(VoiceUI)
        for interval in (0, -1, True, "15", float("nan"), float("inf")):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                await ui.control_say("Article text", skip_seconds=interval)

    async def test_text_ui_accepts_interval_without_playback(self):
        from asteramisk.ui.text_ui import TextUI
        ui = object.__new__(TextUI)
        ui.say = AsyncMock()
        await ui.control_say("Article text", skip_seconds=15)
        ui.say.assert_awaited_once_with("Article text")

    async def check_playback(self, expected_ms, **kwargs):
        ui = object.__new__(VoiceUI)
        ui.voice = "test"
        ui.tts_engine = AsyncMock()
        ui.tts_engine.tts_to_file.return_value = "test-audio"
        ui.done_speaking = AsyncMock()
        ui.channel = AsyncMock()
        ui.dtmf_callbacks = {}
        playback = ui.channel.play.return_value

        async def wait_for_back_or(awaitable):
            return await awaitable

        async def finish_playback():
            await ui.dtmf_callbacks["4"]()
            await ui.dtmf_callbacks["6"]()
            await ui.dtmf_callbacks["5"]()
            await ui.dtmf_callbacks["5"]()
            raise HTTPNotFound()

        ui._wait_for_back_or = wait_for_back_or
        playback.get.side_effect = finish_playback
        await ui.control_say("Article text", **kwargs)

        ui.channel.play.assert_awaited_once_with(media="sound:test-audio", skipms=expected_ms)
        self.assertEqual(
            [call.kwargs["operation"] for call in playback.control.await_args_list],
            ["reverse", "forward", "pause", "unpause"],
        )
        self.assertEqual(ui.dtmf_callbacks, {})
