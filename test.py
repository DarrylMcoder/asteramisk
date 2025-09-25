#!/home/pi/venvs/asteramisk/bin/python
from asteramisk import Server
from asteramisk.config import config

import logging
logging.basicConfig(level=logging.INFO)

async def call_handler():
    print("call handler")

async def main():
    config.ASTERISK_HOST = "127.0.0.1"
    config.ASTERISK_AMI_PORT = 5038
    config.ASTERISK_AMI_USER = "teletools"
    config.ASTERISK_AMI_PASS = "teletoolsDarryl12!"
    config.ASTERISK_ARI_PORT = 8088
    config.ASTERISK_ARI_USER = "teletools"
    config.ASTERISK_ARI_PASS = "teletoolsDarryl12!"

    server: Server = await Server.create()
    await server.register_extension("500", call_handler=call_handler)
    await server.register_extension("501", call_handler=call_handler)
    await server.register_extension("502", call_handler=call_handler)
    await server.register_extension("503", call_handler=call_handler)
    await server.serve_forever()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
