import asyncio
from typing import Any
from agents import Agent, SQLiteSession, Runner, RunResult
from agents.realtime import RealtimeAgent, RealtimeRunner

from asteramisk.internal.async_class import AsyncClass
from asteramisk.config import config

import logging
logger = logging.getLogger(__name__)

class UI(AsyncClass):
    """
    Base class for all user interfaces
    All user interfaces have these basic methods
    All methods are async
    """
    class UIType:
        VOICE = "voice"
        TEXT = "text"

    @property
    def ui_type(self):
        raise NotImplementedError("Subclasses must implement this method")

    @property
    def _unique_id(self):
        raise NotImplementedError

    async def answer(self):
        raise NotImplementedError

    async def hangup(self):
        raise NotImplementedError

    async def say(self, text):
        """
        Say text to the user
        :param text: Text to say
        """
        raise NotImplementedError

    async def prompt(self, text):
        """
        Prompt the user for input
        :param text: Text to prompt the user
        :return: The user's input
        """
        raise NotImplementedError

    async def gather(self, text, num_digits) -> str:
        """
        Prompt the user for dtmf input
        :param text: Text to prompt the user
        :return: The user's input
        """
        raise NotImplementedError

    async def ask_yes_no(self, text) -> bool:
        """
        Ask the user a yes/no question
        :param text: Text to prompt the user
        :return: True if the user answers yes or False if the user answers no
        """
        raise NotImplementedError

    async def input_stream(self):
        raise NotImplementedError

    async def menu(self, text, callbacks: dict[str, callable] = None, voice_callbacks: dict[str, callable] = None, text_callbacks: dict[str, callable] = None):
        """
        Present a menu of options to the user
        Provide `text` as a string containing the menu options available. 
        Provide `callbacks`, `voice_callbacks`, or `text_callbacks` as a dictionary of callbacks, one for each option.
        If only `callbacks` is provided, it is used for both voice and text UIs.
        If `voice_callbacks` and `text_callbacks` are provided, the one corresponding to the current type of UI is used.
        :param text: Text to prompt the user, must contain the menu
        :param callbacks: List of callbacks, one for each option
        :param voice_callbacks: Same as callbacks, but used only in voice UIs
        :param text_callbacks: Same as callbacks, but used only in text UIs
        :return: None. Selected callback will be called
        """
        if callbacks and (voice_callbacks or text_callbacks):
            logger.warning("Both callbacks and voice/text callbacks provided. This is rather ambiguous. Using callbacks.")

        if callbacks:
            local_callbacks = callbacks
        elif voice_callbacks or text_callbacks:
            if voice_callbacks and self.ui_type == self.UIType.VOICE:
                local_callbacks = voice_callbacks
            elif text_callbacks and self.ui_type == self.UIType.TEXT:
                local_callbacks = text_callbacks
            else:
                raise ValueError("No callbacks provided for current UI type")
        else:
            raise ValueError("No callbacks provided")

        # Prompt the user to select an option
        # Kinda breaking my style here, but I think we should use digit menus for voice UIs and text menus for text UIs
        if self.ui_type == self.UIType.VOICE:
            num_digits = max([len(str(i)) for i in local_callbacks.keys()])
            selected = await self.gather(text, num_digits)
        elif self.ui_type == self.UIType.TEXT:
            selected = await self.prompt(text)
        if selected not in local_callbacks:
            return await self.menu("That option is not available, please try again", callbacks, voice_callbacks, text_callbacks)
        return await local_callbacks[selected]()

    async def select(self, text, options: dict[str, Any], voice_options: dict[str, Any] = None, text_options: dict[str, Any] = None):
        """
        Present a list of choices to the user
        :param text: Text to prompt the user, must contain the menu
        :param options: Dictionary of options, like {"1": "Option 1", "2": "Option 2", ...}
        :param voice_options: Same as options, but used only in voice UIs
        :param text_options: Same as options, but used only in text UIs
        :return: Selected option
        """
        if options and (voice_options or text_options):
            logger.warning("Both options and voice/text options provided. This is rather ambiguous. Using options.")
        if options:
            local_options = options
        elif voice_options or text_options:
            if voice_options and self.ui_type == self.UIType.VOICE:
                local_options = voice_options
            elif text_options and self.ui_type == self.UIType.TEXT:
                local_options = text_options
            else:
                raise ValueError("No options provided for current UI type")
        else:
            raise ValueError("No options provided")
        # Prompt the user to select an option
        # Kinda breaking my style here, but I think we should use digit menus for voice UIs and text menus for text UIs
        if self.ui_type == self.UIType.VOICE:
            num_digits = max([len(str(i)) for i in local_options.keys()])
            selected = await self.gather(text, num_digits)
        elif self.ui_type == self.UIType.TEXT:
            selected = await self.prompt(text)
        if selected not in local_options:
            return await self.select("That option is not available, please try again", options, voice_options, text_options)
        return local_options[selected]
    
    async def _run_openai_agent(self, agent: Agent, talk_first: bool = True, model: str = None, voice: str = None) -> None:
        # Wrap the entire task in a try/except block to catch any exceptions
        try:
            if self.ui_type == self.UIType.TEXT and isinstance(agent, RealtimeAgent):
                raise ValueError("RealtimeAgent is not supported for text UIs")
            elif self.ui_type == self.UIType.VOICE and isinstance(agent, RealtimeAgent):
                await self.audconn.set_resampling(rate=24000, channels=1, audio_format="s16le")
                if model is None:
                    # Use the cheaper mini model rather than the default GPT-4o
                    model = config.DEFAULT_REALTIME_GPT_MODEL
                runner = RealtimeRunner(starting_agent=agent, config={
                    "model_settings": {
                        "model_name": model,
                        "modalities": ["text", "audio"],
                        "voice": voice
                    }
                })
                async with await runner.run() as session:
                    if talk_first:
                        # The agent is expected to speak first. E.g. answering a phone call
                        await session.send_message("New call, greet the caller.")
                    async def dtmf_event_handler(objs, event):
                        await session.send_message(event['digit'])
                    self.channel.on_event('ChannelDtmfReceived', dtmf_event_handler)
                    async def audio_loop():
                        # Directly pass audio from the UI to the OpenAI session
                        while self.is_active:
                            logger.debug("audio_loop: Waiting for audio")
                            audio = await self.audconn.read()
                            await session.send_audio(audio)
                    asyncio.create_task(audio_loop())
                    async for event in session:
                        print(event.type)
                        if event.type == "audio":
                            audio = event.audio.data
                            logger.debug("audio_out: Got audio")
                            await self.audconn.write(audio)
                            logger.debug("audio_out: Wrote audio")
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

            elif isinstance(agent, Agent):
                # If the agent is text based, regardless of the UI type
                if model is None and not agent.model:
                    # Use the cheaper mini model rather than the default GPT-4o
                    agent.model = config.DEFAULT_TEXT_GPT_MODEL
                runner = Runner()
                sqlite_session = SQLiteSession(session_id=self._unique_id)
                if talk_first:
                    # The agent is expected to speak first. E.g. answering a phone call
                    result: RunResult = await runner.run(
                            starting_agent=agent,
                            session=sqlite_session,
                            input="New conversation, greet the user."
                    )
                    print("AI:", result.final_output)
                    await self.say(result.final_output)
                async for user_input in self.input_stream():
                    print("User:", user_input)
                    result: RunResult = await runner.run(
                            starting_agent=agent,
                            session=sqlite_session,
                            input=user_input
                    )
                    print("AI:", result.final_output)
                    await self.say(result.final_output)
            else:
                raise ValueError(f"Invalid combination of UI type {self.ui_type} and session type {type(session)}")

        except Exception as e:
            logger.exception(f"Error in _exchange_media_with_session_task: {e}")


    async def connect_openai_agent(self, agent: Agent, talk_first: bool = True, model: str = None, voice: str = None) -> None:
        """
        Connect this UI to an OpenAI agent
        This automates the passing of messages or audio between the UI and the OpenAI agent
        After connecting, control of the conversation is passed to the OpenAI agent.
        You will likely then want to use OpenAI's tool calling to manage your conversation flow
        If the current UI is a text UI, the agent must be an agents.Agent
        If the current UI is a voice UI, the agent can be either an agents.Agent or an agents.realtime.RealtimeAgent
        If the UI is a voice UI and the agent is not a RealtimeAgent, we will transcribe the audio ourself and pass it to the OpenAI text based agent
        This will cause some latency, but it's definitely cheaper than RealtimeAgent so it's probably worth it in some cases
        Example usage:
        .. code-block:: python
            from asteramisk.ui import VoiceUI
            from asteramisk.server import Server

            async def call_handler(ui: VoiceUI):
                await ui.answer()
                await ui.say("Passing control to OpenAI agent")
                bob = RealtimeAgent(
                    name="Bob",
                    instructions="Your agent instructions"
                )
                await ui.connect_openai_agent(bob)
                # Control of the conversation is now passed to the OpenAI agent
                # You can use OpenAI's tool calling to manage your conversation flow
                # You can still use the UI, but the agent is also in the conversation so it would likely be better not to play any audio

        :param agent: The OpenAI agent to connect to the UI
        :param talk_first: If True, the agent will speak first, e.g. answering a phone call
        :return: A task that will run the OpenAI agent. You can await this task to wait for the conversation to end
        """
        return asyncio.create_task(self._run_openai_agent(agent, talk_first, model, voice))
