import asyncio
from panoramisk.manager import Manager

from asteramisk.config import config
from asteramisk.exceptions import AGIException

import logging
logger = logging.getLogger(__name__)

class AsteriskGatewayInterface:
    def __init__(self):
        self._manager = Manager(
            host=config.ASTERISK_HOST,
            port=config.ASTERISK_AMI_PORT,
            username=config.ASTERISK_AMI_USER,
            secret=config.ASTERISK_AMI_PASS,
            ssl=False
        )

    def __del__(self):
        self._manager.close()

    @property
    def channel(self):
        raise NotImplementedError

    @classmethod
    async def create(cls, *args, **kwargs):
        """ Creates a new instance of the class and connects it to asterisk. """
        instance = cls(*args, **kwargs)
        await instance.connect()
        return instance

    async def connect(self):
        await self._manager.connect()

    async def close(self):
        self._manager.close()

    async def send_command(self, command):
        """ Send an AGI command to asterisk. """
        raise NotImplementedError

    async def get_variable(self, name: str) -> str:
        """ Get Asterisk channel variable. Sends GET VARIABLE AGI command """
        response = await self.send_command(f"GET VARIABLE {name}")
        if 'error' in response and 'msg' in response:
            raise AGIException(response['msg'])
        logger.info(f"Got variable {name}: {response['result'][1]}")
        return response['result'][1]

    async def set_variable(self, name: str, value: str) -> str:
        """ Set Asterisk channel variable. Sends SET VARIABLE AGI command """
        logger.info(f"Setting variable {name} to {value}")
        return await self.send_command(f"SET VARIABLE {name} {value}")

    async def wait_for_event(self, event: str, timeout: int = None, this_channel_only: bool = True):
        """
        Wait for an event.
        :param event: Event to wait for
        :param timeout: Timeout in seconds
        :param this_channel_only: Only wait for the specified event on this channel
        :return: Event
        """
        result_event = asyncio.Event()
        result = None

        def channel_event_callback(manager, event):
            logger.info(f"Channel event: {event}")
            nonlocal result
            if (this_channel_only and 'Channel' in event and event['Channel'] == self.channel) or not this_channel_only:
                result = event
                result_event.set()

        self.manager.register_event(event, channel_event_callback)

        logger.info(f"Waiting for event {event}")
        if timeout:
            await asyncio.wait_for(result_event.wait(), timeout)
        else:
            await result_event.wait()
        return result

    async def register_event_handler(self, event: str, callback, this_channel_only: bool = True):
        """
        Register a callback for an event on the channel.
        Runs the callback as an async task
        :param event: Event to listen for
        :param callback: Callback coroutine
        :param this_channel_only: Only listen for the specified event on this channel
        :return: None
        """
        def channel_event_callback(manager, event):
            if (this_channel_only and 'Channel' in event and event['Channel'] == self.channel) or not this_channel_only:
                asyncio.create_task(callback(event))

        self.manager.register_event(event, channel_event_callback)
        logger.info(f"Registered event handler for {event}")
        return

