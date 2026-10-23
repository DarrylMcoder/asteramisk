import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asteramisk.exceptions import InputTimeoutException
from asteramisk.server import Server


class CallHandlerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def run_handler(self, handler, *, active=True):
        server = Server(async_creation=True)
        server.call_semaphore = asyncio.Semaphore(1)
        server.handlers = {"1234": (handler, None)}
        channel = SimpleNamespace(
            id="channel-1",
            json={"name": "test-channel"},
            getChannelVar=AsyncMock(return_value={"value": "1234"}),
        )
        ui = SimpleNamespace(
            is_active=active,
            say=AsyncMock(),
            hangup=AsyncMock(),
        )
        with patch("asteramisk.server.VoiceUI.create", AsyncMock(return_value=ui)):
            await server._call_request_handler(channel)
        return ui

    async def test_normal_return_says_goodbye_and_hangs_up(self):
        ui = await self.run_handler(AsyncMock())
        ui.say.assert_awaited_once_with("Thank you for calling. Goodbye.")
        ui.hangup.assert_awaited_once_with()

    async def test_return_after_custom_hangup_does_not_add_goodbye(self):
        async def handler(ui):
            await ui.say("No response received. Goodbye.")
            await ui.hangup()
            ui.is_active = False

        ui = await self.run_handler(handler)
        ui.say.assert_awaited_once_with("No response received. Goodbye.")
        ui.hangup.assert_awaited_once_with()

    async def test_return_after_caller_hangup_does_not_add_goodbye(self):
        ui = await self.run_handler(AsyncMock(), active=False)
        ui.say.assert_not_awaited()
        ui.hangup.assert_not_awaited()

    async def test_propagated_no_input_uses_default_message_and_hangs_up(self):
        handler = AsyncMock(side_effect=InputTimeoutException("no input"))
        ui = await self.run_handler(handler)
        ui.say.assert_awaited_once_with(
            "I still haven't received a response, so I'll end the call now. Goodbye."
        )
        ui.hangup.assert_awaited_once_with()
