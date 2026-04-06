"""Discord voice channel support — VoiceManager and audio utilities."""

from __future__ import annotations

import asyncio
import audioop
import io
import logging
import struct
import threading
import time
import wave
from typing import TYPE_CHECKING, Any

import discord
import nacl.secret
import nacl.utils

if TYPE_CHECKING:
    from shannon.bus import EventBus
    from shannon.config import VoiceConfig
    from shannon.input.providers.base import STTProvider
    from shannon.output.providers.tts.base import TTSProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RTP header parsing
# ---------------------------------------------------------------------------

def parse_rtp_header(packet: bytes) -> tuple[int, int, int, int, int] | None:
    """Parse RTP header for ``_rtpsize`` modes.

    Returns ``(seq, ts, ssrc, aad_len, ext_data_len)``.

    Per RFC 9605, ``_rtpsize`` modes authenticate the fixed header, CSRC list,
    and the extension *header* (profile + length, 4 bytes) as AAD.  The
    extension *data* is encrypted together with the audio payload.

    * ``aad_len`` — bytes to use as AEAD AAD (everything before the ciphertext).
    * ``ext_data_len`` — bytes of extension data inside the ciphertext that
      must be stripped after decryption to get the raw audio frame.
    """
    if len(packet) < 12:
        return None

    first_byte = packet[0]
    # RTP version must be 2 (bits 6-7)
    if (first_byte >> 6) != 2:
        return None
    # Filter RTCP packets (PT 200-204 in byte 1) — they share version=2 with RTP
    if packet[1] in (200, 201, 202, 203, 204):
        return None

    cc = first_byte & 0x0F  # CSRC count
    has_extension = bool(first_byte & 0x10)

    seq, ts, ssrc = struct.unpack_from(">HII", packet, 2)

    # AAD = fixed header + CSRC list + extension header (if present).
    # Extension DATA is encrypted, so it is NOT part of the AAD.
    aad_len = 12 + cc * 4
    ext_data_len = 0
    if has_extension:
        if len(packet) < aad_len + 4:
            return None
        ext_words = struct.unpack_from(">HH", packet, aad_len)[1]
        ext_data_len = ext_words * 4
        aad_len += 4  # include extension header (profile + length) in AAD

    if aad_len > len(packet):
        return None

    return seq, ts, ssrc, aad_len, ext_data_len


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


