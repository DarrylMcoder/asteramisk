#!/home/pi/venvs/asteramisk/bin/python
from asteramisk import Server
from asteramisk.config import config

import logging
logging.basicConfig(level=logging.DEBUG)

async def call_handler(ui):
    while True:
        await ui.say("Hello, world!")
        await asyncio.sleep(5)

async def main():
    config.ASTERISK_HOST = "127.0.0.1"
    config.ASTERISK_AMI_PORT = 5038
    config.ASTERISK_AMI_USER = "teletools"
    config.ASTERISK_AMI_PASS = "teletoolsDarryl12!"
    config.ASTERISK_ARI_PORT = 8088
    config.ASTERISK_ARI_USER = "teletools"
    config.ASTERISK_ARI_PASS = "teletoolsDarryl12!"
    config.ASTERISK_INCOMING_CALL_CONTEXT = "call-from-darryl"
    config.GOOGLE_APPLICATION_CREDENTIALS = "/home/pi/projects/language/python/teletools/teletools/google-api-key.json"

    server: Server = await Server.create()
    await server.register_extension("500", call_handler=call_handler)
    await server.serve_forever()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
