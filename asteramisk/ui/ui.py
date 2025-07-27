
class UI:
    """
    Base class for all user interfaces
    All user interfaces have these basic methods
    All methods are async
    """
    def __init__(self):
        pass

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

    async def menu(self, text, callbacks: dict[str, callable]):
        """
        Display a menu of options to the user
        :param text: Text to prompt the user, must contain the menu
        :param callbacks: List of callbacks, one for each option
        :return: None. Selected callback will be called
        """
        num_digits = len(str(len(callbacks)))
        digits = await self.gather(text, num_digits)
        if digits not in callbacks:
            return await self.menu("That option is not available, please try again", callbacks, callbacks)
        return await callbacks[digits]()

    async def select(self, text, options):
        """
        Display a list of options to the user
        :param text: Text to prompt the user, must contain the menu
        :param options: List of options
        :return: Selected option
        """
        num_digits = len(str(len(options)))
        digits = await self.gather(text, num_digits)
        if digits not in options:
            return await self.select("That option is not available, please try again", options)

        return options[digits]

