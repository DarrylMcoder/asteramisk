import os
import uuid
import aioari
import asyncio
import panoramisk.fast_agi
import panoramisk.actions
import panoramisk.manager

from asteramisk.config import config
from asteramisk.ui import VoiceUI, TextUI
from asteramisk.internal.message_broker import MessageBroker
from asteramisk.internal.async_class import AsyncClass
from asteramisk.internal.ari_client import AriClient
from asteramisk.internal.audiosocket import AudiosocketAsync

import logging
logger = logging.getLogger(__name__)

class Server(AsyncClass):
    """
    The main server class
    Create an instance of this class to receive calls and messages
    Example:
    .. code-block:: python

        from asteramisk import Server

        async def call_handler(ui: VoiceUI):
            await ui.say("Hello, world!")

        async def message_handler(ui: TextUI):
            await ui.say("Hello, world!")

        server = await Server.create()
        await server.register_extension("1234", call_handler=call_handler, message_handler=message_handler)
        await server.serve_forever()
    """
    async def __create__(self, stasis_app=None):
        self.host = config.AGI_SERVER_HOST
        self.bindaddr = config.AGI_SERVER_BINDADDR
        self.port = config.AGI_SERVER_PORT
        self.audiosocket: AudiosocketAsync = await AudiosocketAsync.create()
        self.ari: aioari.Client = await AriClient.create(
                ari_host=config.ASTERISK_HOST,
                ari_port=config.ASTERISK_ARI_PORT,
                ari_user=config.ASTERISK_ARI_USER,
                ari_pass=config.ASTERISK_ARI_PASS
            )
        self.handlers = {}
        self.stasis_app = stasis_app
        if not self.stasis_app:
            # Unique ID for Stasis application so that there are no conflicts with multiple instances
            self.stasis_app = uuid.uuid4().hex

    async def register_extension(self, extension, call_handler=None, message_handler=None):
        """
        Registers a phone number with asterisk.
        Is an async method

        :param extension: The phone number to register
        :param call_handler: The function to call when the phone number is called. Must be a coroutine. Will be passed an instance of asteramisk.ui.VoiceUI
        :param message_handler: The function to call when a message is sent to the phone number. Must be a coroutine. Will be passed an instance of asteramisk.ui.TextUI
        """
        if extension in self.handlers:
            raise Exception(f"Extension {extension} is already registered")

        if not call_handler:
            call_handler = self.call_handler
        if not message_handler:
            message_handler = self.message_handler

        if not asyncio.iscoroutinefunction(call_handler):
            raise Exception("call_handler must be a coroutine")
        if not asyncio.iscoroutinefunction(message_handler):
            raise Exception("message_handler must be a coroutine")

        self.handlers[extension] = (call_handler, message_handler)

        await self._register_extension(extension, 'call')
        await self._register_extension(extension, 'text')

    async def _register_extension(self, extension, extension_type):
        """
        Internally called to register an extension
        Not a public API function
        """
        manager = panoramisk.manager.Manager(
                host=config.ASTERISK_HOST,
                port=config.ASTERISK_AMI_PORT,
                username=config.ASTERISK_AMI_USER,
                secret=config.ASTERISK_AMI_PASS,
                ssl=False
            )
        await manager.connect()

        registration_action = panoramisk.actions.Action({
            "Action": "DialPlanExtensionAdd",
            "Context": f"{config.ASTERISK_INCOMING_CALL_CONTEXT if extension_type == 'call' else config.ASTERISK_INCOMING_TEXT_CONTEXT}",
            "Extension": extension,
            "Priority": 1,
            "Application": "Stasis",
            "ApplicationData": f"{self.stasis_app},{extension_type}",
            "Replace": "yes"
        })

        await manager.send_action(registration_action)
        manager.close()

    async def serve_forever(self):
        """
        Runs the server. Is an async method
        """
        # Error if not running as root
        if not os.geteuid() == 0:
            raise Exception("Must be run as root")
        self.ari.on_channel_event("StasisStart", self._ari_stasis_start_handler)
        try:
            await self.ari.run(
                apps=[
                    self.stasis_app,
                    "asteramisk"
                ]
            )
        finally:
            await self.audiosocket.close()
            await self.ari.close()

    async def close(self):
        """
        Close the server. Is an async method
        """
        await self.audiosocket.close()
        await self.ari.close()

    async def _ari_stasis_start_handler(self, objs, event):
        if event['application'] == self.stasis_app:
            asyncio.create_task(self._main_handler(objs, event))
        else:
            logger.debug(f"Application {event['application']} has no handler. Probably ok if the code that created it is also controlling it")

    async def _main_handler(self, objs, event):
        """
        Internally called when a call or message is received.
        This is registered as the callback for StasisStart events.
        Not a public API function
        """
        channel = objs['channel']
        extension_type = event['args'][0]
        if extension_type == 'call':
            await self._call_request_handler(channel)
        elif extension_type == 'text':
            await self._message_request_handler(channel)

    async def _call_request_handler(self, channel: aioari.model.Channel):
        """
        Internally called when a call is received.
        This is registered as the callback for call requests.
        Once per call.
        Not a public API function
        """
        ui = await VoiceUI.create(channel)
        extension = (await channel.getChannelVar(variable="EXTEN"))['value']
        call_handler, _ = self.handlers[extension]
        await call_handler(ui)

    async def _message_request_handler(self, channel: aioari.model.Channel):
        """
        Internally called when a message is received.
        This is registered as the callback for message requests.
        Once per message.
        Not a public API function
        """
        phone_number = (await channel.getChannelVar(variable="MESSAGE(from)"))['value']
        message = (await channel.getChannelVar(variable="MESSAGE(body)"))['value']
        extension = (await channel.getChannelVar(variable="EXTEN"))['value']

        broker = await MessageBroker.create(our_number=extension)
        if broker.has_conversation(phone_number):
            # Existing conversation, use the existing UI and simply pass the message to it via the broker
            await broker.message_received(phone_number, message)
        else:
            # New conversation
            ui = await TextUI.create(phone_number)
            _, message_handler = self.handlers[extension]
            await message_handler(ui)
