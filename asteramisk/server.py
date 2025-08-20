import os
import uuid
import asyncio
import contextlib
import panoramisk.fast_agi
import panoramisk.actions
import panoramisk.manager

import asteramisk.ui
from asteramisk.config import config
from asteramisk.internal.async_class import AsyncClass
from asteramisk.internal.message_broker import MessageBroker
from asteramisk.internal.audiosocket import AsyncAudiosocket

import logging
logger = logging.getLogger(__name__)

class Server(AsyncClass):
    async def __create__(self, host=config.ASTERAMISK_HOST, bindaddr=config.AGI_SERVER_BINDADDR, port=config.AGI_SERVER_PORT):
        self.host = host
        self.bindaddr = bindaddr
        self.port = port
        if not self.host:
            raise ValueError("Must provide a host. Either set the ASTERAMISK_HOST environment variable, set config.ASTERAMISK_HOST or pass it to the constructor")
        if not self.bindaddr:
            raise ValueError("Must provide a bind address. Either set the AGI_SERVER_BINDADDR environment variable, set config.AGI_SERVER_BINDADDR or pass it to the constructor")
        if not self.port:
            raise ValueError("Must provide a port. Either set the AGI_SERVER_PORT environment variable, set config.AGI_SERVER_PORT or pass it to the constructor")

        self.handlers = {}
        self.audiosocket_server = await AsyncAudiosocket.create((config.AUDIOSOCKET_BINDADDR, int(config.AUDIOSOCKET_PORT)))

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
            "ApplicationData": f"agi://{self.host}:{self.port}/{extension_type}_handler",
            "Replace": "yes"
        })

        manager = panoramisk.manager.Manager(
                host=config.ASTERISK_HOST,
                port=config.ASTERISK_AMI_PORT,
                username=config.ASTERISK_AMI_USER,
                secret=config.ASTERISK_AMI_PASS,
                ssl=False
            )

        await manager.connect()
        await manager.send_action(registration_action)
        manager.close()

    async def serve_forever(self):
        # Error if not running as root
        if not os.geteuid() == 0:
            raise Exception("Must be run as root")

        fa_app = panoramisk.fast_agi.Application()
        fa_app.add_route("call_handler", self._call_request_handler)
        fa_app.add_route("text_handler", self._message_request_handler)
        server = await asyncio.start_server(fa_app.handler, self.bindaddr, self.port)
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

        logger.info("Answering call")
        await request.send_command('ANSWER')
        logger.info("Answered call")

        audio_socket_id = str(uuid.uuid4())
        # Very hackish way to swallow the ValueError that panoramisk throws
        # It still works though
        async def start_audio_socket():
            with contextlib.suppress(ValueError):
                await request.send_command(f"EXEC AudioSocket {audio_socket_id},{config.ASTERAMISK_HOST}:{config.AUDIOSOCKET_PORT}")
        # Put this in a task because it won't return until the connection is closed
        asyncio.create_task(start_audio_socket())
        audsock_conn = await self.audiosocket_server.accept(audio_socket_id)

        ui = await asteramisk.ui.VoiceUI.create(audsock_conn)

        call_handler, _ = self.handlers[extension]

        logger.info(f"Calling handler for extension {extension}")
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

        broker = await MessageBroker.create(config.SYSTEM_PHONE_NUMBER)
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