class ChunkAudioSource(discord.AudioSource):
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
        self._muted = threading.Event()
        self._opus_decoder = None
        self._lock = threading.Lock()  # Protects _user_buffers, _opus_decoder, _ssrc_to_user from socket thread
        self._packet_count = 0
        self._unknown_ssrcs: set[int] = set()  # SSRCs seen but not mapped
        self._hooked_ws: set[int] = set()  # id() of websockets we've hooked

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
            mode = getattr(vc._connection, "mode", "unknown")
            logger.info("Joined voice channel %s in guild %s (encryption: %s)", channel_id, guild_id, mode)

            # Enable DAVE passthrough so we can receive audio while MLS key
            # exchange completes (or from peers not using DAVE).
            dave_session = getattr(vc._connection, "dave_session", None)
            if dave_session is not None:
                try:
                    dave_session.set_passthrough_mode(True, 120)
                    logger.info("DAVE passthrough enabled (120s window)")
                except Exception:
                    logger.debug("Failed to set DAVE passthrough", exc_info=True)

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

    def handle_speaking_update(self, user_id: str, ssrc: int, display_name: str) -> None:
        """Register or update SSRC-to-user mapping from a SPEAKING event."""
        with self._lock:
            old_ssrcs = [s for s, (uid, _) in self._ssrc_to_user.items() if uid == user_id]
            for old_ssrc in old_ssrcs:
                del self._ssrc_to_user[old_ssrc]
                self._user_buffers.pop(old_ssrc, None)
            self._ssrc_to_user[ssrc] = (user_id, display_name)
        logger.info("SSRC %d -> user %s (%s)", ssrc, user_id, display_name)

    def _register_audio_listener(self, vc: Any) -> None:
        """Register a socket listener on the VoiceClient to receive raw UDP packets."""
        try:
            vc._connection.add_socket_listener(self._on_udp_packet)
            logger.info("Registered UDP socket listener on voice connection")
        except Exception:
            logger.exception("Failed to register socket listener")
        self._hook_voice_ws(vc)

    def _hook_voice_ws(self, vc: Any) -> None:
        """Monkey-patch the voice websocket to intercept SPEAKING and CLIENT_CONNECT events."""
        try:
            ws = vc.ws
            if ws is None:
                logger.warning("Voice websocket is None, cannot hook speaking events")
                return
            original_received = ws.received_message

            def _resolve_display_name(user_id: str) -> str:
                if hasattr(vc, "channel") and vc.channel:
                    for m in vc.channel.members:
                        if str(m.id) == str(user_id):
                            return m.display_name
                return str(user_id)

            async def patched_received(msg: Any) -> None:
                if isinstance(msg, dict):
                    op = msg.get("op")
                    data = msg.get("d", {})
                    # op 5 = SPEAKING — maps user_id to ssrc
                    if op == 5:
                        user_id = data.get("user_id", "")
                        ssrc = data.get("ssrc", 0)
                        if user_id and ssrc:
                            self.handle_speaking_update(
                                str(user_id), ssrc, _resolve_display_name(str(user_id)),
                            )
                    # op 12 = CLIENT_CONNECT — also carries audio_ssrc
                    elif op == 12:
                        user_id = data.get("user_id", "")
                        ssrc = data.get("audio_ssrc", 0)
                        if user_id and ssrc:
                            self.handle_speaking_update(
                                str(user_id), ssrc, _resolve_display_name(str(user_id)),
                            )
                await original_received(msg)

            ws.received_message = patched_received
            self._hooked_ws.add(id(ws))
            logger.info("Hooked voice websocket for SPEAKING/CLIENT_CONNECT events")
        except Exception:
            logger.warning("Failed to hook voice websocket events", exc_info=True)

    def _unregister_audio_listener(self, vc: Any) -> None:
        """Remove the socket listener."""
        try:
            vc._connection.remove_socket_listener(self._on_udp_packet)
        except Exception:
            logger.debug("Failed to remove socket listener", exc_info=True)

    def _on_udp_packet(self, data: bytes) -> None:
        """Callback for raw UDP packets from Discord voice socket.

        Called from discord.py's SocketReader thread — not the asyncio event loop.
        Uses self._lock to synchronize access to _user_buffers, _ssrc_to_user,
        and _opus_decoder.
        """
        if self._muted.is_set() and self._config.mute_during_playback:
            return

        parsed = parse_rtp_header(data)
        if parsed is None:
            return

        seq, ts, ssrc, aad_len, ext_data_len = parsed

        self._packet_count += 1
        if self._packet_count == 1:
            logger.info("Receiving UDP voice packets (first packet, ssrc=%d)", ssrc)

        with self._lock:
            if ssrc not in self._ssrc_to_user:
                if ssrc not in self._unknown_ssrcs:
                    self._unknown_ssrcs.add(ssrc)
                    logger.debug("Unmapped SSRC %d (known: %s)", ssrc, list(self._ssrc_to_user.keys()))
                return
            user_info = self._ssrc_to_user[ssrc]

        # In _rtpsize modes (RFC 9605): AAD = fixed header + CSRC + extension header.
        # Extension DATA is encrypted as part of the payload.
        header = data[:aad_len]
        payload = data[aad_len:]
        decrypted = self._decrypt_payload(payload, header)
        if decrypted is None:
            return

        # Strip encrypted extension data that was part of the ciphertext.
        # After decryption it's the first ext_data_len bytes.
        if ext_data_len > 0:
            if len(decrypted) <= ext_data_len:
                return
            decrypted = decrypted[ext_data_len:]

        # DAVE E2EE: second decryption layer if active
        decrypted = self._dave_decrypt(ssrc, decrypted, user_info)
        if decrypted is None:
            return

        pcm = self._decode_opus(decrypted)
        if pcm is None:
            return

        with self._lock:
            if ssrc not in self._user_buffers:
                self._user_buffers[ssrc] = UserAudioBuffer(
                    max_seconds=self._config.buffer_max_seconds,
                    sample_rate=48000,
                    channels=2,
                )
            self._user_buffers[ssrc].append(pcm)

    def _decrypt_payload(self, payload: bytes, header: bytes) -> bytes | None:
        """Decrypt an RTP payload using the session secret key.

        Supports:
        - aead_xchacha20_poly1305_rtpsize (discord.py 2.7+ preferred mode)
        - aead_aes256_gcm / aead_aes256_gcm_rtpsize
        - xsalsa20_poly1305 / xsalsa20_poly1305_suffix / xsalsa20_poly1305_lite (legacy)
        """
        for vc in self._voice_clients.values():
            try:
                secret_key = bytes(vc._connection.secret_key)
            except Exception:
                continue
            if not secret_key:
                continue
            mode = getattr(vc._connection, "mode", "xsalsa20_poly1305")
            if "xchacha20" in mode:
                return self._decrypt_xchacha20_rtpsize(payload, header, secret_key)
            elif "aead_aes256_gcm" in mode:
                return self._decrypt_aead_gcm(payload, header, secret_key)
            elif "lite" in mode:
                return self._decrypt_xsalsa20_lite(payload, secret_key)
            elif "suffix" in mode:
                return self._decrypt_xsalsa20_suffix(payload, secret_key)
            else:
                # xsalsa20_poly1305 (plain) — nonce is RTP header zero-padded to 24 bytes
                nonce = header + b"\x00" * (24 - len(header))
                box = nacl.secret.SecretBox(secret_key)
                try:
                    return box.decrypt(payload, nonce)
                except Exception:
                    logger.debug("XSalsa20 decryption failed", exc_info=True)
                    return None
        return None

    @staticmethod
    def _decrypt_xchacha20_rtpsize(payload: bytes, header: bytes, secret_key: bytes) -> bytes | None:
        """Decrypt using XChaCha20-Poly1305 AEAD (discord.py 2.7+ preferred mode).

        Per RFC 9605, in ``_rtpsize`` modes the AAD is the fixed RTP header +
        CSRC list + extension *header* (4 bytes).  The extension *data* is
        encrypted as part of the ciphertext.  The 4-byte nonce suffix is
        appended after the ciphertext.
        """
        if len(payload) < 4:
            return None
        nonce_suffix = payload[-4:]
        ciphertext = payload[:-4]
        nonce = bytearray(24)
        nonce[:4] = nonce_suffix
        try:
            box = nacl.secret.Aead(secret_key)
            return box.decrypt(bytes(ciphertext), aad=bytes(header), nonce=bytes(nonce))
        except Exception:
            logger.debug("XChaCha20 decryption failed", exc_info=True)
            return None

    @staticmethod
    def _decrypt_xsalsa20_lite(payload: bytes, secret_key: bytes) -> bytes | None:
        """Decrypt using XSalsa20-Poly1305 lite mode (4-byte nonce suffix)."""
        if len(payload) < 4:
            return None
        nonce_suffix = payload[-4:]
        ciphertext = payload[:-4]
        nonce = nonce_suffix + b"\x00" * 20
        try:
            box = nacl.secret.SecretBox(secret_key)
            return box.decrypt(ciphertext, nonce)
        except Exception:
            logger.debug("XSalsa20 lite decryption failed", exc_info=True)
            return None

    @staticmethod
    def _decrypt_xsalsa20_suffix(payload: bytes, secret_key: bytes) -> bytes | None:
        """Decrypt using XSalsa20-Poly1305 suffix mode (24-byte nonce suffix)."""
        if len(payload) < 24:
            return None
        nonce = payload[-24:]
        ciphertext = payload[:-24]
        try:
            box = nacl.secret.SecretBox(secret_key)
            return box.decrypt(ciphertext, nonce)
        except Exception:
            logger.debug("XSalsa20 suffix decryption failed", exc_info=True)
            return None

    @staticmethod
    def _decrypt_aead_gcm(payload: bytes, header: bytes, secret_key: bytes) -> bytes | None:
        """Decrypt a payload using AEAD-AES256-GCM (Discord's modern encryption)."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            logger.warning(
                "AEAD-AES256-GCM encryption requires the 'cryptography' package. "
                "Install with: pip install cryptography"
            )
            return None
        # Discord AES-GCM: last 4 bytes of payload are the nonce (big-endian uint32),
        # the rest is ciphertext + GCM tag. AAD is the RTP header.
        if len(payload) < 4:
            return None
        nonce_suffix = payload[-4:]
        ciphertext = payload[:-4]
        # Build 12-byte nonce: 8 zero bytes + 4-byte suffix
        nonce = b"\x00" * 8 + nonce_suffix
        try:
            aesgcm = AESGCM(secret_key)
            return aesgcm.decrypt(nonce, ciphertext, header)
        except Exception:
            logger.debug("AES-GCM decryption failed", exc_info=True)
            return None

    def _dave_decrypt(self, ssrc: int, data: bytes, user_info: tuple[str, str] | None = None) -> bytes | None:
        """Decrypt the DAVE E2EE layer if active, otherwise pass through.

        DAVE (Discord Audio/Video Encryption) is a second encryption layer
        on top of transport encryption. When active, the transport-decrypted
        payload is DAVE-encrypted opus, not raw opus.

        Uses davey.DaveSession.decrypt(user_id, media_type, packet).
        """
        for vc in self._voice_clients.values():
            dave_session = getattr(vc._connection, "dave_session", None)
            if dave_session is None:
                return data  # No DAVE — pass through

            if user_info is None:
                return None

            user_id_int = int(user_info[0])

            # Check if this user is in passthrough mode (during transitions)
            try:
                if dave_session.can_passthrough(user_id_int):
                    return data
            except Exception:
                pass

            if not dave_session.ready:
                return data  # Session not ready yet — pass through

            try:
                import davey
                result = dave_session.decrypt(user_id_int, davey.MediaType.audio, data)
                if result is not None:
                    return bytes(result)
            except Exception:
                pass

            # DAVE decrypt failed or returned None — the data may be
            # unencrypted opus (peer not using DAVE, key exchange pending,
            # or transition in progress).  Pass through and let opus decode
            # be the final validator.
            return data
        return data  # No voice clients — pass through

    def _decode_opus(self, opus_data: bytes) -> bytes | None:
        """Decode an opus frame to 48kHz stereo PCM.

        Protected by self._lock since discord.opus.Decoder wraps ctypes
        calls to libopus which are not thread-safe.
        """
        with self._lock:
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
        """Background task: poll buffers for silence gaps and re-hook on reconnect."""
        try:
            rehook_counter = 0
            while True:
                await asyncio.sleep(0.2)
                await self._check_silence_and_transcribe()
                # Periodically check if voice ws was replaced (reconnect) — re-hook
                rehook_counter += 1
                if rehook_counter >= 25:  # Every 5 seconds
                    rehook_counter = 0
                    for vc in self._voice_clients.values():
                        try:
                            ws = vc.ws
                            if ws is not None and id(ws) not in self._hooked_ws:
                                logger.info("Voice websocket changed (reconnect?), re-hooking")
                                self._hook_voice_ws(vc)
                        except Exception:
                            pass
        except asyncio.CancelledError:
            pass

    async def _check_silence_and_transcribe(self) -> None:
        """Transcribe all active buffers when every speaker has been silent past threshold."""
        from shannon.events import VoiceInput

        if not self._user_buffers:
            return

        # Snapshot active buffers under lock (socket thread may be appending)
        with self._lock:
            active_buffers: list[tuple[int, UserAudioBuffer]] = [
                (ssrc, buf) for ssrc, buf in self._user_buffers.items() if buf.has_data
            ]
            if not active_buffers:
                return

            for _ssrc, buf in active_buffers:
                if buf.silence_seconds < self._config.silence_threshold:
                    return  # Someone is still speaking

            # All speakers are silent — drain buffers under lock
            drained: list[tuple[int, bytes]] = []
            for ssrc, buf in active_buffers:
                drained.append((ssrc, buf.drain()))

        # Transcribe outside the lock (STT is async and slow)
        speakers: dict[str, str] = {}
        text_parts: list[str] = []

        for ssrc, pcm_48k_stereo in drained:
            user_info = self._ssrc_to_user.get(ssrc)
            if user_info is None:
                continue

            user_id, display_name = user_info
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
        timeout = 30.0
        waited = 0.0
        while target_vc.is_playing():
            await asyncio.sleep(0.2)
            waited += 0.2
            if waited >= timeout:
                logger.warning("Playback wait timed out after %.0fs", timeout)
                break

        source = ChunkAudioSource(event.audio, volume=self._config.volume)

        if self._config.mute_during_playback:
            self._muted.set()

        def after_play(error: Exception | None) -> None:
            self._muted.clear()
            if error:
                logger.warning("Error during voice playback: %s", error)

        try:
            target_vc.play(source, after=after_play)
        except Exception:
            self._muted.clear()
            logger.exception("Failed to start voice playback")
