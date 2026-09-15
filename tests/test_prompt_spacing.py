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
                "That wasn't one of the choices. Please try again. Choose an option.",
            ],
        )

    async def test_select_retry_has_one_boundary_space(self):
        ui = PromptUI(["invalid", "1"])

        await ui.select("  Choose an option.  ", options={"1": "first"})

        self.assertEqual(
            ui.prompts[-1],
            "That wasn't one of the choices. Please try again. Choose an option.",
        )

    async def test_voice_yes_no_suffix_has_one_boundary_space(self):
        ui = object.__new__(VoiceUI)
        ui.gather = AsyncMock(return_value="1")

        self.assertTrue(await ui.ask_yes_no("  Continue?  "))
        ui.gather.assert_awaited_once_with(
            "Continue? Press 1 for yes or 2 for no", 1
        )

    async def test_voice_yes_no_uses_case_specific_instruction(self):
        ui = object.__new__(VoiceUI)
        ui.gather = AsyncMock(return_value="1")

        self.assertTrue(
            await ui.ask_yes_no(
                "  Would you like me to read the phone number?  ",
                voice_instruction="  Press 1 to hear it, or 2 to go back.  ",
                text_instruction="Answer yes or no.",
            )
        )
        ui.gather.assert_awaited_once_with(
            "Would you like me to read the phone number? Press 1 to hear it, or 2 to go back.",
            1,
        )

    async def test_voice_yes_no_replays_custom_instruction_after_no_input(self):
        ui = object.__new__(VoiceUI)
        ui.gather = AsyncMock(side_effect=["", "1"])
        ui.say = AsyncMock()

        self.assertTrue(
            await ui.ask_yes_no(
                "Continue?",
                voice_instruction="Press 1 to continue, or 2 to cancel.",
            )
        )
        self.assertEqual(
            [call.args[0] for call in ui.gather.await_args_list],
            [
                "Continue? Press 1 to continue, or 2 to cancel.",
                "Continue? Press 1 to continue, or 2 to cancel.",
            ],
        )
        ui.say.assert_awaited_once_with(
            "I didn't receive a selection. Please try again."
        )

    async def test_text_yes_no_suffix_has_one_boundary_space(self):
        ui = object.__new__(TextUI)
        ui.prompt = AsyncMock(return_value="yes")

        self.assertTrue(await ui.ask_yes_no("  Continue?  "))
        ui.prompt.assert_awaited_once_with("Continue? (yes/no)")

    async def test_text_yes_no_ignores_voice_instruction(self):
        ui = object.__new__(TextUI)
        ui.prompt = AsyncMock(return_value="yes")

        self.assertTrue(
            await ui.ask_yes_no(
                "Continue?",
                voice_instruction="Press 1 to continue, or 2 to cancel.",
            )
        )
        ui.prompt.assert_awaited_once_with("Continue? (yes/no)")

    async def test_text_yes_no_replays_custom_instruction_after_invalid_input(self):
        ui = object.__new__(TextUI)
        ui.prompt = AsyncMock(side_effect=["maybe", "no"])
        ui.say = AsyncMock()

        self.assertFalse(await ui.ask_yes_no(
            "  Your name is Bob.  ",
            voice_instruction="If correct, press 1. Otherwise, press 2.",
            text_instruction="  Is that correct? (yes/no)  ",
        ))
        self.assertEqual(
            [call.args[0] for call in ui.prompt.await_args_list],
            ["Your name is Bob. Is that correct? (yes/no)"] * 2,
        )


if __name__ == "__main__":
    unittest.main()
