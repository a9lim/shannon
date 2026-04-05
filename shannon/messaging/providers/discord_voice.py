"""Discord voice channel support — VoiceManager and audio utilities."""

from __future__ import annotations

import asyncio
import audioop
import io
import logging
import struct
import time
import wave
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


def _pcm_to_wav(pcm: bytes, sample_rate: int, channels: int) -> bytes:
    """Wrap raw 16-bit PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


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
        try:
            vc._connection.add_socket_listener(self._on_udp_packet)
        except Exception:
            logger.exception("Failed to register socket listener")

    def _unregister_audio_listener(self, vc: Any) -> None:
        """Remove the socket listener."""
        try:
            vc._connection.remove_socket_listener(self._on_udp_packet)
        except Exception:
            logger.debug("Failed to remove socket listener", exc_info=True)

    def _on_udp_packet(self, data: bytes) -> None:
        """Callback for raw UDP packets from Discord voice socket."""
        if self._muted and self._config.mute_during_playback:
            return

        parsed = parse_rtp_header(data)
        if parsed is None:
            return

        seq, ts, ssrc, payload = parsed

        if ssrc not in self._ssrc_to_user:
            return

        decrypted = self._decrypt_payload(payload, data[:12])
        if decrypted is None:
            return

        pcm = self._decode_opus(decrypted)
        if pcm is None:
            return

        if ssrc not in self._user_buffers:
            self._user_buffers[ssrc] = UserAudioBuffer(
                max_seconds=self._config.buffer_max_seconds,
                sample_rate=48000,
                channels=2,
            )
        self._user_buffers[ssrc].append(pcm)

    def _decrypt_payload(self, payload: bytes, header: bytes) -> bytes | None:
        """Decrypt an RTP payload using the session secret key."""
        for vc in self._voice_clients.values():
            try:
                secret_key = bytes(vc._connection.secret_key)
                if not secret_key:
                    continue
                nonce = header + b"\x00" * (24 - len(header))
                import nacl.secret
                box = nacl.secret.SecretBox(secret_key)
                return box.decrypt(payload, nonce)
            except Exception:
                logger.debug("Decryption failed for packet", exc_info=True)
                return None
        return None

    def _decode_opus(self, opus_data: bytes) -> bytes | None:
        """Decode an opus frame to 48kHz stereo PCM."""
        try:
            if self._opus_decoder is None:
                import discord.opus
                if not discord.opus.is_loaded():
                    discord.opus._load_default()
                self._opus_decoder = discord.opus.Decoder()
            return self._opus_decoder.decode(opus_data)
        except Exception:
            logger.debug("Opus decode failed", exc_info=True)
            return None

    async def _silence_monitor(self) -> None:
        """Background task: poll buffers for silence gaps."""
        try:
            while True:
                await asyncio.sleep(0.2)
                await self._check_silence_and_transcribe()
        except asyncio.CancelledError:
            pass

    async def _check_silence_and_transcribe(self) -> None:
        """Transcribe all active buffers when every speaker has been silent past threshold."""
        from shannon.events import VoiceInput

        if not self._user_buffers:
            return

        active_buffers: list[tuple[int, UserAudioBuffer]] = [
            (ssrc, buf) for ssrc, buf in self._user_buffers.items() if buf.has_data
        ]
        if not active_buffers:
            return

        for _ssrc, buf in active_buffers:
            if buf.silence_seconds < self._config.silence_threshold:
                return  # Someone is still speaking

        # All speakers are silent — transcribe each buffer
        speakers: dict[str, str] = {}
        text_parts: list[str] = []

        for ssrc, buf in active_buffers:
            user_info = self._ssrc_to_user.get(ssrc)
            if user_info is None:
                buf.drain()
                continue

            user_id, display_name = user_info
            pcm_48k_stereo = buf.drain()
            pcm_16k_mono = pcm_48k_stereo_to_16k_mono(pcm_48k_stereo)
            wav_data = _pcm_to_wav(pcm_16k_mono, sample_rate=16000, channels=1)

            try:
                transcript = await self._stt.transcribe(wav_data)
            except Exception:
                logger.exception("STT transcription failed for user %s", display_name)
                continue

            transcript = transcript.strip()
            if transcript:
                speakers[user_id] = display_name
                text_parts.append(f"{display_name}: {transcript}")

        if not text_parts:
            return

        channel_id = ""
        for vc in self._voice_clients.values():
            if hasattr(vc, "channel") and vc.channel:
                channel_id = str(vc.channel.id)
                break

        await self._bus.publish(VoiceInput(
            text="\n".join(text_parts),
            speakers=speakers,
            channel=channel_id,
        ))

    async def _on_voice_output(self, event: Any) -> None:
        """Handle VoiceOutput event: play TTS audio in the voice channel."""
        target_channel = event.channel

        target_vc = None
        for vc in self._voice_clients.values():
            if hasattr(vc, "channel") and vc.channel and str(vc.channel.id) == target_channel:
                target_vc = vc
                break

        if target_vc is None:
            logger.debug("No voice client for channel %s, dropping VoiceOutput", target_channel)
            return

        # Wait for any current playback to finish (sequential queuing)
        while target_vc.is_playing():
            await asyncio.sleep(0.1)

        source = ChunkAudioSource(event.audio, volume=self._config.volume)

        if self._config.mute_during_playback:
            self._muted = True

        def after_play(error: Exception | None) -> None:
            self._muted = False
            if error:
                logger.warning("Error during voice playback: %s", error)

        target_vc.play(source, after=after_play)
