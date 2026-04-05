"""Discord voice channel support — VoiceManager and audio utilities."""

from __future__ import annotations

import asyncio
import audioop
import logging
import struct
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shannon.bus import EventBus
    from shannon.config import VoiceConfig
    from shannon.input.providers.base import STTProvider
    from shannon.output.providers.tts.base import TTSProvider

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


# ---------------------------------------------------------------------------
# Discord AudioSource for TTS playback
# ---------------------------------------------------------------------------

FRAME_SIZE = 3840  # 20ms of 48kHz stereo 16-bit PCM


class ChunkAudioSource:
    """discord.AudioSource that plays an AudioChunk, resampled to 48kHz stereo.

    discord.py calls read() in a separate thread to get 20ms PCM frames.
    Returns empty bytes when done.
    """

    def __init__(self, chunk: object, volume: float = 1.0) -> None:
        # chunk is AudioChunk but typed as object to avoid import at module level
        data = chunk.data  # type: ignore[attr-defined]
        sample_rate = chunk.sample_rate  # type: ignore[attr-defined]
        channels = chunk.channels  # type: ignore[attr-defined]

        # Convert to 48kHz stereo
        if channels == 1:
            pcm = pcm_mono_to_48k_stereo(data, src_rate=sample_rate)
        elif sample_rate != 48000:
            # Stereo but wrong rate — resample
            pcm, _ = audioop.ratecv(data, 2, 2, sample_rate, 48000, None)
        else:
            pcm = data

        # Apply volume
        if volume != 1.0:
            pcm = audioop.mul(pcm, 2, volume)

        self._data = pcm
        self._offset = 0

    def read(self) -> bytes:
        """Return next 20ms frame (3840 bytes) or empty bytes if done."""
        end = self._offset + FRAME_SIZE
        if self._offset >= len(self._data):
            return b""
        frame = self._data[self._offset:end]
        self._offset = end
        if len(frame) < FRAME_SIZE:
            # Pad last frame with silence
            frame = frame + b"\x00" * (FRAME_SIZE - len(frame))
        return frame

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        self._data = b""
        self._offset = 0


# ---------------------------------------------------------------------------
# VoiceManager — connection lifecycle
# ---------------------------------------------------------------------------

class VoiceManager:
    """Manages Discord voice channel connections, audio capture, and TTS playback."""

    def __init__(
        self,
        client: Any,  # discord.Client
        stt: "STTProvider",
        tts: "TTSProvider",
        bus: "EventBus",
        config: "VoiceConfig",
    ) -> None:
        self._client = client
        self._stt = stt
        self._tts = tts
        self._bus = bus
        self._config = config
        self._voice_clients: dict[str, Any] = {}  # guild_id -> VoiceClient
        self._user_buffers: dict[int, UserAudioBuffer] = {}  # ssrc -> buffer
        self._ssrc_to_user: dict[int, tuple[str, str]] = {}  # ssrc -> (user_id, display_name)
        self._silence_task: asyncio.Task | None = None
        self._muted = False
        self._opus_decoder = None

    async def start(self) -> None:
        from shannon.events import VoiceOutput
        self._bus.subscribe(VoiceOutput, self._on_voice_output)
        self._silence_task = asyncio.create_task(self._silence_monitor())

    async def stop(self) -> None:
        if self._silence_task is not None:
            self._silence_task.cancel()
            self._silence_task = None
        from shannon.events import VoiceOutput
        self._bus.unsubscribe(VoiceOutput, self._on_voice_output)
        for vc in list(self._voice_clients.values()):
            try:
                await vc.disconnect()
            except Exception:
                logger.debug("Error disconnecting voice client", exc_info=True)
        self._voice_clients.clear()
        self._user_buffers.clear()

    async def handle_voice_state_update(self, member: Any, before: Any, after: Any) -> None:
        from shannon.events import VoiceStateChange

        if member.bot:
            return

        new_channel = str(after.channel.id) if after.channel else None
        await self._bus.publish(VoiceStateChange(
            user_id=str(member.id),
            user_name=member.display_name,
            channel=new_channel,
        ))

        if after.channel is not None and (before.channel is None or before.channel != after.channel):
            await self._maybe_join(after.channel)

        if before.channel is not None and (after.channel is None or after.channel != before.channel):
            await self._maybe_leave(before.channel)

    async def _maybe_join(self, channel: Any) -> None:
        channel_id = str(channel.id)
        guild_id = str(channel.guild.id)

        if self._config.auto_join_channels and channel_id not in self._config.auto_join_channels:
            return

        if guild_id in self._voice_clients:
            return

        non_bots = [m for m in channel.members if not m.bot]
        if not non_bots:
            return

        try:
            vc = await channel.connect()
            self._voice_clients[guild_id] = vc
            logger.info("Joined voice channel %s in guild %s", channel_id, guild_id)
            self._register_audio_listener(vc)
        except Exception:
            logger.exception("Failed to connect to voice channel %s", channel_id)

    async def _maybe_leave(self, channel: Any) -> None:
        guild_id = str(channel.guild.id)
        vc = self._voice_clients.get(guild_id)
        if vc is None:
            return

        non_bots = [m for m in channel.members if not m.bot]
        if not non_bots:
            self._unregister_audio_listener(vc)
            try:
                await vc.disconnect()
            except Exception:
                logger.debug("Error disconnecting from voice channel", exc_info=True)
            self._voice_clients.pop(guild_id, None)
            logger.info("Left voice channel in guild %s (empty)", guild_id)

    def _register_audio_listener(self, vc: Any) -> None:
        """Register a socket listener on the VoiceClient to receive raw UDP packets."""
        pass  # Implemented in Task 10

    def _unregister_audio_listener(self, vc: Any) -> None:
        """Remove the socket listener."""
        pass  # Implemented in Task 10

    async def _silence_monitor(self) -> None:
        """Background task: poll buffers for silence gaps."""
        try:
            while True:
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass

    async def _on_voice_output(self, event: Any) -> None:
        """Handle VoiceOutput event."""
        pass  # Implemented in Task 12
