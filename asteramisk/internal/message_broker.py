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
        self._session_lock = asyncio.Lock()
        self._active_conversations = {}
        self._pending_messages = {}
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
        """Return whether a live TextUI session exists for this number."""
        async with self._session_lock:
            return phone_number in self._active_conversations

    async def register_conversation(self, phone_number):
        """Register and return a private incoming-message queue for a TextUI."""
        async with self._session_lock:
            if phone_number in self._active_conversations:
                raise ValueError(f"An active text conversation already exists for {phone_number}")
            queue = asyncio.Queue()
            pending = self._pending_messages.pop(phone_number, None)
            if pending is not None:
                while not pending.empty():
                    await queue.put(pending.get_nowait())
            self._active_conversations[phone_number] = queue
            return queue

    async def unregister_conversation(self, phone_number, queue):
        """Unregister a TextUI while preserving messages queued during teardown."""
        async with self._session_lock:
            if self._active_conversations.get(phone_number) is not queue:
                return
            del self._active_conversations[phone_number]
            if queue.empty():
                return
            pending = self._pending_messages.setdefault(phone_number, asyncio.Queue())
            while not queue.empty():
                await pending.put(queue.get_nowait())

    async def _ensure_rate_limiter(self, phone_number):
        if phone_number not in self._rate_limiters:
            self._rate_limiters[phone_number] = aiolimiter.AsyncLimiter(10) # 10 messages per minute

    async def message_received(self, sender_number, message):
        """
        Called when a message is received. The message is added to the conversation for the phone number
        This method should not be called by the user, it is called by the message receiver code in Server
        """
        async with self._session_lock:
            queue = self._active_conversations.get(sender_number)
            if queue is None:
                return False
            await queue.put(message)
            return True

    async def send_message(self, recipient_number, message):
        """
        Sends a message to a phone number
        Rate limited to 10 messages per minute
        :param recipient_number: The phone number to send the message to
        :param message: The message to send
        :return: None
        """
        await self._ensure_rate_limiter(recipient_number)

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
        """Wait for a message on the currently active conversation."""
        async with self._session_lock:
            queue = self._active_conversations.get(phone_number)
        if queue is None:
            raise ValueError(f"No active text conversation exists for {phone_number}")
        return await queue.get()

    async def send_receive(self, phone_number, message):
        """Send a message and wait for a response on the active conversation."""
        await self.send_message(phone_number, message)
        return await self.get_incoming_message(phone_number)

    async def close(self):
        self._manager.close()
