import uuid
import aioari
import asyncio
from asteramisk.internal.audiosocket import AudiosocketAsync
from asteramisk.internal.audiosocket_connection import AudioSocketConnectionAsync

class Test:
    async def stasis_start_cb(self, objs, event):
        print(f"StasisStart on {objs['channel'].json['name']}")
        await self.bridge.addChannel(channel=objs['channel'].id)

    async def test(self):
        await asyncio.sleep(2)
        channel = await self.ari.channels.originate(
            endpoint="PJSIP/darryl",
            app="test"
        )
        stream_id = str(uuid.uuid4())
        """
        external_media_channel = await self.ari.channels.originate(
            endpoint=f"AudioSocket/127.0.0.1:51001/{stream_id}/c(slin16)",
            #endpoint="PJSIP/2266403322@voipms_endpoint",
            callerId="5195899829",
            app="test"
        )
        """

        stream_id = str(uuid.uuid4())

        external_media_channel: aioari.model.Channel = await self.ari.channels.externalMedia(
            external_host=f"127.0.0.1:51001",
            encapsulation="audiosocket",
            app="test",
            transport="tcp",
            format="slin",
            data=stream_id
        )

        print("External media channel created")
        print(external_media_channel.json)

        self.bridge = await self.ari.bridges.create(
            type="mixing",
        )
        await self.bridge.addChannel(channel=external_media_channel.id)

        channel.on_event("StasisStart", self.stasis_start_cb)

        audconn: AudioSocketConnectionAsync = await self.audio_socket.accept(stream_id)
        print("Audio connection accepted")
        while audconn.connected:
            data = await audconn.read()
            await audconn.write(data)

    async def main(self):
        self.ari = await aioari.connect(
            "http://127.0.0.1:8088",
            "teletools",
            "teletoolsDarryl12!"
        )

        self.audio_socket = await AudiosocketAsync.create(bind_addr="0.0.0.0", bind_port=51001)

        asyncio.create_task(self.test())
        await self.ari.run(
            apps=[
                "test"
            ]
        )




if __name__ == "__main__":
    asyncio.run(Test().main())
