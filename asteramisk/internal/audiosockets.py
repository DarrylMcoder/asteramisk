import uuid
import struct
import socket
import asyncio
from asteramisk.internal.async_class import AsyncClass

import logging
logger = logging.getLogger(__name__)

class AudioSocketException(Exception):
    pass

class AudioPacket:
    class TYPES:
        HANGUP = 0x00 # Sent to hang up the call
        UUID = 0x01   # Payload will contain the UUID (16 byte binary representation) for the audio stream
        DTMF = 0x03   # Payload is one byte (ascii) DTMF digit
        AUDIO = 0x10  # Payload is signed linear, 16 bit, 8kHz, mono PCM (little endian)
        ERROR = 0xFF  # Error has occurred; payload is the (optional) application specific error code

    def __init__(self, data_type: int, length: int=None, data: bytes=b''):
        self.type = data_type
        self.length = length
        self.data = data

    def __repr__(self):
        return f"AudioPacket(type={self.type}, length={self.length}, data={self.data})"

    @classmethod
    async def read_from(cls, reader: asyncio.StreamReader):
        logger.debug("Reading audio packet")
        type_bytes = await reader.readexactly(1)
        logger.debug(f"Audio packet type: {type_bytes}")
        packet_type = int.from_bytes(type_bytes, 'big', signed=False)
        # Length is 16 bit unsigned integer (big endian)
        length_bytes = await reader.readexactly(2)
        logger.debug(f"Audio packet length: {length_bytes}")
        packet_length = int.from_bytes(length_bytes, 'big', signed=False)
        packet_data = await reader.readexactly(packet_length)
        packet = cls(packet_type, packet_length, packet_data)
        return packet

    async def write_to(self, writer: asyncio.StreamWriter):
        logger.debug("Writing audio packet")
        type_bytes = self.type.to_bytes(1, 'big', signed=False)
        logger.debug(f"Audio packet type: {type_bytes}")
        writer.write(type_bytes)
        length_bytes = struct.pack('>H', self.length)
        logger.debug(f"Audio packet length: {length_bytes}")
        writer.write(length_bytes)
        writer.write(self.data)
        await writer.drain()


class AudioSocket(AsyncClass):
    async def __create__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self.rx_queue = asyncio.Queue()
        self.tx_queue = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._process_task = asyncio.create_task(self._process())
        self.stream_id = None
        self.connected = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _process(self):
        logger.info("_process: Audio processing started")
        while True:
            # Try to send a packet every 20ms
            # If the queue is empty, send some silence
            async with self._lock:
                rx_packet = await AudioPacket.read_from(self._reader)
            if rx_packet.type == AudioPacket.TYPES.HANGUP:
                logger.info("Audio connection hangup")
                self.connected = False
                break
            elif rx_packet.type == AudioPacket.TYPES.DTMF:
                await self.on_dtmf(rx_packet.data.decode('ascii'))
            elif rx_packet.type == AudioPacket.TYPES.UUID:
                logger.info(f"Audio connection with UUID {rx_packet.data}")
                self.stream_id = str(uuid.UUID(bytes=rx_packet.data))
            elif rx_packet.type == AudioPacket.TYPES.AUDIO:
                if self.rx_queue.full():
                    logger.warning("Audio queue is full, dropping packet")
                await self.rx_queue.put(rx_packet.data)
            elif rx_packet.type == AudioPacket.TYPES.ERROR:
                logger.error(f"Audio connection error: {rx_packet.data}")
            else:
                logger.error(f"Audio connection unknown packet type: {rx_packet.type}")

            if self.tx_queue.empty():
                tx_packet = AudioPacket(AudioPacket.TYPES.AUDIO, 0, b'')
            else:
                tx_packet = await self.tx_queue.get()
            async with self._lock:
                await tx_packet.write_to(self._writer)
            # Wait 20ms before sending the next packet
            await asyncio.sleep(0.02)

    async def receive_packet(self):
        return await self.rx_queue.get()

    async def send_packet(self, packet):
        await self.tx_queue.put(packet)

    async def read(self):
        """
        Read audio data from the socket
        :return: One packet of audio data
        """
        while True:
            packet = await self.receive_packet()
            if packet.type == AudioPacket.TYPES.ERROR:
                logger.error("Audio packet error: %s", packet.data)
            elif packet.type == AudioPacket.TYPES.AUDIO:
                return packet.data

    async def write(self, data):
        await self.send_packet(AudioPacket(AudioPacket.TYPES.AUDIO, len(data), data))

    async def send_hangup(self):
        await self.send_packet(AudioPacket(AudioPacket.TYPES.HANGUP))

    async def send_dtmf(self, dtmf):
        await self.send_packet(AudioPacket(AudioPacket.TYPES.DTMF, len(dtmf), dtmf))

    async def send_audio(self, audio_data):
        await self.send_packet(AudioPacket(AudioPacket.TYPES.AUDIO, len(audio_data), audio_data))

    async def close(self):
        await self.send_hangup()
        self._writer.close()
        await self._writer.wait_closed()

class AudioSocketServer(AsyncClass):
    async def __create__(self, host, port):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        self.socket.bind((host, port))
        self.socket.listen(5)
        self.server = await asyncio.start_server(self._handle_connection, sock=self.socket)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        packstr = b'\x10\x02\x39\x39\x39\x39\x39\x39\x39\x39\x39\x39\x39\x39\x39'
        writer.write(packstr)
        await writer.drain()
        logger.info("Audio packet sent")
        while True:
            logger.info("Sleeping")
            await asyncio.sleep(10)
        logger.info("_handle_connection")
        packet = AudioPacket(AudioPacket.TYPES.AUDIO, 320, b'\x00' * 320)
        await packet.write_to(writer)
        logger.info("Audio packet sent")
        socket = await AudioSocket.create(reader, writer)
        while True:
            logger.info("Sleeping")
            await asyncio.sleep(10)

    async def serve_forever(self):
        logger.info(f"Audio server listening on {self.server.sockets[0].getsockname()}")
        await self.server.serve_forever()

    async def accept(self, stream_id):
        pass

    async def close(self):
        self.server.close()
        await self.server.wait_closed()
