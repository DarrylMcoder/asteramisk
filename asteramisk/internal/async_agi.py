import asyncio
from panoramisk.actions import Action
from panoramisk.fast_agi import parse_agi_result

from asteramisk.exceptions import AGIException
from .agi import AsteriskGatewayInterface

class AsyncAsteriskGatewayInterface(AsteriskGatewayInterface):
    """ 
    Asynchronous AGI interface
    Fully compatible and interchangeable with the synchronous AGI interface
    :param channel: Channel name. The channel must already have been put into Async AGI mode via AGI(agi:async) in the dialplan or AMI command
    """
    async def __create__(self, channel):
        self._channel = channel
        super().__create__()

    @property
    def channel(self):
        return self._channel

    async def send_command(self, command):
        """ Sends AGI command """
        # This function is called by all the others so we need to make sure the manager is connected here
        result_event = asyncio.Event()
        result = None

        def agi_exec_event_callback(manager, event):
            nonlocal result
            result = parse_agi_result(event['Result'])
            result_event.set()

        action = Action({
            "Action": "AGI",
            "Channel": self.channel,
            "Command": command
        })
        await self._manager.send_action(action)
        self._manager.register_event("AsyncAGIExec", agi_exec_event_callback)
        await result_event.wait()
        if 'error' in result and 'msg' in result:
            raise AGIException(result['msg'])
        return result

