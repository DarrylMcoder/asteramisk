import unittest
from unittest.mock import patch

from aiohttp.web_exceptions import HTTPNotFound

from asteramisk.communicator import Communicator
from asteramisk.exceptions import CallFailedException


class _FakeChannel:
    def __init__(self):
        self.json = {
            "id": "outbound-channel",
            "name": "PJSIP/test-00000001",
            "state": "Ringing",
        }
        self.event_handlers = {}

    def on_event(self, event_name, handler):
        self.event_handlers[event_name] = handler


class _FakeChannels:
    def __init__(self, destroy_event=None):
        self.channel = _FakeChannel()
        self.destroy_event = destroy_event

    async def originate(self, **_kwargs):
        return self.channel

    async def get(self, channelId):
        assert channelId == self.channel.json["id"]
        if self.destroy_event is not None:
            self.channel.event_handlers["ChannelDestroyed"](
                self.channel,
                self.destroy_event,
            )
        raise HTTPNotFound()


class _FakeAriClient:
    def __init__(self, destroy_event=None):
        self.channels = _FakeChannels(destroy_event)


class MakeCallFailureTests(unittest.IsolatedAsyncioTestCase):
    def _communicator(self, destroy_event=None):
        communicator = Communicator(async_creation=True)
        communicator._ari_client = _FakeAriClient(destroy_event)
        communicator._callerid_number = "5195551234"
        communicator._callerid_name = "Test Caller"
        return communicator

    async def test_destroyed_channel_includes_hangup_cause(self):
        communicator = self._communicator({
            "cause": 17,
            "cause_txt": "User busy",
        })

        with patch(
            "asteramisk.communicator.AriClient.application_name",
            return_value="test-app",
        ):
            with self.assertRaises(CallFailedException) as raised:
                await communicator.make_call("5195559876")

        self.assertEqual(raised.exception.cause, 17)
        self.assertEqual(raised.exception.cause_txt, "User busy")
        self.assertEqual(str(raised.exception), "Call failed: User busy")

    async def test_missing_destroy_event_still_fails_without_hanging(self):
        communicator = self._communicator()

        with patch(
            "asteramisk.communicator.AriClient.application_name",
            return_value="test-app",
        ):
            with self.assertRaises(CallFailedException) as raised:
                await communicator.make_call("5195559876")

        self.assertIsNone(raised.exception.cause)
        self.assertIsNone(raised.exception.cause_txt)
        self.assertEqual(
            str(raised.exception),
            "Call failed. Channel destroyed before being ready.",
        )


if __name__ == "__main__":
    unittest.main()
