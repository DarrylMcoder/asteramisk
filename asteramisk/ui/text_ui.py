import asyncio
from contextlib import asynccontextmanager, suppress
from agents import TContext
from agents.realtime import RealtimeAgent, RealtimeRunner

from asteramisk.ui import UI
from asteramisk.config import config
from asteramisk.exceptions import HangupException
from asteramisk.internal.message_broker import MessageBroker

import logging
logger = logging.getLogger(__name__)

class TextUI(UI):
    async def __create__(self, recipient_number, callerid_number=config.SYSTEM_PHONE_NUMBER, callerid_name=config.SYSTEM_NAME):
        self._broker: MessageBroker = await MessageBroker.create(callerid_number)
        self._recipient_number = recipient_number
        self._our_callerid_number = callerid_number
        self._our_callerid_name = callerid_name
        self._incoming_queue = await self._broker.register_conversation(recipient_number)
        self._closed_event = asyncio.Event()
        self._closed = False
        self.is_active = True
        await super().__create__()

    @property
    def ui_type(self):
        return self.UIType.TEXT

    @property
    def _unique_id(self):
        return self._recipient_number

    @property
    def remote_number(self):
        return self._recipient_number

    @property
    def remote_name(self):
        return ""

    @property
    def local_number(self):
        return self._our_callerid_number
    
    async def answer(self):
        """ \"Answer\" the call. Mostly for compatibility with other UIs. Connects to the broker. """
        if self._closed:
            raise HangupException("TextUI is closed; create a new TextUI to start another conversation")
        await self._broker.connect()
        self.is_active = True

    async def hangup(self, wait=True):
        """Close this text session; ``wait`` is accepted for UI compatibility."""
        if self._closed:
            return
        self._closed = True
        self.is_active = False
        self._closed_event.set()
        await self._broker.unregister_conversation(self._recipient_number, self._incoming_queue)

    def _ensure_active(self):
        if self._closed or not self.is_active:
            raise HangupException("TextUI is closed; create a new TextUI to start another conversation")

    async def _receive_message(self):
        self._ensure_active()
        message_task = asyncio.create_task(self._incoming_queue.get())
        closed_task = asyncio.create_task(self._closed_event.wait())
        try:
            done, _ = await asyncio.wait(
                (message_task, closed_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            # If both complete together, consume a message that was already
            # accepted before shutdown rather than dropping it.
            if message_task in done:
                return message_task.result()
            raise HangupException("TextUI was hung up while waiting for a message")
        finally:
            for task in (message_task, closed_task):
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
    
    async def say(self, text):
        """
        Say text to the user. Will be sent as a text message
        :param text: Text to say
        """
        self._ensure_active()
        await self._broker.send_message(self._recipient_number, text)

    async def prompt(self, text):
        """
        Prompt the user for input
        :param text: Text to prompt the user
        :return: The user's input
        """
        self._ensure_active()
        await self.say(text)
        return await self._receive_message()

    async def gather(self, text, num_digits):
        """
        Prompt the user to enter digits
        :param text: Text to prompt the user
        :param num_digits: Number of digits to wait for
        :return: The user's input
        """
        digits: str = await self.prompt(text)
        if len(digits) != num_digits:
            return await self.gather(f"Please enter {num_digits} digits", num_digits)
        if not digits.isdigit():
            return await self.gather(f"Please enter {num_digits} digits", num_digits)
        return digits

    async def ask_yes_no(self, text):
        """
        Ask the user a yes/no question
        :param text: Text to prompt the user
        :return: True if the user answers yes or False if the user answers no
        """
        message = f"{text} (yes/no)"
        response = (await self.prompt(message)).strip().lower()
        if response in {"yes", "y"}:
            return True
        if response in {"no", "n"}:
            return False
        await self.say("Please answer yes or no.")
        return await self.ask_yes_no(text)

    async def input_stream(self):
        """
        Returns an async generator that yields incoming messages from the user
        :return: An async generator that yields incoming messages from the user
        """
        try:
            while self.is_active:
                message = await self._receive_message()
                yield message
        except (GeneratorExit, HangupException):
            pass

    @asynccontextmanager
    async def run_realtime_agent(self, agent: RealtimeAgent, talk_first: bool = True, model: str = None, voice: str = None, context: TContext = {}):
        """Connect this text UI to an OpenAI realtime agent."""
        if not isinstance(agent, RealtimeAgent):
            raise ValueError("agent must be an agents.realtime.RealtimeAgent")
        if model is None:
            model = config.DEFAULT_REALTIME_GPT_MODEL

        runner = RealtimeRunner(starting_agent=agent, config={
            "model_settings": {
                "model_name": model,
                "modalities": ["text"]
            }
        })

        async def message_loop(session):
            try:
                while self.is_active:
                    logger.debug("TextUI.run_realtime_agent: waiting for message")
                    message = await self._receive_message()
                    await session.send_message(message)
            except HangupException:
                return

        async def _gen():
            async with await runner.run(context=context) as session:
                if talk_first:
                    await session.send_message("New conversation, greet the user.")
                message_task = asyncio.create_task(message_loop(session))
                try:
                    async for event in session:
                        if event.type == "error":
                            logger.error(f"OpenAI session error: {event}")
                        yield event
                finally:
                    message_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await message_task

        yield _gen()

    async def bridge(self, ui):
        """
        Bridges two text UIs together
        Media will flow between the two UIs
        :param ui: The UI to bridge to
        :return: None
        """
        if ui.ui_type == self.UIType.TEXT:
            # Simply constantly copy messages between the two UIs
            async def _to_ui():
                async for message in self.input_stream():
                    await ui.say(message)

            async def _from_ui():
                async for message in ui.input_stream():
                    await self.say(message)

            await asyncio.gather(_to_ui(), _from_ui())
        else:
            raise ValueError("Can only bridge TextUIs to TextUIs")
