import asyncio
import unittest
from types import SimpleNamespace

from asteramisk.exceptions import GoBackException
from asteramisk.ui.ui import UI
from asteramisk.ui.voice_ui import VoiceUI


class MenuUI(UI):
    def __init__(self, inputs):
        self.inputs = iter(inputs)
        self.prompts = []
        self._menu_navigation_state = SimpleNamespace(callback_depth=0)
        self._event_listeners = []

    @property
    def ui_type(self):
        return self.UIType.TEXT

    async def prompt(self, text):
        self.prompts.append(text)
        value = next(self.inputs)
        if isinstance(value, Exception):
            raise value
        return value


class MenuNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_back_from_business_menu_replays_results(self):
        ui = MenuUI(["1", "1", GoBackException(), "done"])

        async def done():
            return "finished"

        async def business():
            await ui.menu("Business", {"1": done})

        async def results():
            return await ui.menu("Results", {"1": business, "done": done})

        self.assertEqual(await ui.menu("Main", {"1": results}), "finished")
        self.assertEqual(ui.prompts, ["Main", "Results", "Business", "Results"])
        self.assertEqual(ui._menu_navigation_state.callback_depth, 0)

    async def test_second_back_while_parent_replays_reaches_its_parent(self):
        ui = MenuUI(["1", "1", GoBackException(), GoBackException(), "done"])

        async def done():
            return "finished"

        async def business():
            await ui.menu("Business", {"1": done})

        async def results():
            return await ui.menu("Results", {"1": business})

        self.assertEqual(
            await ui.menu("Main", {"1": results, "done": done}), "finished"
        )
        self.assertEqual(
            ui.prompts, ["Main", "Results", "Business", "Results", "Main"]
        )
        self.assertEqual(ui._menu_navigation_state.callback_depth, 0)

    async def test_repeated_callback_back_does_not_recurse(self):
        attempts = 0
        ui = MenuUI(["1"] * 101)

        async def callback():
            nonlocal attempts
            attempts += 1
            if attempts <= 100:
                raise GoBackException()
            return "finished"

        self.assertEqual(await ui.menu("Main", {"1": callback}), "finished")
        self.assertEqual(attempts, 101)
        self.assertEqual(len(ui.prompts), 101)
        self.assertEqual(ui._menu_navigation_state.callback_depth, 0)


class VoiceBackNavigationTests(unittest.IsolatedAsyncioTestCase):
    def make_ui(self, depth):
        ui = object.__new__(VoiceUI)
        ui._menu_navigation_state = SimpleNamespace(callback_depth=depth)
        ui._go_back_event = asyncio.Event()
        ui._go_back_cleanup_done = asyncio.Event()
        return ui

    async def test_pending_back_is_discarded_after_return_to_root(self):
        ui = self.make_ui(depth=1)
        ui._go_back_event.set()
        check = asyncio.create_task(ui._check_go_back())
        await asyncio.sleep(0)
        ui._menu_navigation_state.callback_depth = 0
        ui._go_back_cleanup_done.set()

        await check
        self.assertFalse(ui._go_back_event.is_set())

    async def test_pending_back_in_submenu_still_raises(self):
        ui = self.make_ui(depth=1)
        ui._go_back_event.set()
        ui._go_back_cleanup_done.set()

        with self.assertRaises(GoBackException):
            await ui._check_go_back()
        self.assertFalse(ui._go_back_event.is_set())

    async def test_stale_back_does_not_cancel_root_operation(self):
        ui = self.make_ui(depth=0)
        ui._go_back_cleanup_done.set()

        async def send_stale_back():
            await asyncio.sleep(0)
            ui._go_back_event.set()

        sender = asyncio.create_task(send_stale_back())
        self.assertEqual(await ui._wait_for_back_or(asyncio.sleep(0.01, result="completed")), "completed")
        await sender
        self.assertFalse(ui._go_back_event.is_set())
