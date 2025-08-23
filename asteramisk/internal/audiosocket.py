import socket
import asyncio
from dataclasses import dataclass
from .audiosocket_connection import AudioSocketConnectionAsync
from asteramisk.internal.async_singleton import AsyncSingleton
from asteramisk.config import config

import logging
logger = logging.getLogger(__name__)

@dataclass
class audioop_struct:
    ratecv_state: None
    rate: int
    channels: int
    ulaw2lin: bool

class AudiosocketAsync(AsyncSingleton):
    async def __create__(self, bind_addr=config.AUDIOSOCKET_BINDADDR, bind_port=config.AUDIOSOCKET_PORT, timeout=None):
        logger.debug("AsyncAudiosocket.__create__")
        # By default, features of audioop (for example: resampling
        # or re-mixng input/output) are disabled
        self.user_resample = None
        self.asterisk_resample = None
        self.connections = {}

        if not bind_addr:
            raise ValueError("No bind address specified for audiosocket. You must specify a bind address, either by setting the AUDIOSOCKET_BINDADDR environment variable, setting config.AUDIOSOCKET_BINDADDR, or by passing it as a parameter to the constructor.")

        if not bind_port:
            raise ValueError("No bind port specified for audiosocket. You must specify a bind port, either by setting the AUDIOSOCKET_PORT environment variable, setting config.AUDIOSOCKET_PORT, or by passing it as a parameter to the constructor.")

        self.addr = bind_addr
        self.port = int(bind_port)

        self.initial_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.initial_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.initial_sock.bind((self.addr, self.port))
        self.initial_sock.settimeout(timeout)
        self.initial_sock.setblocking(False)
        self.initial_sock.listen(100)
        # If the user doesn't specify a port, we use the one we got
        self.port = self.initial_sock.getsockname()[1]
        # Start the listening loop
        asyncio.create_task(self._listen_loop())

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

    async def _listen_loop(self):
        try:
            logger.debug("AsyncAudiosocket._listen_loop")
            while True:
                audconn = await self.listen()
                logger.debug("AsyncAudiosocket._listen_loop: audconn created")
                stream_id = await audconn.get_uuid()
                self.connections[stream_id] = audconn
                logger.debug(f"AsyncAudiosocket._listen_loop: added connection {stream_id}")
        except Exception as e:
            logger.error(f"AsyncAudiosocket._listen_loop error: {e}")

    async def accept(self, stream_id):
        logger.debug(f"AsyncAudiosocket.accept: waiting for connection {stream_id}")
        while stream_id not in self.connections:
            logger.debug(f"AsyncAudiosocket.accept: waiting for connection {stream_id}")
            await asyncio.sleep(0.1)
        return self.connections[stream_id]

    async def listen(self):
        logger.debug("AsyncAudiosocket.listen")
        loop = asyncio.get_running_loop()
        logger.debug("AsyncAudiosocket.listen: before sock_accept")
        conn, peer_addr = await loop.sock_accept(self.initial_sock)
        logger.debug("AsyncAudiosocket.listen: after sock_accept")
        connection = await AudioSocketConnectionAsync.create(
            conn,
            peer_addr,
            self.user_resample,
            self.asterisk_resample,
        )
        return connection

    async def close(self):
        self.initial_sock.close()
