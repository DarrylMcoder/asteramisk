from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from asteramisk.exceptions import GoBackException
from asteramisk.ui.ui import UI


class MenuUI(UI):
    def __init__(self, inputs, depth=0):
        self.inputs = iter(inputs)
        self.prompt_count = 0
        self._menu_navigation_state = SimpleNamespace(callback_depth=depth)
        self._event_listeners = []

    @property
    def ui_type(self):
        return self.UIType.TEXT

    async def prompt(self, text):
        self.prompt_count += 1
        value = next(self.inputs)
        if isinstance(value, Exception):
            raise value
        return value


class MenuNavigationTests(IsolatedAsyncioTestCase):
    async def test_pending_back_during_root_replay_stays_at_root(self):
        ui = MenuUI(["1", GoBackException(), "1"])
        calls = 0

        async def callback():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise GoBackException()
            return "selected"

        self.assertEqual(await ui.menu("Root", {"1": callback}), "selected")
        self.assertEqual(ui.prompt_count, 3)
        self.assertEqual(calls, 2)
        self.assertEqual(ui._menu_navigation_state.callback_depth, 0)

    async def test_back_from_submenu_propagates_to_parent(self):
        ui = MenuUI([GoBackException()], depth=1)
        with self.assertRaises(GoBackException):
            await ui.menu("Submenu", {"1": lambda: None})
        self.assertEqual(ui._menu_navigation_state.callback_depth, 1)

    async def test_repeated_root_back_events_do_not_recurse(self):
        ui = MenuUI([*[GoBackException() for _ in range(100)], "1"])

        async def callback():
            return "selected"

        self.assertEqual(await ui.menu("Root", {"1": callback}), "selected")
        self.assertEqual(ui.prompt_count, 101)
        self.assertEqual(ui._menu_navigation_state.callback_depth, 0)
