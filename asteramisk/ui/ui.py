import asyncio
from typing import Any
from agents import Agent, SQLiteSession, Runner, RunResult, TContext

from asteramisk.config import config
from asteramisk.exceptions import GoBackException
from asteramisk.internal.async_class import AsyncClass

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

    async def __aenter__(self):
        await self.answer()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.hangup()

    async def close(self):
        await self.hangup()

    @property
    def ui_type(self):
        raise NotImplementedError("Subclasses must implement this method")

    @property
    def _unique_id(self):
        raise NotImplementedError

    @property
    def remote_number(self):
        """
        The phone number of the other end of the call
        """
        raise NotImplementedError

    @property
    def remote_name(self):
        """
        The name (CALLERID name if available) of the other end of the call
        Not generally available for text UIs
        """
        raise NotImplementedError

    @property
    def local_number(self):
        """
        The phone number of our end of the call
        """
        raise NotImplementedError

    async def answer(self):
        """
        Answer the call or text message conversation
        Performs any necessary setup
        """
        raise NotImplementedError

    async def hangup(self):
        """
        Hangup the call or text message conversation
        Performs any necessary cleanup
        """
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
        """
        Get a stream of input from the user
        Example usage:
        ... code-block:: python
        async for user_input in ui.input_stream():
            print(user_input)
        """
        raise NotImplementedError

    async def connect_openai_agent(self, agent: Agent, talk_first: bool = True, model: str = None, voice: str = None, context: TContext = None) -> asyncio.Task:
        """
        Connect to an OpenAI agent. Either an agents.Agent or an agents.realtime.RealtimeAgent
        Example usage:
        ... code-block:: python
        import asyncio
        from agents import Agent
        from asteramisk import Server
        from asteramisk.ui import VoiceUI

        agent = Agent(
            name="Bob",
            instructions="Your agent instructions"
        )

        async def call_handler(ui: VoiceUI):
            await ui.answer()
            await ui.connect_openai_agent(agent)

        async def main():
            server = await Server.create()
            await server.register_extension("1234567890", call_handler)
            await server.run_forever()

        if __name__ == "__main__":
            asyncio.run(main())

        :param agent: Agent to connect to
        :param talk_first: Whether to wait for the agent to speak first
        :param model: Model to use, defaults to the OpenAI default
        :param voice: Voice to use, defaults to the OpenAI default
        :param context: An arbitrary mutable object to pass to the agent. it will be available in any tool calls and event hooks
        :return: None
        """
        raise NotImplementedError

    async def disconnect_openai_agent(self) -> None:
        """
        Disconnect any connected OpenAI agent
        :return: None
        """
        raise NotImplementedError

    def has_agent(self) -> bool:
        """
        Check if an OpenAI agent is connected
        :return: True if an OpenAI agent is connected, False otherwise
        """
        return hasattr(self, "_agent_task") and self._agent_task is not None

    async def wait_for_agent(self) -> None:
        """
        Wait for any connected OpenAI agent to finish
        :return: None
        """
        if self.has_agent():
            await self._agent_task

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
        selected = str(selected).strip()
        if selected not in local_callbacks:
            if selected:
                error_text = f"{selected} is not a valid option, please try again."
            else:
                error_text = "You did not select an option, please try again."
            return await self.menu(f"{error_text if error_text not in text else ''}{text}", callbacks, voice_callbacks, text_callbacks)

        # Allow for callbacks with arguments
        if isinstance(local_callbacks[selected], tuple):
            callback, args = local_callbacks[selected]
        else:
            callback = local_callbacks[selected]
            args = ()
        try:
            return await callback(*args)
        except GoBackException:
            # Catch GoBackException from the submenu (callback) and replay this menu, which is the previous menu to the submenu
            return await self.menu(text, callbacks, voice_callbacks, text_callbacks)

    async def select(self, text, options: dict[str, Any] = None, voice_options: dict[str, Any] = None, text_options: dict[str, Any] = None):
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
        selected = str(selected).strip()
        if selected not in local_options:
            if selected:
                error_text = f"{selected} is not a valid option, please try again. "
            else:
                error_text = "You did not select an option, please try again. "
            return await self.select(f"{error_text if error_text not in text else ''}{text}", options, voice_options, text_options)
        return local_options[selected]

    async def choose(self, text, options: list[Any] = None, voice_options: list[Any] = None, text_options: list[Any] = None):
        """
        Present a list of choices to the user
        Returns the selected option
        You can use any type of object as an option, but of course it will be nicer if they have sensible string representations
        Options are automatically converted to strings and are presented as follows:
        For voice UIs:
            For "option_1", press 1.
            For "option_2", press 2.
        For text UIs:
            1. "option_1"
            2. "option_2"
            Reply with the number of the option you want.
        :param text: Text to prompt the user.
        :param options: List of options, like [item_1, item_2, ...]
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
        # Make the prompt string
        if self.ui_type == self.UIType.VOICE:
            prompt = "".join([f"For {option}, press {i+1}. " for i, option in enumerate(local_options)])
        elif self.ui_type == self.UIType.TEXT:
            prompt = "Choose one of the following options:\n"
            prompt += "\n".join([f"{i+1}. {option}" for i, option in enumerate(local_options)])
            prompt += "\nReply with the number of the option you want."
        # Make the options dictionary
        final_options = {str(i+1): option for i, option in enumerate(local_options)}
        # Prompt the user to select an option
        selected = await self.select(prompt, final_options)
        return selected

    async def bridge(self, ui):
        """
        Bridge two UIs together
        Media will flow between the two UIs
        :param ui: The UI to bridge to
        :return: None
        """
        raise NotImplementedError

    async def _run_text_agent(self, agent: Agent, talk_first: bool = True, model: str = None) -> None:
        try:
            if model is None and not agent.model:
                # Use the cheaper mini model rather than the default GPT-4o
                agent.model = config.DEFAULT_GPT_MODEL
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
        finally:
            await sqlite_session.close()

