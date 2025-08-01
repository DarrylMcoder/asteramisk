from typing import Any

import logging
logger = logging.getLogger(__name__)

class UI:
    """
    Base class for all user interfaces
    All user interfaces have these basic methods
    All methods are async
    """
    class UIType:
        VOICE = "voice"
        TEXT = "text"

    def __init__(self):
        pass

    @property
    def ui_type(self):
        raise NotImplementedError("Subclasses must implement this method")

    async def _unique_id(self):
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

    async def prompt(self, text) -> str:
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
