import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from asteramisk.exceptions import GoBackException
from asteramisk.ui.text_ui import TextUI


class TextNavigationTests(unittest.IsolatedAsyncioTestCase):
    def make_ui(self, depth):
        ui = object.__new__(TextUI)
        ui.is_active = True
        ui._closed = False
        ui._closed_event = asyncio.Event()
        ui._incoming_queue = asyncio.Queue()
        ui._menu_navigation_state = SimpleNamespace(callback_depth=depth)
        return ui

    async def test_back_is_recognized_by_shared_input(self):
        for message in ('*', 'back', ' BACK '):
            ui = self.make_ui(1)
            ui._incoming_queue.put_nowait(message)
            with patch('asteramisk.ui.text_ui.config.GO_BACK_ON_STAR', True):
                with self.assertRaises(GoBackException):
                    await ui._receive_message()

    async def test_back_is_ignored_outside_menu_callback(self):
        ui = self.make_ui(0)
        for message in ('*', 'back', 'Elmira'):
            ui._incoming_queue.put_nowait(message)
        with patch('asteramisk.ui.text_ui.config.GO_BACK_ON_STAR', True):
            self.assertEqual(await ui._receive_message(), 'Elmira')

    async def test_disabled_navigation_preserves_message(self):
        ui = self.make_ui(1)
        ui._incoming_queue.put_nowait('back')
        with patch('asteramisk.ui.text_ui.config.GO_BACK_ON_STAR', False):
            self.assertEqual(await ui._receive_message(), 'back')
