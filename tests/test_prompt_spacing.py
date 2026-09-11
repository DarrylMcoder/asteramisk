import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from asteramisk.ui.text_ui import TextUI
from asteramisk.ui.ui import UI
from asteramisk.ui.voice_ui import VoiceUI


class PromptUI(UI):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []
        self._menu_navigation_state = SimpleNamespace(callback_depth=0)

    @property
    def ui_type(self):
        return self.UIType.TEXT

    async def prompt(self, text):
        self.prompts.append(text)
        return next(self.responses)


class PromptSpacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_menu_retry_has_one_boundary_space(self):
        ui = PromptUI(["invalid", "1"])
        callback = AsyncMock()

        await ui.menu("  Choose an option.  ", callbacks={"1": callback})

        self.assertEqual(
            ui.prompts,
            [
                "Choose an option.",
                "invalid is not a valid option, please try again. Choose an option.",
            ],
        )

    async def test_select_retry_has_one_boundary_space(self):
        ui = PromptUI(["invalid", "1"])

        await ui.select("  Choose an option.  ", options={"1": "first"})

        self.assertEqual(
            ui.prompts[-1],
            "invalid is not a valid option, please try again. Choose an option.",
        )

    async def test_voice_yes_no_suffix_has_one_boundary_space(self):
        ui = object.__new__(VoiceUI)
        ui.gather = AsyncMock(return_value="1")

        self.assertTrue(await ui.ask_yes_no("  Continue?  "))
        ui.gather.assert_awaited_once_with(
            "Continue? Press 1 for yes or 2 for no", 1
        )

    async def test_text_yes_no_suffix_has_one_boundary_space(self):
        ui = object.__new__(TextUI)
        ui.prompt = AsyncMock(return_value="yes")

        self.assertTrue(await ui.ask_yes_no("  Continue?  "))
        ui.prompt.assert_awaited_once_with("Continue? (yes/no)")


if __name__ == "__main__":
    unittest.main()
