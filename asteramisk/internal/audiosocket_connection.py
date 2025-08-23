import uuid
import audioop
import asyncio
from contextlib import suppress
from dataclasses import dataclass
from asteramisk.internal.async_class import AsyncClass

import logging
logger = logging.getLogger(__name__)

# A sort of imitation struct that holds all of the possible
# AudioSocket message types

@dataclass(frozen=True)
class types_struct:
  uuid:    bytes = b'\x01'   # Message payload contains UUID set in Asterisk Dialplan
  audio:   bytes = b'\x10'   # * Message payload contains 8Khz 16-bit mono LE PCM audio (* See Github readme)
  silence: bytes = b'\x02'   # Message payload contains silence (I've never seen this occur personally)
  dtmf:    bytes = b'\x03'   # Message payload is 1 byte (ascii) DTMF digit
  hangup:  bytes = b'\x00'   # Tell Asterisk to hangup the call (This doesn't appear to ever be sent from Asterisk to us)
  error:   bytes = b'\xff'   # Message payload contains an error from Asterisk

types = types_struct()


# The size of 20ms of 8KHz 16-bit mono LE PCM represented as a
# 16 bit (2 byte, size of length header) unsigned BE integer

# This amount of the audio data mentioned above is equal
# to 320 bytes, which is the required payload size when
# sending audio back to AudioSocket for playback on the
# bridged channel. Sending more or less data will result in distorted sound
PCM_SIZE = (320).to_bytes(2, 'big')


# Similar to one above, this holds all the possible
# AudioSocket related error codes Asterisk can send us

@dataclass(frozen=True)
class errors_struct:
  none:   bytes = b'\x00'
  hangup: bytes = b'\x01'
  frame:  bytes = b'\x02'
  memory: bytes = b'\x04'

errors = errors_struct()

