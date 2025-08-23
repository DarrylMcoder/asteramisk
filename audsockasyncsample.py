import socket
import asyncio
from asteramisk.internal.audiosocket import AsyncAudiosocket, AsyncConnection

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Example usage for echo server with async connection handling
async def main():
    server = await AsyncAudiosocket.create(('0.0.0.0', 51001))
    while True:
        conn = await server.listen()
        logger.debug("New connection. Creating task")
        asyncio.create_task(handle_connection(conn))

async def handle_connection(conn):
    logger.debug("handle_connection")
    logger.info(f"Received connection with UUID {await conn.get_uuid()}")
    while conn.connected:
        data = await conn.read()
        await conn.write(data)

if __name__ == "__main__":
    asyncio.run(main())
