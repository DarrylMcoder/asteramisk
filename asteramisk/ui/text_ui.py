from asteramisk.config import config
from asteramisk.internal.message_broker import MessageBroker
from .ui import UI

class TextUI(UI):
    def __init__(self, recipient_number, our_callerid_number=config.SYSTEM_PHONE_NUMBER, our_callerid_name=config.SYSTEM_NAME):
        self._broker = MessageBroker(our_callerid_number)
        self._recipient_number = recipient_number
        self._our_callerid_number = our_callerid_number
        self._our_callerid_name = our_callerid_name
        super().__init__()

    async def answer(self):
        pass

    async def hangup(self):
        pass
    
    async def say(self, text):
        await self._broker.send_message(self._recipient_number, text)

    async def prompt(self, text):
        return await self._broker.send_receive(self._recipient_number, text)

    async def gather(self, text, num_digits):
        digits: str = await self.prompt(text)
        if len(digits) != num_digits:
            return await self.gather(f"Please enter {num_digits} digits", num_digits)
        if not digits.isdigit():
            return await self.gather(f"Please enter {num_digits} digits", num_digits)
        return digits

    async def ask_yes_no(self, text):
        message = f"{text} (yes/no)"
        return await self.prompt(message)

