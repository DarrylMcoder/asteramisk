import asyncio
import aiohttp
from typing import Union
from panoramisk import Manager

import asteramisk.ui
import asteramisk.exceptions
from asteramisk.config import config
from asteramisk.internal.ari_client import AriClient
from asteramisk.internal.async_class import AsyncClass

import logging
logger = logging.getLogger(__name__)

class Communicator(AsyncClass):
    """
    A class for making calls and text message conversations.
    
    Example usage:

    .. code-block:: python

        communicator = await Communicator.create(callerid_number="1234567890", callerid_name="John Doe")
        try:
            await communicator.make_call(recipient_number="1234567890")
            await communicator.send_message(recipient_number="1234567890", message="Hello world!")
            await communicator.send_receive(recipient_number="1234567890", message="Hello world!")
        finally:
            await communicator.close()

    Can be used as a context manager.

    .. code-block:: python

        async with await Communicator.create() as communicator:
            await communicator.make_call(recipient_number="1234567890")
            await communicator.send_message(recipient_number="1234567890", message="Hello world!")
    """
    async def __create__(self, callerid_number=None, callerid_name=None):
        """
        Initializes the Communicator.
        :param callerid_number: The number to use for the caller ID.
        :type callerid_number: str
        :param callerid_name: The name to use for the caller ID.
        :type callerid_name: str
        :return: Communicator
        """
        self._callerid_number = callerid_number
        self._callerid_name = callerid_name

        self._ari_client = await AriClient.create()
        self._manager = Manager(
            host=config.ASTERISK_HOST,
            port=config.ASTERISK_AMI_PORT,
            username=config.ASTERISK_AMI_USER,
            secret=config.ASTERISK_AMI_PASS,
            ssl=False
        )
        await self._manager.connect()

    async def connect(self):
        await self._manager.connect()

    async def close(self):
        self._manager.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    async def make_call(self,
                        recipient_number=None,
                        channel=None,
                        callerid_number=None, # Callerids are None for a reason, so we can use the Communicator instance defaults. See further down
                        callerid_name=None,
                        timeout=None) -> asteramisk.ui.VoiceUI:
        """ 
        Makes a call to the recipient and returns a VoiceUI object.
        :param recipient_number: The number to call. Uses PJSIP with voip.ms
        :param channel: The channel to dial for the call. Mutually exclusive with recipient_number
        :param callerid_number: The number to use for the caller ID.
        :param callerid_name: The name to use for the caller ID.
        :param timeout: The timeout in seconds for the call
        :return: An asteramisk.ui.VoiceUI object.
        :raises ValueError: If neither recipient_number or channel is provided or both are provided
        :raises asteramisk.exceptions.CallFailedException: If the call fails
        """
        
        if not recipient_number and not channel:
            raise ValueError("Must provide either recipient_number or channel")
        if recipient_number and channel:
            raise ValueError("Cannot provide both recipient_number and channel")

        callerid_number = callerid_number or self._callerid_number or config.SYSTEM_PHONE_NUMBER
        callerid_name = callerid_name or self._callerid_name or config.SYSTEM_NAME

        if recipient_number:
            # Do this only after null check as it will convert None to literally 'None'
            recipient_number = str(recipient_number)
            channel = f"PJSIP/{recipient_number}@{config.ASTERISK_PSTN_ENDPOINT}"

        if not callerid_name:
            raise asteramisk.exceptions.ConfigurationException("Caller ID name is not set. This will not work unless this is a call to a local extension on our system.")
        if not callerid_number:
            raise asteramisk.exceptions.ConfigurationException("Caller ID number is not set. This will not work unless this is a call to a local extension on our system.")

        # Convert to string in case its int
        callerid_number = str(callerid_number)

        if callerid_number and len(callerid_number) != 10:
            logger.warning(f"Caller ID number {callerid_number} is not 10 digits. It will not work. Will be replaced with default number.")
            callerid_number = config.SYSTEM_PHONE_NUMBER

        logger.info(f"Making call to {recipient_number} on channel {channel}")

        channel = await self._ari_client.channels.originate(
            endpoint=channel,
            app="asteramisk",
            callerId=f"{callerid_name} <{callerid_number}>",
            timeout=timeout or config.OUTBOUND_CALL_TIMEOUT
        )
        logger.info(f"Created channel {channel.json['name']} with ID {channel.json['id']}")

        # All the following in one try/except block to catch originating UI hangups (asyncio.CancelledError)
        try:

            # Poll for the channel to be ready
            start_time = asyncio.get_event_loop().time()
            timeout = timeout or config.OUTBOUND_CALL_TIMEOUT or 30
            while asyncio.get_event_loop().time() - start_time < timeout:
                try:
                    channel = await self._ari_client.channels.get(channelId=channel.json['id'])
                    state = channel.json['state']
                    if state == "Up":
                        logger.debug(f"Channel {channel.json['name']} is now Up, Detected via polling")
                        break
                except aiohttp.web_exceptions.HTTPNotFound:
                    raise asteramisk.exceptions.CallFailedException("Call failed. Channel destroyed before being ready.")
                await asyncio.sleep(0.1)
            else:
                # Timed out
                raise asteramisk.exceptions.CallFailedException("Call failed. Reached timeout waiting for channel to be answered.")
            
            logger.debug(f"Dialled out to {recipient_number} on channel {channel.json['name']} successfully")

            try:
                await self._ari_client.applications.get(applicationName="asteramisk")
            except aiohttp.web_exceptions.HTTPNotFound:
                raise asteramisk.exceptions.AsteramiskException("The default `asteramisk` Stasis application was not found. This should not happen as it is created on server startup.")

            ui = await asteramisk.ui.VoiceUI.create(channel)
            # I know this seems strange, but audio simply won't play via audio socket until we play a sound file like this
            # This is only a problem on outbound calls
            await ui.channel.play(media="sound:ascending-2tone")
            return ui
        except asyncio.CancelledError:
            logger.info("Call to {recipient_number or channel} was cancelled because the originating UI channel was destroyed")
            # Hangup the outgoing channel
            await channel.hangup()
            raise

    async def make_text(self,
                        recipient_number, # No reason to make this optional
                        callerid_number=None,
                        callerid_name=None) -> asteramisk.ui.TextUI:
        """
        Starts a new messaging conversation with the recipient.
        :param recipient_number: The number to message.
        :param callerid_number: The number to use for the caller ID.
        :param callerid_name: The name to use for the caller ID.
        :return: An asteramisk.ui.TextUI object.
        :raises ValueError: If the recipient_number is not provided
        """
        callerid_number = callerid_number or self._callerid_number or config.SYSTEM_PHONE_NUMBER
        callerid_name = callerid_name or self._callerid_name or config.SYSTEM_NAME

        return await asteramisk.ui.TextUI.create(recipient_number, callerid_number=callerid_number, callerid_name=callerid_name)

    async def make_conversation(self,
                                recipient_number=None,
                                callerid_number=None,
                                callerid_name=None,
                                contact_method=None) -> Union[asteramisk.ui.VoiceUI, asteramisk.ui.TextUI]:
        """
        Starts a new messaging conversation with the recipient.
        :param recipient_number: The number to contact.
        :param callerid_number: The number to use for the caller ID.
        :param callerid_name: The name to use for the caller ID.
        :param contact_method: The contact method to use. Either "call" or "text"
        :return: An asteramisk.ui.VoiceUI or asteramisk.ui.TextUI object.
        :raises ValueError: If the contact method is not "call" or "text"
        """
        if contact_method == "call":
            return await self.make_call(recipient_number, callerid_number=callerid_number, callerid_name=callerid_name)
        elif contact_method == "text":
            return await self.make_text(recipient_number, callerid_number=callerid_number, callerid_name=callerid_name)
        else:
            raise ValueError(f"Unknown contact method {contact_method}")
