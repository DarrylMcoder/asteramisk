import datetime
import aiofiles
import traceback
from typing import Literal
from asteramisk.communicator import Communicator
from asteramisk.ui import VoiceUI, TextUI
from asteramisk.config import config

async def notify(notification: str, recipient_number: str = config.ADMIN_PHONE_NUMBER, contact_method: Literal["call", "text"] = "call"):
    async with await Communicator.create() as communicator:
        ui: VoiceUI | TextUI = await communicator.make_conversation(recipient_number=recipient_number, contact_method=contact_method)
        await ui.say(notification)
        await ui.hangup()

async def notify_error(error: str, recipient_number: str = config.ADMIN_PHONE_NUMBER, contact_method: Literal["call", "text"] = "call"):
    await notify(f"An error has occurred on system {config.SYSTEM_NAME}. Please listen carefully to the following message. {error}", recipient_number, contact_method)

async def notify_exception(exception: Exception, recipient_number: str = config.ADMIN_PHONE_NUMBER, contact_method: Literal["call", "text"] = "call"):
    datefilename = datetime.datetime.now().strftime("%Y-%m-%d") + ".log"
    async with aiofiles.open(f"{config.LOG_DIR}/{datefilename}", "w") as f:
        await f.write(traceback.format_exc())
    await notify(f"An exception has occurred on system {config.SYSTEM_NAME}. Please listen carefully to the following message. {exception}. The full traceback has been logged to {config.LOG_DIR}/{datefilename}.", recipient_number, contact_method)
