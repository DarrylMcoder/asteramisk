from typing import Any
from agents import Agent, SQLiteSession, Runner, TContext, RunConfig, RunResultStreaming, OutputGuardrailTripwireTriggered

from contextlib import asynccontextmanager
from asteramisk.config import config
from asteramisk.exceptions import GoBackException, GuardrailTriggeredRecoveryException, InputTimeoutException
from asteramisk.internal.async_class import AsyncClass

import logging
logger = logging.getLogger(__name__)


class _MenuNavigationState:
    def __init__(self):
        self.callback_depth = 0


class UI(AsyncClass):
    """
    Base class for all user interfaces
    All user interfaces have these basic methods
    All methods are async
    """
    class UIType:
        VOICE = "voice"
        TEXT = "text"

    async def __create__(self):
        # DTMF back navigation is meaningful only while a menu callback (or a
        # submenu called by that callback) is active.
        # Keep this in a mutable object so UI wrappers that forward attributes
        # share the same state instead of shadowing an integer locally.
        self._menu_navigation_state = _MenuNavigationState()
        await super().__create__()

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
        .. code-block:: python

            async for user_input in ui.input_stream():
                print(user_input)
        """
        raise NotImplementedError

    async def menu(self, text, callbacks: dict[str, callable] = None, voice_callbacks: dict[str, callable] = None, text_callbacks: dict[str, callable] = None, max_attempts=None):
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
        :param max_attempts: Maximum consecutive no-input prompts before raising InputTimeoutException. None uses config.MAX_NO_INPUT_ATTEMPTS.
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

        # Loop until a valid option is selected
        retry_reason = ""
        no_input_attempts = 0
        max_attempts = config.MAX_NO_INPUT_ATTEMPTS if max_attempts is None else max_attempts
        while True:
            say_text = f"{retry_reason}{text}"
            # Prompt the user to select an option
            # Kinda breaking my style here, but I think we should use digit menus for voice UIs and text menus for text UIs
            if self.ui_type == self.UIType.VOICE:
                num_digits = max([len(str(i)) for i in local_callbacks.keys()])
                selected = await self.gather(say_text, num_digits)
            elif self.ui_type == self.UIType.TEXT:
                selected = await self.prompt(say_text)
            selected = str(selected).strip()
            if not selected:
                no_input_attempts += 1
                if max_attempts is not None and no_input_attempts >= max_attempts:
                    raise InputTimeoutException("No input received for too many consecutive prompts")
            else:
                no_input_attempts = 0
            if selected not in local_callbacks:
                if selected:
                    retry_reason = f"{selected} is not a valid option, please try again."
                else:
                    retry_reason = "You did not select an option, please try again."
                continue
            # Break the loop if a valid option is selected
            break

        # Allow for callbacks with arguments
        if isinstance(local_callbacks[selected], tuple):
            callback, args = local_callbacks[selected]
        else:
            callback = local_callbacks[selected]
            args = ()
        try:
            self._menu_navigation_state.callback_depth += 1
            try:
                result = await callback(*args)
                if self.ui_type == self.UIType.VOICE:
                    await self.done_speaking()
                return result
            finally:
                self._menu_navigation_state.callback_depth -= 1
        except GoBackException:
            # Catch GoBackException from the submenu (callback) and replay this menu, which is the previous menu to the submenu
            return await self.menu(text, callbacks, voice_callbacks, text_callbacks, max_attempts)

    async def select(self, text, options: dict[str, Any] = None, voice_options: dict[str, Any] = None, text_options: dict[str, Any] = None, max_attempts=None):
        """
        Present a list of choices to the user
        :param text: Text to prompt the user, must contain the menu
        :param options: Dictionary of options, like {"1": "Option 1", "2": "Option 2", ...}
        :param voice_options: Same as options, but used only in voice UIs
        :param text_options: Same as options, but used only in text UIs
        :param max_attempts: Maximum consecutive no-input prompts before raising InputTimeoutException. None uses config.MAX_NO_INPUT_ATTEMPTS.
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

        # Loop until a valid option is selected
        retry_reason = ""
        no_input_attempts = 0
        max_attempts = config.MAX_NO_INPUT_ATTEMPTS if max_attempts is None else max_attempts
        while True:
            say_text = f"{retry_reason}{text}"
            # Prompt the user to select an option
            # Kinda breaking my style here, but I think we should use digit menus for voice UIs and text menus for text UIs
            if self.ui_type == self.UIType.VOICE:
                num_digits = max([len(str(i)) for i in local_options.keys()])
                selected = await self.gather(say_text, num_digits)
            elif self.ui_type == self.UIType.TEXT:
                selected = await self.prompt(say_text)
            selected = str(selected).strip()
            if not selected:
                no_input_attempts += 1
                if max_attempts is not None and no_input_attempts >= max_attempts:
                    raise InputTimeoutException("No input received for too many consecutive prompts")
            else:
                no_input_attempts = 0
            if selected not in local_options:
                if selected:
                    retry_reason = f"{selected} is not a valid option, please try again. "
                else:
                    retry_reason = "You did not select an option, please try again. "
                continue
            # Break the loop if a valid option is selected
            break
        return local_options[selected]

    async def choose(self, text, options: list[Any] = None, voice_options: list[Any] = None, text_options: list[Any] = None):
        """
        Present a list of choices to the user
        Returns the selected option
        You can use any type of object as an option, but of course it will be nicer if they have sensible string representations
        Options are automatically converted to strings and are presented as follows:

        * For voice UIs, the user is prompted to press a number for an option.
        * For text UIs, the options are listed with numbers and the user replies with a number.

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

    async def done_speaking(self):
        """
        Wait till the last output (text or audio, depending on the UI type) has finished playing or being sent
        :return: None
        """
        # Do nothing in the base class
        pass

    async def stop_speaking(self):
        """
        Immediately interrupt the current output (text or audio, depending on the UI type)
        :return: None
        """
        # Do nothing by default, only implemented in the voice UI
        pass

    @asynccontextmanager
    async def run_agent(self, agent, talk_first: bool = True, model: str = None, context: TContext = {}):
        """
        Connects the UI to an OpenAI agent (not realtime)
        For better-performing, but more expensive realtime agents, use the run_realtime_agent method instead
        :param agent: The OpenAI agents.Agent to connect to
        :param talk_first: Whether or not to cause the agent to speak first. If False, the agent will wait for the caller to speak first
        :param model: The OpenAI model to use
        :param context: The context to pass to the agent. Will be passed to any tools used by the agent
        :return: An async context manager that returns an async generator
        Use this method almost like you would use the OpenAI realtime agents API

        .. code-block:: python

            from asteramisk.ui import VoiceUI
            from agents import Agent

            async def call_handler(ui: VoiceUI):
                await ui.answer()
                async with ui.run_agent(Agent(...)) as session:
                    async for event in session:
                        pass
        """

        if not isinstance(agent, Agent):
            raise ValueError("agent must be an agents.Agent. To use a realtime agent, use the run_realtime_agent method instead.")

        async def _call_agent_streaming(input, agent: Agent, sqlite_session: SQLiteSession, context: TContext, depth=0):
            # Run the agent on the given input
            try:
                result: RunResultStreaming = Runner.run_streamed(
                    starting_agent=agent,
                    input=input,
                    run_config=RunConfig(model=model),
                    session=sqlite_session,
                    context=context
                )
                sentence = ""
                async for event in result.stream_events():
                    # For voice UIs, we want to stream the agent's response as it comes
                    # For text UIs, we want to wait for the full response before sending it
                    if self.ui_type == self.UIType.VOICE:
                        if event.type == "raw_response_event" and event.data.type == "response.output_text.delta":
                            sentence += event.data.delta
                            logger.info(event.data.delta)
                            if sentence.strip().endswith("."):
                                await self.say(sentence)
                                sentence = ""
                        if event.type == "raw_response_event" and event.data.type == "response.output_text.done":
                            # Make sure to send the last sentence just in case it doesn't end with a period
                            if sentence.strip():
                                await self.say(sentence)
                    elif self.ui_type == self.UIType.TEXT:
                        if event.type == "raw_response_event" and event.data.type == "response.output_text.done":
                            await self.say(event.data.text)
                    yield event

            except OutputGuardrailTripwireTriggered as e:
                logger.warning(f"Agent output guardrail triggered: {e.guardrail_result.output.output_info}")

                # Recursively call the agent again
                # Limit the depth to prevent infinite recursion
                # If the agent is still unable to produce an acceptable response, raise an error
                if depth > 5:
                    raise GuardrailTriggeredRecoveryException("Too many agents.OutputGuardrailTripwireTriggered exceptions. The agent appears unable to produce an acceptable response.") from e

                # Give the agent a chance to correct itself
                await self.stop_speaking()
                error_explanation = f"Agent output guardrail triggered. You sent a response that contains forbidden information. Please identify what you did wrong and correct it in your next response. The following explains the problem: {e.guardrail_result.output.output_info}"
                async for event in _call_agent_streaming(e.guardrail_result.output.output_info, agent, sqlite_session, context, depth + 1):
                    yield event


        async def _gen():
            nonlocal model
            if model is None:
                model = config.DEFAULT_GPT_MODEL

            sqlite_session = SQLiteSession(session_id=self.remote_number)

            try:
                if talk_first:
                    async for event in _call_agent_streaming("New conversation, greet the user.", agent, sqlite_session, context):
                        yield event

                async for transcript in self.input_stream():
                    async for event in _call_agent_streaming(transcript, agent, sqlite_session, context):
                        yield event
            finally:
                sqlite_session.close()

        try:
            # Context manager
            yield _gen()
        finally:
            # Context manager exit
            pass
