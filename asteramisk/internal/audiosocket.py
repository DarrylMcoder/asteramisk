import socket
import asyncio
from dataclasses import dataclass
from .audiosocket_connection import AsyncConnection
from asteramisk.internal.async_class import AsyncClass

import logging
logger = logging.getLogger(__name__)

@dataclass
class audioop_struct:
    ratecv_state: None
    rate: int
    channels: int
    ulaw2lin: bool

class AsyncAudiosocket(AsyncClass):
    async def __create__(self, bind_info, timeout=None):
        logger.debug("AsyncAudiosocket.__create__")
        # By default, features of audioop (for example: resampling
        # or re-mixng input/output) are disabled
        self.user_resample = None
        self.asterisk_resample = None

        if not isinstance(bind_info, tuple):
            raise TypeError("Expected tuple (addr, port), received", type(bind_info))
        self.addr, self.port = bind_info
        self.initial_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.initial_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.initial_sock.bind((self.addr, self.port))
        self.initial_sock.settimeout(timeout)
        self.initial_sock.setblocking(False)
        self.initial_sock.listen(100)
        # If the user doesn't specify a port, we use the one we got
        self.port = self.initial_sock.getsockname()[1]

    async def prepare_input(self, inrate=44000, channels=2, ulaw2lin=False):
        self.user_resample = audioop_struct(
            rate=inrate,
            channels=channels,
            ulaw2lin=ulaw2lin,
            ratecv_state=None,
        )

    async def prepare_output(self, outrate=44000, channels=2, ulaw2lin=False):
        self.asterisk_resample = audioop_struct(
            rate=outrate,
            channels=channels,
            ulaw2lin=ulaw2lin,
            ratecv_state=None,
        )

    async def listen(self):
        logger.debug("AsyncAudiosocket.listen")
        loop = asyncio.get_running_loop()
        logger.debug("AsyncAudiosocket.listen: before sock_accept")
        conn, peer_addr = await loop.sock_accept(self.initial_sock)
        logger.debug("AsyncAudiosocket.listen: after sock_accept")
        connection = await AsyncConnection.create(
            conn,
            peer_addr,
            self.user_resample,
            self.asterisk_resample,
        )
        return connection

    async def close(self):
        self.initial_sock.close()
