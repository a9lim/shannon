"""Discord voice channel support — VoiceManager and audio utilities."""

from __future__ import annotations

import audioop
import logging
import struct
import time

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RTP header parsing
# ---------------------------------------------------------------------------

def parse_rtp_header(packet: bytes) -> tuple[int, int, int, bytes] | None:
    """Parse RTP header, return (sequence, timestamp, ssrc, payload) or None.

    Handles the optional header extension (X bit). Returns the payload bytes
    after the RTP header (and extension if present).
    """
    if len(packet) < 12:
        return None

    first_byte = packet[0]
    has_extension = bool(first_byte & 0x10)
    cc = first_byte & 0x0F  # CSRC count

    seq, ts, ssrc = struct.unpack_from(">HII", packet, 2)

    offset = 12 + cc * 4  # skip CSRC list

    if has_extension:
        if len(packet) < offset + 4:
            return None
        ext_length = struct.unpack_from(">HH", packet, offset)[1]
        offset += 4 + ext_length * 4

    if offset > len(packet):
        return None

    return seq, ts, ssrc, packet[offset:]


# ---------------------------------------------------------------------------
# Audio format conversion
# ---------------------------------------------------------------------------

def pcm_48k_stereo_to_16k_mono(data: bytes) -> bytes:
    """Convert 48kHz stereo 16-bit PCM to 16kHz mono for Whisper STT.

    Steps: stereo->mono, then 48kHz->16kHz.
    """
    # Stereo to mono (width=2 for 16-bit)
    mono = audioop.tomono(data, 2, 1.0, 1.0)
    # 48kHz -> 16kHz
    converted, _state = audioop.ratecv(mono, 2, 1, 48000, 16000, None)
    return converted


def pcm_mono_to_48k_stereo(data: bytes, src_rate: int) -> bytes:
    """Convert mono 16-bit PCM at *src_rate* to 48kHz stereo for Discord.

    Steps: resample to 48kHz (if needed), then mono->stereo.
    """
    if src_rate != 48000:
        data, _state = audioop.ratecv(data, 2, 1, src_rate, 48000, None)
    # Mono to stereo (same amplitude in both channels)
    stereo = audioop.tostereo(data, 2, 1.0, 1.0)
    return stereo


# ---------------------------------------------------------------------------
# Per-user audio buffer
# ---------------------------------------------------------------------------

class UserAudioBuffer:
    """Accumulates PCM audio for a single user with max-length cap."""

    def __init__(self, max_seconds: float, sample_rate: int, channels: int) -> None:
        self._max_bytes = int(max_seconds * sample_rate * channels * 2)  # 16-bit
        self._buf = bytearray()
        self._last_activity = time.monotonic()

    @property
    def has_data(self) -> bool:
        return len(self._buf) > 0

    @property
    def silence_seconds(self) -> float:
        return time.monotonic() - self._last_activity

    def append(self, pcm: bytes) -> None:
        """Append PCM data, trimming oldest bytes if over cap."""
        self._buf.extend(pcm)
        if len(self._buf) > self._max_bytes:
            excess = len(self._buf) - self._max_bytes
            del self._buf[:excess]
        self._last_activity = time.monotonic()

    def drain(self) -> bytes:
        """Return all buffered data and clear the buffer."""
        data = bytes(self._buf)
        self._buf.clear()
        return data