class AudioSocketConnectionAsync(AsyncClass):
    async def __create__(self, conn, peer_addr, user_resample, asterisk_resample):
        logger.debug("AsyncConnection.__create__")
        self.conn = conn
        self.peer_addr = peer_addr
        self._uuid = None
        self.connected = True
        self._user_resample = user_resample
        self._asterisk_resample = asterisk_resample
        self._rx_q = asyncio.Queue(500)
        self._tx_q = asyncio.Queue(500)
        self._lock = asyncio.Lock()
        self._event_callbacks = {}
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._process())

    def on(self, event, callback):
        # Ensure that the event exists in types_struct
        if event not in ['uuid', 'dtmf', 'error']:
            raise ValueError(f"Trying to register an invalid event: {event}")

        self._event_callbacks[event] = callback

    async def get_uuid(self):
        while self._uuid is None:
            logger.debug("AsyncConnection.get_uuid: waiting for uuid")
            await asyncio.sleep(0.1)
        return self._uuid

    async def clear_send_queue(self):
        """Clear the send queue. Cancels any audio that is currently being sent"""
        logger.debug("AsyncConnection.clear_send_queue")
        async def clear():
            while True:
                try:
                    await asyncio.wait_for(self._tx_q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    break
        asyncio.create_task(clear())

    async def clear_receive_queue(self):
        """Clear the receive queue. Discards any audio that has been received but not yet read"""
        logger.debug("AsyncConnection.clear_receive_queue")
        async def clear():
            while True:
                try:
                    await asyncio.wait_for(self._rx_q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    break
        asyncio.create_task(clear())

    async def drain_send_queue(self):
        logger.debug("AsyncConnection.drain_send_queue")
        await self._tx_q.join()

    def _split_data(self, data):
        if len(data) < 3:
            print('[AUDIOSOCKET WARNING] The data received was less than 3 bytes, ' +
                  'the minimum length data from Asterisk AudioSocket should be.')
            return b'\x00', 0, bytes(320)
        else:
            return data[:1], int.from_bytes(data[1:3], 'big'), data[3:]

    def _decode_error(self, payload):
        if payload == errors.none:
            print('[ASTERISK ERROR] No error code present')
        elif payload == errors.hangup:
            print('[ASTERISK ERROR] The called party hungup')
        elif payload == errors.frame:
            print('[ASTERISK ERROR] Failed to forward frame')
        elif payload == errors.memory:
            print('[ASTERISK ERROR] Memory allocation error')
        return

    async def read(self):
        try:
            audio = await asyncio.wait_for(self._rx_q.get(), timeout=0.2)
            if len(audio) != 320:
                audio += bytes(320 - len(audio))
        except asyncio.TimeoutError:
            return bytes(320)
        if self._asterisk_resample:
            if self._asterisk_resample.ulaw2lin:
                audio = audioop.ulaw2lin(audio, 2)
            if self._asterisk_resample.rate != 8000:
                audio, self._asterisk_resample.ratecv_state = audioop.ratecv(
                    audio,
                    2,
                    1,
                    8000,
                    self._asterisk_resample.rate,
                    self._asterisk_resample.ratecv_state,
                )
            if self._asterisk_resample.channels == 2:
                audio = audioop.tostereo(audio, 2, 1, 1)
        return audio

    async def write(self, audio):
        logger.debug("AsyncConnection.write")
        if self._user_resample:
            if self._user_resample.ulaw2lin:
                audio = audioop.ulaw2lin(audio, 2)
            if self._user_resample.rate != 8000:
                audio, self._user_resample.ratecv_state = audioop.ratecv(
                    audio,
                    2,
                    self._user_resample.channels,
                    self._user_resample.rate,
                    8000,
                    self._user_resample.ratecv_state,
                )
            if self._user_resample.channels == 2:
                audio = audioop.tomono(audio, 2, 1, 1)
        # If the audio data is greater than 320 bytes, write it in 320 byte chunks
        if len(audio) > 320:
            for i in range(0, len(audio), 320):
                await self._tx_q.put(audio[i : i + 320])
        else:
            await self._tx_q.put(audio)

    async def hangup(self):
        logger.debug("AsyncConnection.hangup")
        async with self._lock:
            await self._loop.sock_sendall(self.conn, types.hangup * 3)
        await asyncio.sleep(0.2)
        await self.close()

    async def _process(self):
        logger.debug("AsyncConnection._process")
        try:
            while self.connected:
                data = None
                try:
                    data = await self._loop.sock_recv(self.conn, 323)
                except (ConnectionResetError, asyncio.TimeoutError):
                    pass
                if not data:
                    self.connected = False
                    await self.close()
                    break
                type_byte, length, payload = self._split_data(data)
                if type_byte == types.audio:
                    if self._rx_q.full():
                        print('[AUDIOSOCKET WARNING] The inbound audio queue is full! This most ' +
                              'likely occurred because the read() method is not being called, dropping oldest frame')
                        self._rx_q.get_nowait()
                    await self._rx_q.put(payload)
                    if self._tx_q.empty():
                        async with self._lock:
                            await self._loop.sock_sendall(self.conn, types.audio + PCM_SIZE + bytes(320))
                    else:
                        audio_data = await self._tx_q.get()
                        audio_data = audio_data[:320]
                        async with self._lock:
                            await self._loop.sock_sendall(self.conn, types.audio + len(audio_data).to_bytes(2, 'big') + audio_data)
                        self._tx_q.task_done()
                elif type_byte == types.dtmf:
                    logger.debug(f"AsyncConnection._process DTMF: {payload}")
                    if 'dtmf' in self._event_callbacks:
                        asyncio.create_task(self._event_callbacks['dtmf'](payload))
                elif type_byte == types.error:
                    logger.debug(f"AsyncConnection._process ERROR: {payload}")
                    if 'error' in self._event_callbacks:
                        asyncio.create_task(self._event_callbacks['error'](payload))
                    self._decode_error(payload)
                elif type_byte == types.uuid:
                    logger.debug(f"AsyncConnection._process UUID: {payload}")
                    if 'uuid' in self._event_callbacks:
                        asyncio.create_task(self._event_callbacks['uuid'](payload))
                    self._uuid = str(uuid.UUID(bytes=payload))
        except Exception as e:
            logger.exception(f"AsyncConnection._process error: {e}")
        finally:
            await self.close()

    async def close(self):
        self.connected = False
        if self.conn:
            self.conn.close()
        if hasattr(self, '_task'):
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
