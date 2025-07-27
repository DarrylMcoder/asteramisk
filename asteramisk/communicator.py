from typing import Union
from panoramisk import Manager
from panoramisk.actions import Action

import asteramisk.ui
import asteramisk.exceptions
from asteramisk.config import config

import logging
logger = logging.getLogger(__name__)

class Communicator:
    """
    A class for making calls and text message conversations.
    
    Example usage:

    .. code-block:: python

        communicator = await Communicator.create()
        try:
            await communicator.make_call(recipient_number="1234567890")
            await communicator.send_message(recipient_number="1234567890", message="Hello world!")
            await communicator.send_receive(recipient_number="1234567890", message="Hello world!")
        finally:
            await communicator.close()

    Can be used as a context manager.

    .. code-block:: python

        async with Communicator.create() as communicator:
            await communicator.make_call(recipient_number="1234567890")
            await communicator.send_message(recipient_number="1234567890", message="Hello world!")
    """
    def __init__(self, callerid_number=config.SYSTEM_PHONE_NUMBER, callerid_name=config.SYSTEM_NAME):
        """
        Initializes the Communicator.
        :param callerid_number: The number to use for the caller ID.
        :type callerid_number: str
        :param callerid_name: The name to use for the caller ID.
        :type callerid_name: str
        """
        self._callerid_number = callerid_number
        self._callerid_name = callerid_name

        self._manager = Manager(
            host=config.ASTERISK_HOST,
            port=config.ASTERISK_AMI_PORT,
            username=config.ASTERISK_AMI_USER,
            secret=config.ASTERISK_AMI_PASS,
            ssl=False
        )

    @classmethod
    async def create(cls, *args, **kwargs):
        instance = cls(*args, **kwargs)
        await instance.connect()
        return instance

    async def connect(self):
        await self._manager.connect()

    async def close(self):
        await self._manager.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    async def make_call(self,
                        recipient_number=None,
                        channel=None,
                        application="AGI",
                        data="agi:async",
                        callerid_number=None,
                        callerid_name=None) -> asteramisk.ui.VoiceUI:
        """ 
        Makes a call to the recipient and returns a VoiceUI object.
        :param recipient_number: The number to call. Uses PJSIP with voip.ms
        :type recipient_number: str
        :param channel: The channel to dial for the call. Mutually exclusive with recipient_number
        :type channel: str
        :param application: The application to execute at our end of the call.
        :type application: str
        :param data: The data to pass to the application.
        :type data: str
        :param callerid_number: The number to use for the caller ID.
        :type callerid_number: str
        :param callerid_name: The name to use for the caller ID.
        :type callerid_name: str
        :return: An asteramisk.ui.VoiceUI object.
        :rtype: asteramisk.ui.VoiceUI
        :raises ValueError: If neither recipient_number or channel is provided or both are provided
        :raises asteramisk.exceptions.CallFailedException: If the call fails
        """
        
        if not recipient_number and not channel:
            raise ValueError("Must provide either recipient_number or channel")
        if recipient_number and channel:
            raise ValueError("Cannot provide both recipient_number and channel")

        if not callerid_number:
            callerid_number = self._callerid_number
        if not callerid_name:
            callerid_name = self._callerid_name

        if recipient_number:
            channel = f"PJSIP/{recipient_number}@{config.ASTERISK_PSTN_ENDPOINT}"

        if len(callerid_number) != 10:
            logger.warning(f"Caller ID number {callerid_number} is not 10 digits. It will not work. Will be replaced with default number.")
            callerid_number = config.SYSTEM_PHONE_NUMBER

        logger.info(f"Making call to {recipient_number} on channel {channel}")

        originate_action = Action({
            "Action": "Originate",
            "Channel": channel,
            "Application": application,
            "Data": data,
            "CallerID": f"{callerid_name} <{callerid_number}>",
            "Async": True  # This seems to be required.
        })

        response = await self._manager.send_action(originate_action)
        print("Originate AMI response", response)
        for event in response:
            # Check if the call failed
            if "Event" in event and "Response" in event and \
                    event["Event"] == "OriginateResponse" and event["Response"] == "Failure":
                raise asteramisk.exceptions.CallFailedException(f"Failed to make call to {recipient_number}")

        # Get the channel
        if not response[1].channel:
            raise asteramisk.exceptions.CallFailedException(f"Failed to get channel for call to {recipient_number}")
        channel = response[1].channel

        ui = asteramisk.ui.VoiceUI(channel)
        return ui

    async def make_text(self,
                        recipient_number=None,
                        callerid_number=config.SYSTEM_PHONE_NUMBER,
                        callerid_name=config.SYSTEM_NAME) -> asteramisk.ui.TextUI:
        """
        Starts a new messaging conversation with the recipient.
        :param recipient_number: The number to message.
        :type recipient_number: str
        :param callerid_number: The number to use for the caller ID.
        :type callerid_number: str
        :param callerid_name: The name to use for the caller ID.
        :type callerid_name: str
        :return: An asteramisk.ui.TextUI object.
        :rtype: asteramisk.ui.TextUI
        """
        return asteramisk.ui.TextUI(recipient_number, callerid_number=callerid_number, callerid_name=callerid_name)

    async def make_conversation(self,
                                recipient_number=None,
                                callerid_number=config.SYSTEM_PHONE_NUMBER,
                                callerid_name=config.SYSTEM_NAME,
                                contact_method=None) -> Union[asteramisk.ui.VoiceUI, asteramisk.ui.TextUI]:
        """
        Starts a new messaging conversation with the recipient.
        :param recipient_number: The number to contact.
        :type recipient_number: str
        :param callerid_number: The number to use for the caller ID.
        :type callerid_number: str
        :param callerid_name: The name to use for the caller ID.
        :type callerid_name: str
        :param contact_method: The contact method to use. Either "call" or "text"
        :type contact_method: str
        :return: An asteramisk.ui.VoiceUI or asteramisk.ui.TextUI object.
        :rtype: Union[asteramisk.ui.VoiceUI, asteramisk.ui.TextUI]
        """
        if contact_method == "call":
            return await self.make_call(recipient_number, callerid_number=callerid_number, callerid_name=callerid_name)
        elif contact_method == "text":
            return await self.make_text(recipient_number, callerid_number=callerid_number, callerid_name=callerid_name)
        else:
            raise ValueError(f"Unknown contact method {contact_method}")
