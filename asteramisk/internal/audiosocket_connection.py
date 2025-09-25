import uuid
import asyncio
from contextlib import suppress
from dataclasses import dataclass

from asteramisk.exceptions import InvalidStateException
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
    async def __create__(self, conn, peer_addr):
        logger.debug("AsyncConnection.__create__")
        self.conn = conn
        self.peer_addr = peer_addr
        self._uuid = None
        self.connected = True
        self.is_closing = False
        self._rx_q = asyncio.Queue(500)
        self._tx_q = asyncio.Queue(500)
        self._from_asterisk_resample_factor = 1
        self._to_asterisk_resample_factor = 1
        self._from_asterisk_resampler = None
        self._to_asterisk_resampler = None
        self._tx_extra_data = b''
        self._lock = asyncio.Lock()
        self._to_asterisk_resampler_lock = asyncio.Lock()
        self._from_asterisk_resampler_lock = asyncio.Lock()
        self._event_callbacks = {}
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._process())

    def on(self, event, callback):
        # Ensure that the event exists in types_struct
        if event not in ['uuid', 'dtmf', 'error']:
            raise ValueError(f"Trying to register an invalid event: {event}")

        self._event_callbacks[event] = callback

    async def set_resampling(self, rate, channels, audio_format):
        """
        Set the resampling factors for your end of the connection.
        Asterisk's end cannot be changed.
        Use this method to start automatically resampling audio that is written to your end of the connection
        If not used, audio will be sent as-is, which may not be what asterisk expects
        :param rate: Audio sample rate at your end of the connection
        :param channels: Audio channels at your end of the connection
        :param audio_format: Audio format at your end of the connection
        :return: None
        """
        self._from_asterisk_resample_factor = rate / 8000
        self._to_asterisk_resample_factor = 8000 / rate

        # Start the resampling tasks
        self._rx_resample_task = asyncio.create_task(self._rx_resample(rate, channels, audio_format))
        self._tx_resample_task = asyncio.create_task(self._tx_resample(rate, channels, audio_format))

    async def stop_resampling(self):
        logger.debug("AsyncConnection.stop_resampling")
        if hasattr(self, '_rx_resample_task') and self._rx_resample_task is not None:
            self._rx_resample_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._rx_resample_task
        if hasattr(self, '_tx_resample_task') and self._tx_resample_task is not None:
            self._tx_resample_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._tx_resample_task
        logger.debug("AsyncConnection.stop_resampling: done")

    async def get_uuid(self):
        while self._uuid is None:
            logger.debug("AsyncConnection.get_uuid: waiting for uuid")
            await asyncio.sleep(0.1)
        return self._uuid

    async def clear_send_queue(self):
        """Clear the send queue. Cancels any audio that is currently being sent"""
        logger.debug("AsyncConnection.clear_send_queue")
        while True:
            try:
                await asyncio.wait_for(self._tx_q.get(), timeout=0.5)
                self._tx_q.task_done()
            except asyncio.TimeoutError:
                break

    async def clear_receive_queue(self):
        """Clear the receive queue. Discards any audio that has been received but not yet read"""
        logger.debug("AsyncConnection.clear_receive_queue")
        while True:
            try:
                await asyncio.wait_for(self._rx_q.get(), timeout=0.2)
                self._rx_q.task_done()
            except asyncio.TimeoutError:
                break

    async def drain_send_queue(self):
        logger.debug("AsyncConnection.drain_send_queue")
        # If the connection is closed, return immediately
        if not self.connected:
            logger.debug("AsyncConnection.drain_send_queue: connection is closed, nothing to drain")
            return
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
            logger.error('[ASTERISK ERROR] No error code present')
        elif payload == errors.hangup:
            logger.error('[ASTERISK ERROR] The called party hungup')
        elif payload == errors.frame:
            logger.error('[ASTERISK ERROR] Failed to forward frame')
        elif payload == errors.memory:
            logger.error('[ASTERISK ERROR] Memory allocation error')
        return

    async def _stop_process(self, process):
        # Send EOF to the process, and wait for stdin to close
        process.stdin.close()
        await process.stdin.wait_closed()

        # Read to EOF from stdout so that it won't get stuck
        _ = await process.stdout.read()
        
        # Try to terminate the process gracefully
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            # If the process is still running, kill it forcibly
            process.kill()
            await process.wait()

    async def _rx_resample(self, rate, channels, audio_format):
        logger.debug("AsyncConnection._rx_resample_task")
        # Create the resampler: an ffmpeg process
        self._from_asterisk_resampler = await asyncio.create_subprocess_exec(
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-fflags', '+flush_packets',
            '-f', 's16le',
            '-ar', '8000', # Asterisk end fixed to 8KHz
            '-ac', '1', # Asterisk end fixed to mono
            '-i', 'pipe:0',
            '-f', 's16le',
            '-ar', str(rate),
            '-ac', str(channels),
            'pipe:1',
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE
        )
        try:
            while self.connected:
                audio = await self._rx_q.get()
                self._from_asterisk_resampler.stdin.write(audio)
                await self._from_asterisk_resampler.stdin.drain()
                self._rx_q.task_done()
        finally:
            # Clean up the resources we use in this task
            await self._stop_process(self._from_asterisk_resampler)
            self._from_asterisk_resampler = None
            logger.debug("AsyncConnection._rx_resample_task: done")

    async def _tx_resample(self, rate, channels, audio_format):
        logger.debug("AsyncConnection._tx_resample_task")
        # Create the resampler: an ffmpeg process
        self._to_asterisk_resampler = await asyncio.create_subprocess_exec(
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-fflags', '+flush_packets',
            '-f', 's16le',
            '-ar', str(rate),
            '-ac', str(channels),
            '-i', 'pipe:0',
            '-f', 's16le',
            '-ar', '8000', # Asterisk end fixed to 8KHz
            '-ac', '1', # Asterisk end fixed to mono
            'pipe:1',
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE
        )
        try:
            while self.connected:
                audio = await self._to_asterisk_resampler.stdout.read(320)
                await self._write_to_tx_queue(audio)
        finally:
            # Clean up the resources we use in this task
            await self._stop_process(self._to_asterisk_resampler)
            self._to_asterisk_resampler = None
            logger.debug("AsyncConnection._tx_resample_task: done")

    async def _write_to_tx_queue(self, audio):
        """
        Write audio to the send queue, chunkify it if it is greater than 320 bytes
        """
        # Add the extra data from last time
        audio = self._tx_extra_data + audio
        self._tx_extra_data = b''
        # If the audio data is greater than 320 bytes, write it in 320 byte chunks
        if len(audio) > 320:
            for i in range(0, len(audio), 320):
                chunk = audio[i : i + 320]
                if len(chunk) == 320:
                    await self._tx_q.put(chunk)
                elif len(chunk) < 320:
                    self._tx_extra_data = chunk
                    break
                else:
                    raise ValueError("Audio chunk is greater than 320 bytes")
        elif len(audio) < 320:
            self._tx_extra_data = audio
        else:
            await self._tx_q.put(audio)

    async def read(self):
        """
        Read audio from the receive queue
        If the connection is resampled, read from the resampled queue
        If the connection is not resampled, read from the original queue
        :return: Audio data
        """
        #logger.debug("AsyncConnection.read")
        if not self.connected:
            raise InvalidStateException("Unable to read audio. Connection is not connected")
        if self._from_asterisk_resampler:
            async with self._from_asterisk_resampler_lock:
                bytes_to_read = int(320 * self._from_asterisk_resample_factor)
                return await self._from_asterisk_resampler.stdout.read(bytes_to_read)
        else:
            audio = await self._rx_q.get()
            self._rx_q.task_done()
            return audio

    async def write(self, data):
        """
        Write audio to the send queue
        If the connection is resampled, write to the resampled queue
        If the connection is not resampled, write to the original queue
        :param data: Audio data
        :return: None
        """
        logger.debug("AsyncConnection.write")
        if not self.connected:
            raise InvalidStateException("Unable to write audio. Connection is not connected")
        if self._to_asterisk_resampler:
            async with self._to_asterisk_resampler_lock:
                self._to_asterisk_resampler.stdin.write(data)
                await self._to_asterisk_resampler.stdin.drain()
        else:
            await self._write_to_tx_queue(data)

    async def hangup(self):
        """
        Send a hangup command to asterisk
        This absolutely MUST be called before closing the connection
        If you don't, asterisk will for some reason never hangup the AudioSocket channel and will go into some weird state, consuming 100% CPU.
        This method is automatically called in the close() method
        :return: None
        """
        logger.debug("AsyncConnection.hangup")
        if hasattr(self, 'hangup_sent') and self.hangup_sent:
            return
        async with self._lock:
            await self._loop.sock_sendall(self.conn, types.hangup * 3)
            self.hangup_sent = True

    async def _process(self):
        try:
            logger.debug("AsyncConnection._process")
            while self.connected:
                data = None
                try:
                    data = await self._loop.sock_recv(self.conn, 323)
                except ConnectionResetError:
                    pass
                if not data:
                    break
                type_byte, length, payload = self._split_data(data)
                if type_byte == types.audio:
                    if self._rx_q.full():
                        #logger.debug('[AUDIOSOCKET WARNING] The inbound audio queue is full! This most ' +
                        #      'likely occurred because the read() method is not being called, dropping oldest frame')
                        # Get and discard the oldest frame
                        self._rx_q.get_nowait()
                        self._rx_q.task_done()
                    await self._rx_q.put(payload)
                    if self._tx_q.empty():
                        async with self._lock:
                            # If the connection is closed, the socket will be closed next time around in receive part of loop
                            with suppress(ConnectionResetError):
                                await self._loop.sock_sendall(self.conn, types.audio + PCM_SIZE + bytes(320))
                    else:
                        audio_data = await self._tx_q.get()
                        if len(audio_data) > 320:
                            logger.warning("Audio data is greater than 320 bytes, truncating to 320 bytes")
                            audio_data = audio_data[:320]

                        async with self._lock:
                            # If the connection is closed, the socket will be closed next time around in receive part of loop
                            with suppress(ConnectionResetError):
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
                else:
                    logger.warning(f"Unknown type byte: {type_byte}")
        except asyncio.CancelledError:
            raise
        finally:
            # Send hangup
            await self.hangup()
            # Give the hangup time to be sent
            await asyncio.sleep(0.2)
            # Close the connection
            if hasattr(self, 'conn'):
                self.conn.close()
            self.connected = False

    async def close(self):
        """
        Drain the send queue, stop resampling, send hangup, and close the connection
        :return: None
        """
        logger.debug("AsyncConnection.close")
        if not self.connected:
            return
        # Wait for the send queue to drain
        logger.debug("AsyncConnection.close: draining send queue")
        try:
            # Try to drain the send queue, for cases where we initiate the close and the audio is still being sent
            # But don't wait too long as this will block indefinitely if the connection is dead
            await asyncio.wait_for(self.drain_send_queue(), timeout=5)
        except asyncio.TimeoutError:
            pass
        # Stop resampling if it is running
        await self.stop_resampling()
        # Cancel the process task
        if hasattr(self, '_task') and self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
