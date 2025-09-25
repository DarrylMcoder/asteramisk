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

def raise_not_configured(var):
    raise Exception(f"{var} is not configured. Please configure it by setting config.{var} or by setting the environment variable {var}")

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

        async def main():
            server: Server = await Server.create()
            await server.register_extension("1234", call_handler=call_handler, message_handler=message_handler)
            await server.serve_forever()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    async def __create__(self, stasis_app=None):
        # Raise an exception if required variables are not configured
        if not config.ASTERISK_HOST:
            raise_not_configured("ASTERISK_HOST")
        if not config.ASTERAMISK_HOST:
            raise_not_configured("ASTERAMISK_HOST")
        if not config.ASTERISK_AMI_PORT:
            raise_not_configured("ASTERISK_AMI_PORT")
        if not config.ASTERISK_AMI_USER:
            raise_not_configured("ASTERISK_AMI_USER")
        if not config.ASTERISK_AMI_PASS:
            raise_not_configured("ASTERISK_AMI_PASS")

        if not config.ASTERISK_ARI_PORT:
            raise_not_configured("ASTERISK_ARI_PORT")
        if not config.ASTERISK_ARI_USER:
            raise_not_configured("ASTERISK_ARI_USER")
        if not config.ASTERISK_ARI_PASS:
            raise_not_configured("ASTERISK_ARI_PASS")

        # Create semaphores to limit the number of concurrent calls and text conversations
        self.call_semaphore = asyncio.Semaphore(int(config.MAX_CONCURRENT_CALLS))
        self.message_semaphore = asyncio.Semaphore(int(config.MAX_CONCURRENT_CONVERSATIONS))

        # A dictionary to store the dialplan priority at which each extension is registered
        self.extension_priorities = {}

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

        # Convert to string
        extension = str(extension)

        # Raise an exception if the extension is already registered
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

        self.extension_priorities[extension] = 1
        added_successfully = False
        while not added_successfully:
            registration_action = panoramisk.actions.Action({
                "Action": "DialPlanExtensionAdd",
                "Context": f"{config.ASTERISK_INCOMING_CALL_CONTEXT if extension_type == 'call' else config.ASTERISK_INCOMING_TEXT_CONTEXT}",
                "Extension": extension,
                "Priority": self.extension_priorities[extension],
                "Application": "Stasis",
                "ApplicationData": f"{self.stasis_app},{extension_type}",
                "Replace": "no" # Do not replace existing extension. If it exists, we need to increment the priority. This is so that we can have multiple instances of asteramisk running and each will pass the call to the next if it is overloaded
            })

            response = await manager.send_action(registration_action)
            if response["Response"] == "Success":
                logger.info(f"Registered extension {extension} with type {extension_type} at priority {self.extension_priorities[extension]}")
                added_successfully = True
            elif response["Response"] == "Error" and response["Message"] == "That extension and priority already exist at that context":
                logger.info(f"Extension {extension} with priority {self.extension_priorities[extension]} already exists, probably another instance of asteramisk is running. Incrementing priority and trying again")
                self.extension_priorities[extension] += 1
            else:
                raise Exception(f"Failed to register extension {extension} with type {extension_type}. Response: {response}")

        manager.close()

    async def unregister_all_extensions(self):
        """
        Unregisters from asterisk all phone numbers registered for this instance.
        Is an async method
        """
        # Copy because we are going to remove items from the dictionary, which is not allowed during iteration
        extensions = list(self.handlers.keys())
        for extension in extensions:
            await self.unregister_extension(extension)

    async def unregister_extension(self, extension):
        """
        Unregisters a phone number from asterisk.
        Is an async method

        :param extension: The phone number to unregister
        """
        # Convert to string
        extension = str(extension)

        # Raise an exception if the extension is not registered
        if extension not in self.handlers:
            raise Exception(f"Extension {extension} is not registered and therefore cannot be unregistered")

        # Unregister from asterisk dialplan
        await self._unregister_extension(extension, 'call')
        await self._unregister_extension(extension, 'text')

        # Remove from handlers
        del self.handlers[extension]

    async def _unregister_extension(self, extension, extension_type):
        """
        Internally called to unregister an extension
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

        await manager.send_action(panoramisk.actions.Action({
            "Action": "DialPlanExtensionRemove",
            "Context": f"{config.ASTERISK_INCOMING_CALL_CONTEXT if extension_type == 'call' else config.ASTERISK_INCOMING_TEXT_CONTEXT}",
            "Extension": extension,
            "Priority": self.extension_priorities[extension]
        }))

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
            await self.unregister_all_extensions()
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

        # Check if we are overloaded
        try:
            await asyncio.wait_for(self.call_semaphore.acquire(), timeout=0.1)

        except asyncio.TimeoutError:
            logger.error("Call semaphore is full, dropping call")
            # Simply return without hanging up. 
            # This allows another node to pick up the call if multiple instances are running. e.g. docker swarm
            # If no other instance is running, the call will hang up anyway
            await channel.continueInDialplan()
            return

        else:
            # If the try succeeds, we are not overloaded
            ui = await VoiceUI.create(channel)
            extension = (await channel.getChannelVar(variable="EXTEN"))['value']
            call_handler, _ = self.handlers[extension]
            await call_handler(ui)

        finally:
            # Release here as well. Should only have been acquired if we are not overloaded
            self.call_semaphore.release()

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

            # Check if we are overloaded
            try:
                await asyncio.wait_for(self.message_semaphore.acquire(), timeout=0.1)
            except asyncio.TimeoutError:
                logger.error("Message semaphore is full, dropping message.")
                # Simply return without doing anything.
                await channel.continueInDialplan()
                return

            else:
                # Create a new UI and pass it to the message handler
                ui = await TextUI.create(phone_number)
                _, message_handler = self.handlers[extension]
                await message_handler(ui)

            finally:
                # Release here as well. Should only have been acquired if we are not overloaded
                self.message_semaphore.release()

    async def call_handler(self, ui: VoiceUI):
        """
        This is the default call handler.
        It does nothing.
        Override this method to handle calls or pass call_handler to the constructor
        """
        pass

    async def message_handler(self, ui: TextUI):
        """
        This is the default message handler.
        It does nothing.
        Override this method to handle messages or pass message_handler to the constructor
        """
        pass
