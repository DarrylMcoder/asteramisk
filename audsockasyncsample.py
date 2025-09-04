import asyncio
from asteramisk.internal.audiosocket import AudiosocketAsync

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Example usage for echo server with async connection handling
async def main():
    server = await AudiosocketAsync.create(bind_addr="0.0.0.0", bind_port=51001)
    while True:
        conn = await server.accept()
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
