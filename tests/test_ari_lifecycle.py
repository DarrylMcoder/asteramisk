import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.web_exceptions import HTTPNotFound

from asteramisk.internal.ari_client import AriClient
from asteramisk.server import Server


class _FakeApplications:
    def __init__(self, client):
        self.client = client

    async def get(self, applicationName):
        if not self.client.registered:
            raise HTTPNotFound()
        return {"name": applicationName}


class _FakeAriClient:
    def __init__(self):
        self.applications = _FakeApplications(self)
        self.registered = False
        self.run_calls = []
        self.closed = False
        self._closed = asyncio.Event()

    async def run(self, apps):
        self.run_calls.append(apps)
        self.registered = True
        await self._closed.wait()

    async def close(self):
        self.closed = True
        self._closed.set()


class AriClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        AriClient._instance = None
        AriClient._application_name = "test-app"
        AriClient._run_task = None
        AriClient._lock = None
        AriClient._users = 0

    async def test_acquirers_share_one_application_websocket(self):
        client = _FakeAriClient()
        connect = AsyncMock(return_value=client)
        with patch("asteramisk.internal.ari_client.aioari.connect", connect):
            acquired = await asyncio.gather(AriClient.acquire(), AriClient.acquire())
            self.assertEqual(acquired, [client, client])
            connect.assert_awaited_once()
            self.assertEqual(client.run_calls, [["test-app"]])

            await AriClient.release()
            self.assertFalse(client.closed)

            await AriClient.release()
            self.assertTrue(client.closed)

    async def test_running_application_cannot_be_renamed(self):
        client = _FakeAriClient()
        with patch("asteramisk.internal.ari_client.aioari.connect", AsyncMock(return_value=client)):
            await AriClient.acquire()
            with self.assertRaisesRegex(RuntimeError, "already running as 'test-app'"):
                AriClient.configure_application("other-app")
            await AriClient.release()

    async def test_configured_application_is_used_when_started_later(self):
        client = _FakeAriClient()
        AriClient.configure_application("custom-app")
        with patch("asteramisk.internal.ari_client.aioari.connect", AsyncMock(return_value=client)):
            await AriClient.acquire()
            self.assertEqual(client.run_calls, [["custom-app"]])
            await AriClient.release()


class ServerStasisRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_dialplan_requests_reach_main_handler(self):
        server = Server(async_creation=True)
        server.stasis_app = "test-app"
        server.handler_tasks = {}
        server._main_handler = AsyncMock()
        channel = SimpleNamespace(id="channel-1", json={"name": "test-channel"})
        objects = {"channel": channel}

        await server._ari_stasis_start_handler(
            objects,
            {"application": "test-app", "args": []},
        )
        self.assertEqual(server.handler_tasks, {})

        await server._ari_stasis_start_handler(
            objects,
            {"application": "test-app", "args": ["call"]},
        )
        await server.handler_tasks[channel.id]
        server._main_handler.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
