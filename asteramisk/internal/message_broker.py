import base64
import asyncio
import aiolimiter
from panoramisk import Manager
from panoramisk.actions import Action

from asteramisk.config import config
from asteramisk.internal.async_singleton import AsyncSingleton

class MessageBroker(AsyncSingleton):
    async def __create__(self, our_number):
        self._our_number = our_number
        self._message_lock = asyncio.Lock()
        self._incoming_messages = {}
        self._rate_limiters = {}
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

    async def has_conversation(self, phone_number):
        return phone_number in self._incoming_messages

    async def _ensure_conversation_exists(self, phone_number):
        if phone_number not in self._incoming_messages:
            self._incoming_messages[phone_number] = asyncio.Queue()
            self._rate_limiters[phone_number] = aiolimiter.AsyncLimiter(10) # 10 messages per minute

    async def message_received(self, sender_number, message):
        """
        Called when a message is received. The message is added to the conversation for the phone number
        This method should not be called by the user, it is called by the message receiver code in Server
        """
        await self._ensure_conversation_exists(sender_number)
        await self._incoming_messages[sender_number].put(message)

    async def send_message(self, recipient_number, message):
        """
        Sends a message to a phone number
        Rate limited to 10 messages per minute
        :param recipient_number: The phone number to send the message to
        :param message: The message to send
        :return: None
        """
        await self._ensure_conversation_exists(recipient_number)

        message_action = Action({
            'Action': 'MessageSend',
            'Destination': f"pjsip:{config.ASTERISK_PSTN_ENDPOINT}/<sip:{recipient_number}@{config.ASTERISK_PSTN_GATEWAY_HOST}>",
            'From': f"sip:{config.ASTERISK_PSTN_GATEWAY_USER}@{config.ASTERISK_PSTN_GATEWAY_HOST}",
            'Base64Body': base64.b64encode(message.encode('utf-8')).decode('utf-8'),
            'Variable': f"Remote-Party-ID=<sip:{self._our_number}@{config.ASTERISK_PSTN_GATEWAY_HOST}>",
        })

        # Ensure we don't send more than 10 messages per minute to the same number
        # and only one message at a time because I want to avoid potential issues with race conditions
        async with self._message_lock, self._rate_limiters[recipient_number]:
            await self._manager.send_action(message_action)

    async def get_incoming_message(self, phone_number):
        """
        Waits for a message to be received from the phone number
        :param phone_number: The phone number to wait for a message from
        :return: The message received
        """
        await self._ensure_conversation_exists(phone_number)
        return await self._incoming_messages[phone_number].get()

    async def send_receive(self, phone_number, message):
        """
        Sends a message to the phone number and waits for a response
        :param phone_number: The phone number to send the message to
        :param message: The message to send
        :return: The message received in response
        """
        await self.send_message(phone_number, message)
        return await self.get_incoming_message(phone_number)

    async def close(self):
        self._manager.close()
