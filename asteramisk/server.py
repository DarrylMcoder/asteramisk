import os
import asyncio
import panoramisk.fast_agi
import panoramisk.actions
import panoramisk.manager

import asteramisk.ui
from asteramisk.config import config
from asteramisk.internal import MessageBroker

import logging
logger = logging.getLogger(__name__)

class Server:
    def __init__(self, host=config.AGI_SERVER_HOST, port=config.AGI_SERVER_PORT):
        self.host = host
        self.port = port

        self.handlers = {}

    async def register_extension(self, extension, call_handler=None, message_handler=None):
        """
        Registers a phone number with asterisk.

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
        registration_action = panoramisk.actions.Action({
            "Action": "DialPlanExtensionAdd",
            "Context": f"{config.ASTERISK_INCOMING_CALL_CONTEXT if extension_type == 'call' else config.ASTERISK_INCOMING_TEXT_CONTEXT}",
            "Extension": extension,
            "Priority": 1,
            "Application": "AGI",
            "ApplicationData": f"agi://{config.AGI_SERVER_HOST}:{config.AGI_SERVER_PORT}/{extension_type}_handler",
            "Replace": "yes"
        })

        manager = panoramisk.manager.Manager(
                host=config.ASTERISK_HOST,
                port=config.ASTERISK_AMI_PORT,
                user=config.ASTERISK_AMI_USER,
                password=config.ASTERISK_AMI_PASS,
                ssl=False
            )

        await manager.send_action(registration_action)

    async def serve_forever(self):
        # Error if not running as root
        if not os.geteuid() == 0:
            raise Exception("Must be run as root")

        fa_app = panoramisk.fast_agi.Application()
        fa_app.add_route("call_handler", self._call_request_handler)
        fa_app.add_route("text_handler", self._message_request_handler)
        server = await asyncio.start_server(fa_app.handler, self.host, self.port)
        logger.info('Asteramisk server started on {}'.format(server.sockets[0].getsockname()))

        try:
            await server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.close()

    async def _call_request_handler(self, request: panoramisk.fast_agi.Request):
        """
        Called when an AGI request is received.
        This is registered as the callback for call requests.
        Once per call.
        """
        channel = request.headers['agi_channel']
        extension = request.headers['agi_extension']

        ui = asteramisk.ui.VoiceUI(channel)
        call_handler, _ = self.handlers[extension]

        await call_handler(ui)

    async def _message_request_handler(self, request: panoramisk.fast_agi.Request):
        """
        Called when an AGI request is received.
        This is registered as the callback for message requests.
        Once per message.
        """
        # TODO: Get phone number and message properly
        phone_number = request.headers['agi_arg_1']
        message = request.headers['agi_arg_2']
        extension = request.headers['agi_extension']

        broker = MessageBroker()
        if broker.has_conversation(phone_number):
            # Existing conversation, use the existing UI and simply pass the message to it via the broker
            await broker.message_received(phone_number, message)
        else:
            # New conversation
            ui = asteramisk.ui.TextUI(phone_number)
            _, message_handler = self.handlers[extension]
            await message_handler(ui)

    async def call_handler(self, ui: asteramisk.ui.VoiceUI):
        """
        Called when a call is received.
        Override this to handle the call.
        :param ui: asteramisk.ui.VoiceUI A UI that can be used to control the call.
        """
        raise NotImplementedError

    async def message_handler(self, ui: asteramisk.ui.VoiceUI):
        """
        Called when a new messaging conversation is started.
        Override this to handle the message.
        :param ui: asteramisk.ui.TextUI A UI that can be used to control the conversation.
        """
        raise NotImplementedError
