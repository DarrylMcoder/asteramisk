import socket
import asyncio
from dataclasses import dataclass
from asteramisk.internal.async_class import AsyncClass

@dataclass
class RTPState:
    seq: int = 1
    ts: int = 0
    ssrc: int = 0x12345678

class RTPSocket(AsyncClass):
    async def __create__(self, asterisk_rtp_host, asterisk_rtp_port, local_rtp_host, local_rtp_port):
        self.asterisk_rtp_host = asterisk_rtp_host
        self.asterisk_rtp_port = asterisk_rtp_port
        self.local_rtp_host = local_rtp_host
        self.local_rtp_port = local_rtp_port
        self._rtp = RTPState()
        loop = asyncio.get_running_loop()
        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp.bind((self.local_rtp_host, self.local_rtp_port))
        self._udp.setblocking(False)
        self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    async def write(self, data):
        for i in range(0, len(data), 640):
            pkt = await self._build_rtp(data[i:i+640], self._rtp)
            self._udp.sendto(pkt, (self.asterisk_rtp_host, self.asterisk_rtp_port))

    async def read(self):
        try:
            data = await asyncio.get_running_loop().sock_recv(self._udp, 4096)
        except (asyncio.CancelledError, OSError):
            return None
        return await self._parse_rtp(data)

    async def _build_rtp(payload: bytes, st: RTPState) -> bytes:
        """Build RTP packet with 12-byte header + payload"""
        # 12-byte RTP header: V/P/X/CC, M/PT, seq, ts, ssrc
        vpxcc = (RTP_VERSION << 6)
        mpt = PT_DYN  # no marker bit for continuous audio
        header = struct.pack("!BBHII", vpxcc, mpt, st.seq & 0xFFFF, st.ts & 0xFFFFFFFF, st.ssrc)
        st.seq = (st.seq + 1) & 0xFFFF
        st.ts = (st.ts + 320) & 0xFFFFFFFF  # 16kHz * 0.02s
        return header + payload

    async def _parse_rtp(packet: bytes) -> bytes:
        """Extract payload from RTP packet"""
        if len(packet) < 12:  # invalid
            return b""
        # Ignore header fields; return payload only
        return packet[12:]

    async def close(self):
        self._udp.close()
