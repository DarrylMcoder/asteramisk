from panoramisk.fast_agi import Request
from .agi import AsteriskGatewayInterface

import logging
logger = logging.getLogger(__name__)

class SyncAsteriskGatewayInterface(AsteriskGatewayInterface):
    """
    Synchronous AGI interface
    Fully compatible and interchangeable with the asynchronous AGI interface
    """
    async def __create__(self, request: Request):
        self._request = request
        await super().__create__()

    @property
    def channel(self):
        return self._request.headers['agi_channel']

    async def send_command(self, command: str) -> str:
        """ Sends AGI command to Asterisk PBX """
        return await self._request.send_command(command)

