import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from agents.realtime import RealtimeAgent
from asteramisk.exceptions import GoBackException, HangupException
from asteramisk.ui.voice_ui import VoiceUI
from asteramisk.ui.text_ui import TextUI


class RealtimeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setup_ui(self, voice, *, idle=False):
        ui = object.__new__(VoiceUI if voice else TextUI)
        ui.is_active = True
        ui.done_speaking = AsyncMock()
        ui._check_go_back = AsyncMock()
        ui._go_back_event = asyncio.Event()
        self.input_stopped = asyncio.Event()
        self.session_closed = False

        async def read():
            try:
                await asyncio.Future()
            finally:
                self.input_stopped.set()

        ui._receive_message = read
        ui.audconn = SimpleNamespace(read=read)

        async def events():
            if not idle:
                yield SimpleNamespace(type="test")
            await asyncio.Future()

        stream = events()
        session = SimpleNamespace(send_message=AsyncMock())

        class Session:
            def __aiter__(self):
                return stream
            send_message = session.send_message

        @asynccontextmanager
        async def running():
            try:
                yield Session()
            finally:
                await stream.aclose()
                self.session_closed = True

        runner = Mock()
        runner.run = AsyncMock(side_effect=lambda **kwargs: running())
        module = "voice_ui" if voice else "text_ui"
        return ui, patch(f"asteramisk.ui.{module}.RealtimeRunner", return_value=runner)

    async def test_early_exit_closes_session_and_input_on_both_interfaces(self):
        for voice in (True, False):
            with self.subTest(voice=voice):
                ui, patched = self.setup_ui(voice)
                with patched:
                    async with ui.run_realtime_agent(RealtimeAgent(name="test")) as events:
                        async for _ in events:
                            await asyncio.sleep(0)
                            break
                self.assertTrue(self.session_closed)
                self.assertTrue(self.input_stopped.is_set())
                self.assertEqual(ui.done_speaking.await_count, int(voice))

    async def test_exception_in_caller_closes_session(self):
        for voice in (True, False):
            ui, patched = self.setup_ui(voice)
            with patched, self.assertRaisesRegex(RuntimeError, "caller error"):
                async with ui.run_realtime_agent(RealtimeAgent(name="test")) as events:
                    async for _ in events:
                        raise RuntimeError("caller error")
            self.assertTrue(self.session_closed)

    async def test_text_back_and_hangup_interrupt_idle_session(self):
        for value in ("back", "*", HangupException("closed")):
            ui, patched = self.setup_ui(False, idle=True)
            ui._closed = False
            ui._closed_event = asyncio.Event()
            ui._incoming_queue = asyncio.Queue()
            ui._menu_navigation_state = SimpleNamespace(callback_depth=1)
            if isinstance(value, Exception):
                ui._closed_event.set()
            else:
                ui._incoming_queue.put_nowait(value)
            ui._receive_message = TextUI._receive_message.__get__(ui)
            expected = HangupException if isinstance(value, Exception) else GoBackException
            with patched, patch('asteramisk.ui.text_ui.config.GO_BACK_ON_STAR', True), self.assertRaises(expected):
                async with ui.run_realtime_agent(RealtimeAgent(name="test")) as events:
                    await asyncio.wait_for(anext(events), 1)
            self.assertTrue(self.session_closed)

    async def test_voice_star_interrupts_idle_session(self):
        ui, patched = self.setup_ui(True, idle=True)

        async def check_back():
            if ui._go_back_event.is_set():
                raise GoBackException()

        ui._check_go_back = check_back
        with patched, self.assertRaises(GoBackException):
            async with ui.run_realtime_agent(RealtimeAgent(name="test")) as events:
                task = asyncio.create_task(anext(events))
                await asyncio.sleep(0.02)
                ui._go_back_event.set()
                await asyncio.wait_for(task, 1)
        self.assertTrue(self.session_closed)

    async def test_queued_speech_failure_prevents_agent_start(self):
        ui, patched = self.setup_ui(True)
        ui.done_speaking.side_effect = RuntimeError("queued speech failed")
        with patched, self.assertRaisesRegex(RuntimeError, "queued speech failed"):
            async with ui.run_realtime_agent(RealtimeAgent(name="test")):
                self.fail("Should not enter agent context")

    async def test_cancellation_closes_idle_session_on_both_interfaces(self):
        for voice in (True, False):
            ui, patched = self.setup_ui(voice, idle=True)

            async def consume():
                async with ui.run_realtime_agent(RealtimeAgent(name="test")) as events:
                    async for _ in events:
                        pass

            with patched:
                task = asyncio.create_task(consume())
                await asyncio.sleep(0.02)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertTrue(self.session_closed)
            self.assertTrue(self.input_stopped.is_set())
