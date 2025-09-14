import asyncio
from agents import Agent
from contextlib import suppress
from agents.realtime import RealtimeAgent, RealtimeRunner

from asteramisk.ui import UI
from asteramisk.config import config
from asteramisk.internal.message_broker import MessageBroker

import logging
logger = logging.getLogger(__name__)

class TextUI(UI):
    async def __create__(self, recipient_number, our_callerid_number=config.SYSTEM_PHONE_NUMBER, our_callerid_name=config.SYSTEM_NAME):
        self._broker: MessageBroker = await MessageBroker.create(our_callerid_number)
        self._recipient_number = recipient_number
        self._our_callerid_number = our_callerid_number
        self._our_callerid_name = our_callerid_name
        self.is_active = False
        super().__create__()

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
        await self._broker.connect()
        self.is_active = True

    async def hangup(self):
        """ \"Hangup\" the call. Mostly for compatibility with other UIs. Closes the broker. """
        await self._broker.close()
        self.is_active = False
    
    async def say(self, text):
        """
        Say text to the user. Will be sent as a text message
        :param text: Text to say
        """
        await self._broker.send_message(self._recipient_number, text)

    async def prompt(self, text):
        """
        Prompt the user for input
        :param text: Text to prompt the user
        :return: The user's input
        """
        return await self._broker.send_receive(self._recipient_number, text)

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
        response = await self.prompt(message)
        return 'yes' in response.lower()

    async def input_stream(self):
        while self.is_active:
            message = await self._broker.get_incoming_message(self._recipient_number)
            yield message

    async def connect_openai_agent(self, agent: Agent, talk_first: bool = True, model: str = None, voice: str = None) -> None:
        """
        Connect this UI to an OpenAI agent
        This automates the passing of messages or audio between the UI and the OpenAI agent
        After connecting, control of the conversation is passed to the OpenAI agent.
        You will likely then want to use OpenAI's tool calling to manage your conversation flow
        Example usage:
        .. code-block:: python
            from agents import Agent
            from asteramisk.ui import TextUI
            from asteramisk.server import Server

            async def message_handler(ui: TextUI):
                await ui.answer()
                await ui.say("Passing control to OpenAI agent")
                bob = Agent(
                    name="Bob",
                    instructions="Your agent instructions"
                )
                await ui.connect_openai_agent(bob, model="gpt-4o")
                # Control of the conversation is now passed to the OpenAI agent
                # You can use OpenAI's tool calling to manage your conversation flow
                # You can still use the UI, but the agent is also in the conversation so it would likely be better not to play any audio

        :param agent: The OpenAI agent to connect to the UI, either an agents.Agent or an agents.realtime.RealtimeAgent
        :param talk_first: If True, the agent will speak first
        :return: A task that will run the OpenAI agent. You can await this task to wait for the conversation to end
        """
        async def _run_agent_task():
            nonlocal model # We might change the model so we need to declare it nonlocal
            if isinstance(agent, Agent):
                await self._run_text_agent(agent, talk_first, model)
            elif isinstance(agent, RealtimeAgent):
                if model is None:
                    # Use the cheaper mini model rather than the default GPT-4o
                    model = config.DEFAULT_REALTIME_GPT_MODEL
                runner = RealtimeRunner(starting_agent=agent, config={
                    "model_settings": {
                        "model_name": model,
                        "modalities": ["text"]
                    }
                })
                async with await runner.run() as session:
                    if talk_first:
                        # The agent is expected to speak first.
                        await session.send_message("New call, greet the caller.")
                    async def message_loop():
                        # Directly pass messages from the UI to the OpenAI session
                        while self.is_active:
                            logger.debug("message_loop: Waiting for message")
                            message = await self._broker.get_incoming_message(self._recipient_number)
                            await session.send_message(message)
                    asyncio.create_task(message_loop())
                    async for event in session:
                        print(event.type)
                        if event.type == "audio":
                            pass
                        elif event.type == "audio_interrupted":
                            # Audio was interrupted, stop speaking and listen
                            await self.audconn.clear_send_queue()
                        elif event.type == "raw_model_event":
                            print(" ", event.data.type)
                            if event.data.type == "raw_server_event":
                                print("     ", event.data.data["type"])
                                if event.data.data["type"].count("rate") > 0:
                                    print("         ", event)
                        elif event.type == "error":
                            logger.error(f"OpenAI session error: {event}")

            else:
                raise ValueError(f"Unsupported agent type: {type(agent)}")

        self._agent_task = asyncio.create_task(_run_agent_task())
        return self._agent_task

    async def disconnect_openai_agent(self):
        if self._agent_task:
            self._agent_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._agent_task
            self._agent_task = None
