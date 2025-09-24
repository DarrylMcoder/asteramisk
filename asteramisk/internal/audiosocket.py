import socket
import asyncio
from contextlib import suppress

from asteramisk.config import config
from asteramisk.internal.async_singleton import AsyncSingleton
from .audiosocket_connection import AudioSocketConnectionAsync

import logging
logger = logging.getLogger(__name__)

class AudiosocketAsync(AsyncSingleton):
    async def __create__(self, bind_addr=config.AUDIOSOCKET_BINDADDR, bind_port=config.AUDIOSOCKET_PORT, timeout=None):
        logger.debug("AsyncAudiosocket.__create__")
        self.connections = {}

        if not bind_addr:
            raise ValueError("No bind address specified for audiosocket. You must specify a bind address, either by setting the AUDIOSOCKET_BINDADDR environment variable, setting config.AUDIOSOCKET_BINDADDR, or by passing it as a parameter to the constructor.")

        if not bind_port:
            raise ValueError("No bind port specified for audiosocket. You must specify a bind port, either by setting the AUDIOSOCKET_PORT environment variable, setting config.AUDIOSOCKET_PORT, or by passing it as a parameter to the constructor.")

        self.addr = bind_addr
        self.port = int(bind_port)

        self.initial_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.initial_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.initial_sock.bind((self.addr, self.port))
        except OSError as e:
            raise OSError(f"Failed to bind audiosocket to {self.addr}:{self.port}: {e}")
        self.initial_sock.settimeout(timeout)
        self.initial_sock.setblocking(False)
        self.initial_sock.listen(100)
        # If the user doesn't specify a port, we use the one we got
        self.port = self.initial_sock.getsockname()[1]
        # Start the listening loop
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        logger.debug("AsyncAudiosocket._listen_loop")
        while True:
            audconn = await self.listen()
            logger.debug("AsyncAudiosocket._listen_loop: audconn created")
            stream_id = await audconn.get_uuid()
            self.connections[stream_id] = audconn
            logger.debug(f"AsyncAudiosocket._listen_loop: added connection {stream_id}")

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
            peer_addr
        )
        return connection

    async def close(self):
        if self._listen_task:
            self._listen_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._listen_task
            self._listen_task = None
        self.initial_sock.close()
