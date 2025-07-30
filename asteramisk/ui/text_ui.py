from typing import Any
from asteramisk.config import config
from asteramisk.internal.message_broker import MessageBroker
from .ui import UI
from .voice_ui import VoiceUI

class TextUI(UI):
    def __init__(self, recipient_number, our_callerid_number=config.SYSTEM_PHONE_NUMBER, our_callerid_name=config.SYSTEM_NAME):
        self._broker = MessageBroker(our_callerid_number)
        self._recipient_number = recipient_number
        self._our_callerid_number = our_callerid_number
        self._our_callerid_name = our_callerid_name
        super().__init__()

    @property
    def ui_type(self):
        return self.UIType.TEXT
    
    async def answer(self):
        """ \"Answer\" the call. Simply for compatibility with other UIs. Does nothing on TextUI. """
        pass

    async def hangup(self):
        """ \"Hangup\" the call. Simply for compatibility with other UIs. Does nothing on TextUI. """
        pass
    
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
        return await self.prompt(message)


