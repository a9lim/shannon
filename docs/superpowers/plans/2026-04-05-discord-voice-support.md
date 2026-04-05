# Discord Voice Channel Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full-duplex Discord voice channel support — Shannon auto-joins voice channels, listens via per-user STT, and responds with TTS audio.

**Architecture:** VoiceManager class in `shannon/messaging/providers/discord_voice.py` handles connection lifecycle, raw UDP audio capture (RTP parsing, decryption, opus decode), silence-gap batching for STT, and TTS playback via a custom AudioSource. Integrates with the event bus via three new events: VoiceInput, VoiceOutput, VoiceStateChange.

**Tech Stack:** discord.py 2.7.1 (VoiceClient, AudioSource, opus.Decoder), PyNaCl (AEAD decryption), davey (DAVE E2EE), audioop-lts (sample rate/channel conversion), existing Piper TTS + Whisper STT.

**Spec:** `docs/superpowers/specs/2026-04-05-discord-voice-support-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `shannon/messaging/providers/discord_voice.py` | VoiceManager: connection lifecycle, audio capture, silence batching, TTS playback |
| Modify | `shannon/events.py` | Add VoiceInput, VoiceOutput, VoiceStateChange events |
| Modify | `shannon/config.py` | Add VoiceConfig dataclass, nest under MessagingConfig |
| Modify | `shannon/messaging/providers/discord.py` | Expose `client` property, add `voice_states` intent |
| Modify | `shannon/brain/brain.py` | Add `_on_voice_input` handler |
| Modify | `shannon/app.py` | Wire VoiceManager at startup, validate deps, shutdown order |
| Modify | `pyproject.toml` | Add `voice` optional dep group |
| Create | `tests/test_discord_voice.py` | All voice-related tests |
| Modify | `tests/test_config.py` | VoiceConfig tests |
| Modify | `tests/test_brain.py` | VoiceInput handler tests |

---

### Task 1: Add VoiceConfig to Configuration

**Files:**
- Modify: `shannon/config.py:84-108` (MessagingConfig)
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for VoiceConfig**

Add to `tests/test_config.py`:

```python
# --- Voice config tests ---

def test_voice_config_defaults():
    from shannon.config import VoiceConfig
    vc = VoiceConfig()
    assert vc.enabled is False
    assert vc.auto_join_channels == []
    assert vc.silence_threshold == 2.0
    assert vc.buffer_max_seconds == 30.0
    assert vc.voice_reply_probability == 1.0
    assert vc.mute_during_playback is True
    assert vc.volume == 1.0


def test_voice_config_clamps_silence_threshold():
    from shannon.config import VoiceConfig
    vc = VoiceConfig(silence_threshold=0.1)
    assert vc.silence_threshold == 0.5
    vc2 = VoiceConfig(silence_threshold=99.0)
    assert vc2.silence_threshold == 10.0


def test_voice_config_clamps_buffer_max():
    from shannon.config import VoiceConfig
    vc = VoiceConfig(buffer_max_seconds=1.0)
    assert vc.buffer_max_seconds == 5.0
    vc2 = VoiceConfig(buffer_max_seconds=999.0)
    assert vc2.buffer_max_seconds == 60.0


def test_voice_config_clamps_reply_probability():
    from shannon.config import VoiceConfig
    vc = VoiceConfig(voice_reply_probability=-1.0)
    assert vc.voice_reply_probability == 0.0
    vc2 = VoiceConfig(voice_reply_probability=5.0)
    assert vc2.voice_reply_probability == 1.0


def test_voice_config_clamps_volume():
    from shannon.config import VoiceConfig
    vc = VoiceConfig(volume=-0.5)
    assert vc.volume == 0.0
    vc2 = VoiceConfig(volume=10.0)
    assert vc2.volume == 2.0


def test_messaging_config_has_voice():
    from shannon.config import MessagingConfig
    mc = MessagingConfig()
    assert hasattr(mc, "voice")
    assert mc.voice.enabled is False


def test_voice_config_merges_from_yaml(tmp_path):
    import yaml
    from shannon.config import load_config
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "messaging": {
            "voice": {
                "enabled": True,
                "silence_threshold": 3.0,
                "auto_join_channels": ["12345"],
            }
        }
    }))
    config = load_config(str(config_file))
    assert config.messaging.voice.enabled is True
    assert config.messaging.voice.silence_threshold == 3.0
    assert config.messaging.voice.auto_join_channels == ["12345"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config.py -k "voice" -v`
Expected: FAIL — `VoiceConfig` does not exist yet.

- [ ] **Step 3: Implement VoiceConfig**

In `shannon/config.py`, add the VoiceConfig dataclass **before** MessagingConfig (before line 83):

```python
@dataclass
class VoiceConfig:
    enabled: bool = False
    auto_join_channels: list[str] = field(default_factory=list)
    silence_threshold: float = 2.0
    buffer_max_seconds: float = 30.0
    voice_reply_probability: float = 1.0
    mute_during_playback: bool = True
    volume: float = 1.0

    def __post_init__(self) -> None:
        if _SKIP_VALIDATION:
            return
        self.silence_threshold = _clamp(self.silence_threshold, 0.5, 10.0, "silence_threshold")
        self.buffer_max_seconds = _clamp(self.buffer_max_seconds, 5.0, 60.0, "buffer_max_seconds")
        self.voice_reply_probability = _clamp(self.voice_reply_probability, 0, 1, "voice_reply_probability")
        self.volume = _clamp(self.volume, 0, 2, "volume")
```

Then add `voice` field to `MessagingConfig` (after `admin_ids`):

```python
    voice: VoiceConfig = field(default_factory=VoiceConfig)
```

No changes needed to `_merge_dataclass` — it already handles nested dataclasses recursively.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py -k "voice" -v`
Expected: All PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python3 -m pytest tests/ -v`
Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add shannon/config.py tests/test_config.py
git commit -m "feat: add VoiceConfig dataclass for Discord voice support"
```

---

### Task 2: Add Voice Events

**Files:**
- Modify: `shannon/events.py:115` (end of file)
- Modify: `tests/test_events.py`

- [ ] **Step 1: Write failing tests for new events**

Add to `tests/test_events.py`:

```python
from shannon.events import VoiceInput, VoiceOutput, VoiceStateChange


def test_voice_input():
    event = VoiceInput(
        text="Hello everyone",
        speakers={"123": "Alice", "456": "Bob"},
        channel="789",
    )
    assert event.text == "Hello everyone"
    assert event.speakers == {"123": "Alice", "456": "Bob"}
    assert event.channel == "789"
    assert event.platform == "discord"


def test_voice_output():
    from shannon.output.providers.tts.base import AudioChunk
    chunk = AudioChunk(data=b"\x00" * 100, sample_rate=22050, channels=1)
    event = VoiceOutput(audio=chunk, channel="789")
    assert event.audio is chunk
    assert event.channel == "789"
    assert event.platform == "discord"


def test_voice_state_change_join():
    event = VoiceStateChange(user_id="123", user_name="Alice", channel="789")
    assert event.channel == "789"
    assert event.platform == "discord"


def test_voice_state_change_leave():
    event = VoiceStateChange(user_id="123", user_name="Alice", channel=None)
    assert event.channel is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_events.py -k "voice" -v`
Expected: FAIL — imports don't exist.

- [ ] **Step 3: Add events to `shannon/events.py`**

Append at end of file (after line 114):

```python

@dataclass
class VoiceInput:
    """Batched transcription from voice channel after silence gap."""
    text: str
    speakers: dict[str, str]  # user_id -> display_name
    channel: str
    platform: str = "discord"


@dataclass
class VoiceOutput:
    """TTS audio to play in a voice channel."""
    audio: object  # AudioChunk — typed as object to avoid circular import
    channel: str
    platform: str = "discord"


@dataclass
class VoiceStateChange:
    """User joined/left a voice channel."""
    user_id: str
    user_name: str
    channel: str | None  # None = left all voice
    platform: str = "discord"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_events.py -k "voice" -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add shannon/events.py tests/test_events.py
git commit -m "feat: add VoiceInput, VoiceOutput, VoiceStateChange events"
```

---

### Task 3: Add `voice` Optional Dependency Group

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml**

Add the `voice` group to `[project.optional-dependencies]` and update `all`:

```toml
voice = ["PyNaCl>=1.5.0", "davey>=0.1.0"]
all = ["shannon[computer,vision,tts,stt,vtuber,messaging,voice]"]
```

- [ ] **Step 2: Install the new group**

Run: `pip install -e ".[all,dev]"`
Expected: PyNaCl and davey install successfully.

- [ ] **Step 3: Verify imports work**

Run: `python3 -c "import nacl; import davey; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add voice optional dependency group (PyNaCl, davey)"
```

---

### Task 4: Expose Discord Client and Add Voice Intents

**Files:**
- Modify: `shannon/messaging/providers/discord.py:82-100`
- Modify: `tests/test_discord_provider.py`

- [ ] **Step 1: Write failing test for client property**

Add to `tests/test_discord_provider.py`:

```python
def test_discord_provider_exposes_client():
    """DiscordProvider.client returns the internal discord.Client (or None before connect)."""
    from shannon.messaging.providers.discord import DiscordProvider
    provider = DiscordProvider(token="fake-token")
    assert provider.client is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_discord_provider.py -k "exposes_client" -v`
Expected: FAIL — no `client` attribute.

- [ ] **Step 3: Add client property to DiscordProvider**

In `shannon/messaging/providers/discord.py`, add after `__init__` (after line 87):

```python
    @property
    def client(self) -> Any:
        """The underlying discord.Client, or None before connect()."""
        return self._client
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_discord_provider.py -k "exposes_client" -v`
Expected: PASS.

- [ ] **Step 5: Add voice_states intent**

In `shannon/messaging/providers/discord.py`, modify the `connect()` method. Change lines 98-99:

```python
        intents = discord.Intents.default()
        intents.message_content = True
```

To:

```python
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
```

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add shannon/messaging/providers/discord.py tests/test_discord_provider.py
git commit -m "feat: expose discord.Client property and enable voice_states intent"
```

---

### Task 5: Audio Format Conversion Utilities

**Files:**
- Create: `shannon/messaging/providers/discord_voice.py` (start with just audio utils)
- Create: `tests/test_discord_voice.py`

- [ ] **Step 1: Write failing tests for audio conversion**

Create `tests/test_discord_voice.py`:

```python
"""Tests for Discord voice support."""

import struct
import pytest


# ---------------------------------------------------------------------------
# Audio conversion tests
# ---------------------------------------------------------------------------

def test_pcm_48k_stereo_to_16k_mono():
    """Convert 48kHz stereo PCM to 16kHz mono for Whisper."""
    from shannon.messaging.providers.discord_voice import pcm_48k_stereo_to_16k_mono

    # Generate 20ms of 48kHz stereo silence (3840 bytes)
    data_48k_stereo = b"\x00" * 3840
    result = pcm_48k_stereo_to_16k_mono(data_48k_stereo)

    # 48kHz stereo -> 16kHz mono: 3840 * (16000/48000) * (1/2) = 640 bytes
    # (audioop.ratecv may produce slightly different lengths due to state)
    assert len(result) > 0
    # All silence in = all silence out
    assert all(b == 0 for b in result)


def test_pcm_mono_to_48k_stereo():
    """Convert TTS PCM (arbitrary rate, mono) to 48kHz stereo for Discord."""
    from shannon.messaging.providers.discord_voice import pcm_mono_to_48k_stereo

    # 20ms of 22050Hz mono silence: 22050 * 0.02 * 2 bytes = 882 bytes
    # Round to even for 16-bit alignment
    num_samples = int(22050 * 0.02)
    data_mono = b"\x00" * (num_samples * 2)
    result = pcm_mono_to_48k_stereo(data_mono, src_rate=22050)

    # Should have data and be longer (upsampled + stereo)
    assert len(result) > len(data_mono)


def test_pcm_mono_to_48k_stereo_passthrough():
    """48kHz mono input only needs stereo conversion, no resampling."""
    from shannon.messaging.providers.discord_voice import pcm_mono_to_48k_stereo

    num_samples = 960  # 20ms at 48kHz
    data_mono = b"\x00" * (num_samples * 2)
    result = pcm_mono_to_48k_stereo(data_mono, src_rate=48000)

    # Stereo = 2x the bytes
    assert len(result) == num_samples * 4  # 2 channels * 2 bytes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_discord_voice.py -k "pcm" -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create `discord_voice.py` with audio conversion utilities**

Create `shannon/messaging/providers/discord_voice.py`:

```python
"""Discord voice channel support — VoiceManager and audio utilities."""

from __future__ import annotations

import audioop
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audio format conversion
# ---------------------------------------------------------------------------

def pcm_48k_stereo_to_16k_mono(data: bytes) -> bytes:
    """Convert 48kHz stereo 16-bit PCM to 16kHz mono for Whisper STT.

    Steps: stereo→mono, then 48kHz→16kHz.
    """
    # Stereo to mono (width=2 for 16-bit)
    mono = audioop.tomono(data, 2, 1.0, 1.0)
    # 48kHz -> 16kHz
    converted, _state = audioop.ratecv(mono, 2, 1, 48000, 16000, None)
    return converted


def pcm_mono_to_48k_stereo(data: bytes, src_rate: int) -> bytes:
    """Convert mono 16-bit PCM at *src_rate* to 48kHz stereo for Discord.

    Steps: resample to 48kHz (if needed), then mono→stereo.
    """
    if src_rate != 48000:
        data, _state = audioop.ratecv(data, 2, 1, src_rate, 48000, None)
    # Mono to stereo (same amplitude in both channels)
    stereo = audioop.tostereo(data, 2, 1.0, 1.0)
    return stereo
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_discord_voice.py -k "pcm" -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add shannon/messaging/providers/discord_voice.py tests/test_discord_voice.py
git commit -m "feat: add audio format conversion utilities for Discord voice"
```

---

### Task 6: RTP Parsing and SSRC Tracking

**Files:**
- Modify: `shannon/messaging/providers/discord_voice.py`
- Modify: `tests/test_discord_voice.py`

- [ ] **Step 1: Write failing tests for RTP parsing**

Add to `tests/test_discord_voice.py`:

```python
def test_parse_rtp_header():
    """Parse a valid RTP header to extract sequence, timestamp, ssrc."""
    from shannon.messaging.providers.discord_voice import parse_rtp_header

    # Build a fake RTP packet: version=2, no padding/extension, payload type 120
    # Sequence: 42, Timestamp: 12345, SSRC: 99
    header = struct.pack(">BBHII", 0x80, 120, 42, 12345, 99)
    payload = b"\xDE\xAD\xBE\xEF"
    packet = header + payload

    seq, ts, ssrc, data = parse_rtp_header(packet)
    assert seq == 42
    assert ts == 12345
    assert ssrc == 99
    assert data == payload


def test_parse_rtp_header_with_extension():
    """RTP packets with header extension should skip the extension bytes."""
    from shannon.messaging.providers.discord_voice import parse_rtp_header

    # Extension bit set (0x90 instead of 0x80)
    header = struct.pack(">BBHII", 0x90, 120, 1, 100, 50)
    # Extension header: profile=0xBEDE, length=1 (1 * 4 bytes of extension data)
    ext_header = struct.pack(">HH", 0xBEDE, 1)
    ext_data = b"\x00\x00\x00\x00"
    payload = b"\xCA\xFE"
    packet = header + ext_header + ext_data + payload

    seq, ts, ssrc, data = parse_rtp_header(packet)
    assert seq == 1
    assert ssrc == 50
    assert data == payload


def test_parse_rtp_header_too_short():
    """Packets shorter than 12 bytes should return None."""
    from shannon.messaging.providers.discord_voice import parse_rtp_header
    assert parse_rtp_header(b"\x00" * 5) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_discord_voice.py -k "rtp" -v`
Expected: FAIL — `parse_rtp_header` doesn't exist.

- [ ] **Step 3: Implement RTP parser**

Add to `shannon/messaging/providers/discord_voice.py`:

```python
import struct


def parse_rtp_header(packet: bytes) -> tuple[int, int, int, bytes] | None:
    """Parse RTP header, return (sequence, timestamp, ssrc, payload) or None.

    Handles the optional header extension (X bit). Returns the payload bytes
    after the RTP header (and extension if present).
    """
    if len(packet) < 12:
        return None

    first_byte = packet[0]
    # version = (first_byte >> 6) & 0x03
    has_extension = bool(first_byte & 0x10)
    cc = first_byte & 0x0F  # CSRC count

    seq, ts, ssrc = struct.unpack_from(">HII", packet, 2)

    offset = 12 + cc * 4  # skip CSRC list

    if has_extension:
        if len(packet) < offset + 4:
            return None
        # Extension header: 2 bytes profile, 2 bytes length (in 32-bit words)
        ext_length = struct.unpack_from(">HH", packet, offset)[1]
        offset += 4 + ext_length * 4

    if offset > len(packet):
        return None

    return seq, ts, ssrc, packet[offset:]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_discord_voice.py -k "rtp" -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add shannon/messaging/providers/discord_voice.py tests/test_discord_voice.py
git commit -m "feat: add RTP header parser for Discord voice packets"
```

---

### Task 7: Per-User Audio Buffer with Silence Detection

**Files:**
- Modify: `shannon/messaging/providers/discord_voice.py`
- Modify: `tests/test_discord_voice.py`

- [ ] **Step 1: Write failing tests for UserAudioBuffer**

Add to `tests/test_discord_voice.py`:

```python
import time


def test_user_audio_buffer_append_and_drain():
    """Buffer accumulates PCM data and drain clears it."""
    from shannon.messaging.providers.discord_voice import UserAudioBuffer

    buf = UserAudioBuffer(max_seconds=30.0, sample_rate=48000, channels=2)
    buf.append(b"\x00" * 3840)  # 20ms frame
    buf.append(b"\x00" * 3840)

    assert buf.has_data
    data = buf.drain()
    assert len(data) == 7680
    assert not buf.has_data


def test_user_audio_buffer_caps_at_max():
    """Buffer should discard oldest data when exceeding max_seconds."""
    from shannon.messaging.providers.discord_voice import UserAudioBuffer

    # Max 0.1 seconds at 48kHz stereo = 48000 * 0.1 * 2 * 2 = 19200 bytes
    buf = UserAudioBuffer(max_seconds=0.1, sample_rate=48000, channels=2)

    # Add 0.2 seconds of data
    frame = b"\x00" * 3840  # 20ms
    for _ in range(10):  # 200ms
        buf.append(frame)

    data = buf.drain()
    max_bytes = int(48000 * 0.1 * 2 * 2)
    assert len(data) <= max_bytes + 3840  # allow one extra frame tolerance


def test_user_audio_buffer_silence_detection():
    """silence_seconds should reflect time since last append."""
    from shannon.messaging.providers.discord_voice import UserAudioBuffer

    buf = UserAudioBuffer(max_seconds=30.0, sample_rate=48000, channels=2)

    assert buf.silence_seconds > 0  # never had data

    buf.append(b"\x00" * 3840)
    assert buf.silence_seconds < 0.1  # just appended

    # Simulate time passing by backdating last_activity
    buf._last_activity = time.monotonic() - 3.0
    assert buf.silence_seconds >= 2.9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_discord_voice.py -k "user_audio_buffer" -v`
Expected: FAIL — `UserAudioBuffer` doesn't exist.

- [ ] **Step 3: Implement UserAudioBuffer**

Add to `shannon/messaging/providers/discord_voice.py`:

```python
import time


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_discord_voice.py -k "user_audio_buffer" -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add shannon/messaging/providers/discord_voice.py tests/test_discord_voice.py
git commit -m "feat: add per-user audio buffer with silence detection"
```

---

### Task 8: PCM AudioSource for Discord Playback

**Files:**
- Modify: `shannon/messaging/providers/discord_voice.py`
- Modify: `tests/test_discord_voice.py`

- [ ] **Step 1: Write failing tests for ChunkAudioSource**

Add to `tests/test_discord_voice.py`:

```python
def test_chunk_audio_source_reads_frames():
    """ChunkAudioSource should yield 3840-byte frames from resampled PCM."""
    from shannon.messaging.providers.discord_voice import ChunkAudioSource
    from shannon.output.providers.tts.base import AudioChunk

    # 100ms of 22050Hz mono silence
    num_samples = int(22050 * 0.1)
    chunk = AudioChunk(data=b"\x00" * (num_samples * 2), sample_rate=22050, channels=1)
    source = ChunkAudioSource(chunk)

    frames = []
    while True:
        frame = source.read()
        if not frame:
            break
        frames.append(frame)

    assert len(frames) > 0
    for frame in frames:
        assert len(frame) == 3840  # 20ms of 48kHz stereo 16-bit


def test_chunk_audio_source_is_not_opus():
    """ChunkAudioSource returns raw PCM, not opus."""
    from shannon.messaging.providers.discord_voice import ChunkAudioSource
    from shannon.output.providers.tts.base import AudioChunk

    chunk = AudioChunk(data=b"\x00" * 100, sample_rate=22050, channels=1)
    source = ChunkAudioSource(chunk)
    assert source.is_opus() is False


def test_chunk_audio_source_applies_volume():
    """Volume adjustment should scale PCM amplitude."""
    from shannon.messaging.providers.discord_voice import ChunkAudioSource
    from shannon.output.providers.tts.base import AudioChunk

    # Single 48kHz stereo frame of known values
    # 960 samples * 2 channels * 2 bytes = 3840 bytes
    sample_val = 10000
    samples = [sample_val, sample_val] * 960  # stereo pairs
    data = struct.pack(f"<{len(samples)}h", *samples)

    chunk = AudioChunk(data=data, sample_rate=48000, channels=2)
    source = ChunkAudioSource(chunk, volume=0.5)

    frame = source.read()
    # Unpack first sample pair
    left, right = struct.unpack_from("<hh", frame, 0)
    assert abs(left - 5000) < 100  # ~50% of 10000
    assert abs(right - 5000) < 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_discord_voice.py -k "chunk_audio_source" -v`
Expected: FAIL — `ChunkAudioSource` doesn't exist.

- [ ] **Step 3: Implement ChunkAudioSource**

Add to `shannon/messaging/providers/discord_voice.py`:

```python
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
            # Stereo but wrong rate — resample then pass through
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_discord_voice.py -k "chunk_audio_source" -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add shannon/messaging/providers/discord_voice.py tests/test_discord_voice.py
git commit -m "feat: add ChunkAudioSource for Discord TTS playback"
```

---

### Task 9: VoiceManager Core — Connection Lifecycle

**Files:**
- Modify: `shannon/messaging/providers/discord_voice.py`
- Modify: `tests/test_discord_voice.py`

- [ ] **Step 1: Write failing tests for VoiceManager connection lifecycle**

Add to `tests/test_discord_voice.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from shannon.bus import EventBus
from shannon.config import VoiceConfig
from shannon.events import VoiceStateChange


class FakeVoiceClient:
    """Mock discord.VoiceClient."""
    def __init__(self):
        self.is_connected_val = True
        self.disconnect = AsyncMock()
        self.play = MagicMock()
        self.is_playing = MagicMock(return_value=False)
        self._connection = MagicMock()
        self._connection.secret_key = [0] * 32
        self._connection.add_socket_listener = MagicMock()
        self._connection.remove_socket_listener = MagicMock()

    def is_connected(self):
        return self.is_connected_val


class FakeGuild:
    def __init__(self, guild_id="guild_1"):
        self.id = guild_id


class FakeVoiceChannel:
    def __init__(self, channel_id="vc_1", guild_id="guild_1"):
        self.id = channel_id
        self.guild = FakeGuild(guild_id)
        self.members = []
        self.connect = AsyncMock(return_value=FakeVoiceClient())


class FakeMember:
    def __init__(self, user_id="user_1", name="Alice", bot=False):
        self.id = user_id
        self.display_name = name
        self.bot = bot


class FakeVoiceState:
    def __init__(self, channel=None):
        self.channel = channel


def _make_voice_manager(**kwargs):
    from shannon.messaging.providers.discord_voice import VoiceManager
    bus = EventBus()
    client = MagicMock()
    client.voice_clients = []
    stt = AsyncMock()
    tts = AsyncMock()
    config = VoiceConfig(**kwargs)
    vm = VoiceManager(client=client, stt=stt, tts=tts, bus=bus, config=config)
    return vm, bus, client


@pytest.mark.asyncio
async def test_voice_manager_auto_joins_on_user_enter():
    """VoiceManager joins when a non-bot user enters a configured channel."""
    vm, bus, client = _make_voice_manager(
        enabled=True,
        auto_join_channels=["vc_1"],
    )
    client.voice_clients = []

    channel = FakeVoiceChannel("vc_1")
    channel.members = [FakeMember()]
    member = FakeMember("user_1", "Alice")
    before = FakeVoiceState(channel=None)
    after = FakeVoiceState(channel=channel)

    await vm.handle_voice_state_update(member, before, after)

    channel.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_manager_ignores_bot_joins():
    """VoiceManager should not join for bot users."""
    vm, bus, client = _make_voice_manager(enabled=True, auto_join_channels=["vc_1"])
    client.voice_clients = []

    channel = FakeVoiceChannel("vc_1")
    member = FakeMember("bot_1", "OtherBot", bot=True)
    before = FakeVoiceState(channel=None)
    after = FakeVoiceState(channel=channel)

    await vm.handle_voice_state_update(member, before, after)

    channel.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_manager_ignores_unconfigured_channels():
    """VoiceManager ignores channels not in auto_join_channels."""
    vm, bus, client = _make_voice_manager(
        enabled=True,
        auto_join_channels=["vc_99"],
    )
    client.voice_clients = []

    channel = FakeVoiceChannel("vc_1")
    member = FakeMember()
    before = FakeVoiceState(channel=None)
    after = FakeVoiceState(channel=channel)

    await vm.handle_voice_state_update(member, before, after)

    channel.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_manager_joins_any_channel_when_empty_list():
    """Empty auto_join_channels means join any voice channel."""
    vm, bus, client = _make_voice_manager(enabled=True, auto_join_channels=[])
    client.voice_clients = []

    channel = FakeVoiceChannel("vc_random")
    channel.members = [FakeMember()]
    member = FakeMember()
    before = FakeVoiceState(channel=None)
    after = FakeVoiceState(channel=channel)

    await vm.handle_voice_state_update(member, before, after)

    channel.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_manager_disconnects_when_empty():
    """VoiceManager disconnects when last non-bot user leaves."""
    vm, bus, client = _make_voice_manager(enabled=True, auto_join_channels=[])

    channel = FakeVoiceChannel("vc_1")
    fake_vc = FakeVoiceClient()
    vm._voice_clients["guild_1"] = fake_vc

    # Member leaves, channel now has only bots
    bot = FakeMember("bot_1", "Bot", bot=True)
    channel.members = [bot]
    member = FakeMember("user_1", "Alice")
    before = FakeVoiceState(channel=channel)
    after = FakeVoiceState(channel=None)

    await vm.handle_voice_state_update(member, before, after)

    fake_vc.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_manager_publishes_state_change():
    """Voice state changes should be published to the event bus."""
    vm, bus, client = _make_voice_manager(enabled=True, auto_join_channels=[])
    client.voice_clients = []

    received: list[VoiceStateChange] = []
    bus.subscribe(VoiceStateChange, lambda e: received.append(e))

    channel = FakeVoiceChannel("vc_1")
    channel.members = [FakeMember()]
    member = FakeMember("user_1", "Alice")
    before = FakeVoiceState(channel=None)
    after = FakeVoiceState(channel=channel)

    await vm.handle_voice_state_update(member, before, after)

    # Allow async handlers to run
    await asyncio.sleep(0)
    assert len(received) == 1
    assert received[0].user_id == "user_1"
    assert received[0].channel == "vc_1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_discord_voice.py -k "voice_manager" -v`
Expected: FAIL — `VoiceManager` doesn't exist.

- [ ] **Step 3: Implement VoiceManager connection lifecycle**

Add to `shannon/messaging/providers/discord_voice.py`:

```python
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shannon.bus import EventBus
    from shannon.config import VoiceConfig
    from shannon.input.providers.base import STTProvider
    from shannon.output.providers.tts.base import TTSProvider


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
        self._user_buffers: dict[str, UserAudioBuffer] = {}  # ssrc -> buffer
        self._ssrc_to_user: dict[int, tuple[str, str]] = {}  # ssrc -> (user_id, display_name)
        self._silence_task: asyncio.Task | None = None
        self._muted = False  # True during TTS playback

    async def start(self) -> None:
        """Register event handlers and start the silence monitor."""
        from shannon.events import VoiceOutput
        self._bus.subscribe(VoiceOutput, self._on_voice_output)
        self._silence_task = asyncio.create_task(self._silence_monitor())

    async def stop(self) -> None:
        """Disconnect all voice clients and cancel background tasks."""
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
        """Handle a discord.py on_voice_state_update event."""
        from shannon.events import VoiceStateChange

        if member.bot:
            return

        # Publish state change event
        new_channel = str(after.channel.id) if after.channel else None
        await self._bus.publish(VoiceStateChange(
            user_id=str(member.id),
            user_name=member.display_name,
            channel=new_channel,
        ))

        # User joined a voice channel
        if after.channel is not None and (before.channel is None or before.channel != after.channel):
            await self._maybe_join(after.channel)

        # User left a voice channel
        if before.channel is not None and (after.channel is None or after.channel != before.channel):
            await self._maybe_leave(before.channel)

    async def _maybe_join(self, channel: Any) -> None:
        """Join channel if configured and not already connected in this guild."""
        channel_id = str(channel.id)
        guild_id = str(channel.guild.id)

        # Check if channel is in our configured list (empty = any)
        if self._config.auto_join_channels and channel_id not in self._config.auto_join_channels:
            return

        # Already connected in this guild
        if guild_id in self._voice_clients:
            return

        # Check if there are non-bot members
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
        """Leave if the channel has no non-bot members left."""
        guild_id = str(channel.guild.id)
        vc = self._voice_clients.get(guild_id)
        if vc is None:
            return

        non_bots = [m for m in channel.members if not m.bot]
        if not non_bots:
            try:
                await vc.disconnect()
            except Exception:
                logger.debug("Error disconnecting from voice channel", exc_info=True)
            self._voice_clients.pop(guild_id, None)
            logger.info("Left voice channel in guild %s (empty)", guild_id)

    def _register_audio_listener(self, vc: Any) -> None:
        """Register a socket listener on the VoiceClient to receive raw UDP packets."""
        # Implemented in Task 10
        pass

    async def _silence_monitor(self) -> None:
        """Background task: poll buffers for silence gaps and trigger transcription."""
        # Implemented in Task 11
        while True:
            await asyncio.sleep(0.2)

    async def _on_voice_output(self, event: Any) -> None:
        """Handle VoiceOutput event: play TTS audio in the voice channel."""
        # Implemented in Task 12
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_discord_voice.py -k "voice_manager" -v`
Expected: All PASS.

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add shannon/messaging/providers/discord_voice.py tests/test_discord_voice.py
git commit -m "feat: add VoiceManager connection lifecycle (auto-join, auto-leave)"
```

---

### Task 10: Audio Capture — Socket Listener and Opus Decode

**Files:**
- Modify: `shannon/messaging/providers/discord_voice.py`
- Modify: `tests/test_discord_voice.py`

- [ ] **Step 1: Write failing tests for audio capture pipeline**

Add to `tests/test_discord_voice.py`:

```python
def test_voice_manager_socket_callback_buffers_audio():
    """Raw UDP packets should be parsed and buffered per SSRC."""
    from shannon.messaging.providers.discord_voice import VoiceManager

    vm, bus, client = _make_voice_manager(enabled=True)

    # Register a known SSRC -> user mapping
    vm._ssrc_to_user[99] = ("user_1", "Alice")

    # Build a fake RTP packet with SSRC=99
    header = struct.pack(">BBHII", 0x80, 120, 1, 100, 99)
    # Fake "decrypted opus payload" — we'll mock the decrypt step
    fake_pcm = b"\x00" * 3840  # 20ms of 48kHz stereo

    # Mock decrypt and opus decode to return known PCM
    with patch.object(vm, "_decrypt_payload", return_value=b"\x00\x00"):
        with patch.object(vm, "_decode_opus", return_value=fake_pcm):
            vm._on_udp_packet(header + b"\x00\x00")

    assert "99" in vm._user_buffers or 99 in vm._ssrc_to_user
    # Check buffer has data for this SSRC
    buf = vm._user_buffers.get(99)
    assert buf is not None
    assert buf.has_data


def test_voice_manager_ignores_unknown_ssrc():
    """Packets from unknown SSRCs should be silently dropped."""
    from shannon.messaging.providers.discord_voice import VoiceManager

    vm, bus, client = _make_voice_manager(enabled=True)
    # No SSRC mapping registered

    header = struct.pack(">BBHII", 0x80, 120, 1, 100, 999)

    with patch.object(vm, "_decrypt_payload", return_value=b"\x00"):
        vm._on_udp_packet(header + b"\x00")

    assert len(vm._user_buffers) == 0


def test_voice_manager_muted_skips_buffering():
    """When muted (during playback), packets should be dropped."""
    from shannon.messaging.providers.discord_voice import VoiceManager

    vm, bus, client = _make_voice_manager(enabled=True, mute_during_playback=True)
    vm._muted = True
    vm._ssrc_to_user[99] = ("user_1", "Alice")

    header = struct.pack(">BBHII", 0x80, 120, 1, 100, 99)

    with patch.object(vm, "_decrypt_payload", return_value=b"\x00"):
        with patch.object(vm, "_decode_opus", return_value=b"\x00" * 3840):
            vm._on_udp_packet(header + b"\x00")

    assert len(vm._user_buffers) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_discord_voice.py -k "socket_callback or unknown_ssrc or muted_skips" -v`
Expected: FAIL — methods don't exist.

- [ ] **Step 3: Implement audio capture pipeline**

Replace the stub `_register_audio_listener` and add supporting methods in `VoiceManager`:

```python
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
            return  # Unknown speaker, ignore

        decrypted = self._decrypt_payload(payload, data[:12])
        if decrypted is None:
            return

        pcm = self._decode_opus(decrypted)
        if pcm is None:
            return

        # Buffer the PCM data for this SSRC
        if ssrc not in self._user_buffers:
            self._user_buffers[ssrc] = UserAudioBuffer(
                max_seconds=self._config.buffer_max_seconds,
                sample_rate=48000,
                channels=2,
            )
        self._user_buffers[ssrc].append(pcm)

    def _decrypt_payload(self, payload: bytes, header: bytes) -> bytes | None:
        """Decrypt an RTP payload using the session secret key.

        Uses the VoiceClient's secret_key and the RTP header as nonce material.
        Returns decrypted bytes or None on failure.
        """
        # Find the voice client that has the secret key
        for vc in self._voice_clients.values():
            try:
                secret_key = bytes(vc._connection.secret_key)
                if not secret_key:
                    continue
                # Discord uses XSalsa20-Poly1305 or AEAD-AES256-GCM
                # Build nonce from RTP header (padded to 24 bytes for XSalsa20)
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
                import discord.opus  # type: ignore[import]
                if not discord.opus.is_loaded():
                    discord.opus._load_default()  # type: ignore[attr-defined]
                self._opus_decoder = discord.opus.Decoder()
            return self._opus_decoder.decode(opus_data)
        except Exception:
            logger.debug("Opus decode failed", exc_info=True)
            return None
```

Also add `self._opus_decoder = None` to `VoiceManager.__init__`.

Also update `_maybe_leave` to unregister the listener before disconnecting:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_discord_voice.py -k "socket_callback or unknown_ssrc or muted_skips" -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add shannon/messaging/providers/discord_voice.py tests/test_discord_voice.py
git commit -m "feat: add audio capture pipeline (socket listener, decrypt, opus decode)"
```

---

### Task 11: Silence Monitor and STT Transcription

**Files:**
- Modify: `shannon/messaging/providers/discord_voice.py`
- Modify: `tests/test_discord_voice.py`

- [ ] **Step 1: Write failing tests for silence-triggered transcription**

Add to `tests/test_discord_voice.py`:

```python
@pytest.mark.asyncio
async def test_silence_monitor_triggers_transcription():
    """When all speakers are silent past threshold, transcribe and publish VoiceInput."""
    from shannon.messaging.providers.discord_voice import VoiceManager, UserAudioBuffer
    from shannon.events import VoiceInput

    vm, bus, client = _make_voice_manager(enabled=True, silence_threshold=0.5)

    # Set up mock STT that returns fixed text
    vm._stt.transcribe = AsyncMock(return_value="hello world")

    # Simulate a user with buffered audio past the silence threshold
    buf = UserAudioBuffer(max_seconds=30.0, sample_rate=48000, channels=2)
    buf.append(b"\x00" * 3840)
    buf._last_activity = time.monotonic() - 1.0  # 1s ago, past 0.5s threshold
    vm._user_buffers[99] = buf
    vm._ssrc_to_user[99] = ("user_1", "Alice")

    # Track the voice channel for this guild
    fake_vc = FakeVoiceClient()
    fake_vc.channel = FakeVoiceChannel("vc_1")
    vm._voice_clients["guild_1"] = fake_vc

    received: list[VoiceInput] = []

    async def capture(event):
        received.append(event)

    bus.subscribe(VoiceInput, capture)

    await vm._check_silence_and_transcribe()

    assert len(received) == 1
    assert received[0].text == "Alice: hello world"
    assert received[0].speakers == {"user_1": "Alice"}
    assert received[0].channel == "vc_1"


@pytest.mark.asyncio
async def test_silence_monitor_skips_when_still_speaking():
    """Don't transcribe if speakers haven't been silent long enough."""
    from shannon.messaging.providers.discord_voice import VoiceManager, UserAudioBuffer
    from shannon.events import VoiceInput

    vm, bus, client = _make_voice_manager(enabled=True, silence_threshold=2.0)

    buf = UserAudioBuffer(max_seconds=30.0, sample_rate=48000, channels=2)
    buf.append(b"\x00" * 3840)
    # Still active (just appended)
    vm._user_buffers[99] = buf
    vm._ssrc_to_user[99] = ("user_1", "Alice")

    received: list[VoiceInput] = []
    bus.subscribe(VoiceInput, lambda e: received.append(e))

    await vm._check_silence_and_transcribe()

    assert len(received) == 0
    assert buf.has_data  # Buffer not drained


@pytest.mark.asyncio
async def test_silence_monitor_multiple_speakers():
    """Multiple speakers should each be transcribed independently."""
    from shannon.messaging.providers.discord_voice import VoiceManager, UserAudioBuffer
    from shannon.events import VoiceInput

    vm, bus, client = _make_voice_manager(enabled=True, silence_threshold=0.5)

    # STT returns different text for different audio
    call_count = 0

    async def mock_transcribe(audio):
        nonlocal call_count
        call_count += 1
        return f"text_{call_count}"

    vm._stt.transcribe = mock_transcribe

    # Two users, both past silence threshold
    for ssrc, uid, name in [(10, "u1", "Alice"), (20, "u2", "Bob")]:
        buf = UserAudioBuffer(max_seconds=30.0, sample_rate=48000, channels=2)
        buf.append(b"\x00" * 3840)
        buf._last_activity = time.monotonic() - 1.0
        vm._user_buffers[ssrc] = buf
        vm._ssrc_to_user[ssrc] = (uid, name)

    fake_vc = FakeVoiceClient()
    fake_vc.channel = FakeVoiceChannel("vc_1")
    vm._voice_clients["guild_1"] = fake_vc

    received: list[VoiceInput] = []
    bus.subscribe(VoiceInput, lambda e: received.append(e))

    await vm._check_silence_and_transcribe()

    assert len(received) == 1
    assert len(received[0].speakers) == 2
    # Both speakers appear in text
    assert "Alice:" in received[0].text
    assert "Bob:" in received[0].text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_discord_voice.py -k "silence_monitor" -v`
Expected: FAIL — `_check_silence_and_transcribe` doesn't exist.

- [ ] **Step 3: Implement silence monitoring and transcription**

Replace the `_silence_monitor` stub and add `_check_silence_and_transcribe`:

```python
    async def _silence_monitor(self) -> None:
        """Background task: poll buffers for silence gaps and trigger transcription."""
        try:
            while True:
                await asyncio.sleep(0.2)
                await self._check_silence_and_transcribe()
        except asyncio.CancelledError:
            pass

    async def _check_silence_and_transcribe(self) -> None:
        """Check if all active speakers are silent, and if so, transcribe their buffers."""
        from shannon.events import VoiceInput

        if not self._user_buffers:
            return

        # Check if ALL buffers with data have been silent past threshold
        active_buffers: list[tuple[int, UserAudioBuffer]] = [
            (ssrc, buf) for ssrc, buf in self._user_buffers.items() if buf.has_data
        ]
        if not active_buffers:
            return

        for _ssrc, buf in active_buffers:
            if buf.silence_seconds < self._config.silence_threshold:
                return  # Someone is still speaking, wait

        # All speakers are silent — transcribe each buffer
        speakers: dict[str, str] = {}
        text_parts: list[str] = []

        for ssrc, buf in active_buffers:
            user_info = self._ssrc_to_user.get(ssrc)
            if user_info is None:
                buf.drain()  # Discard orphaned buffer
                continue

            user_id, display_name = user_info
            pcm_48k_stereo = buf.drain()

            # Convert to 16kHz mono WAV for Whisper
            pcm_16k_mono = pcm_48k_stereo_to_16k_mono(pcm_48k_stereo)

            # Wrap in WAV for STT (Whisper expects WAV files)
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

        # Find the voice channel to tag the event
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
```

Also add the WAV helper at module level:

```python
import io
import wave


def _pcm_to_wav(pcm: bytes, sample_rate: int, channels: int) -> bytes:
    """Wrap raw 16-bit PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_discord_voice.py -k "silence_monitor" -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add shannon/messaging/providers/discord_voice.py tests/test_discord_voice.py
git commit -m "feat: add silence-gap batching and per-user STT transcription"
```

---

### Task 12: TTS Playback via VoiceOutput Event

**Files:**
- Modify: `shannon/messaging/providers/discord_voice.py`
- Modify: `tests/test_discord_voice.py`

- [ ] **Step 1: Write failing tests for TTS playback**

Add to `tests/test_discord_voice.py`:

```python
@pytest.mark.asyncio
async def test_voice_output_plays_audio():
    """VoiceOutput event should trigger playback on the correct voice client."""
    from shannon.messaging.providers.discord_voice import VoiceManager
    from shannon.output.providers.tts.base import AudioChunk
    from shannon.events import VoiceOutput

    vm, bus, client = _make_voice_manager(enabled=True, volume=1.0)

    fake_vc = FakeVoiceClient()
    fake_vc.channel = FakeVoiceChannel("vc_1")
    vm._voice_clients["guild_1"] = fake_vc

    chunk = AudioChunk(data=b"\x00" * 4410, sample_rate=22050, channels=1)
    event = VoiceOutput(audio=chunk, channel="vc_1")

    await vm._on_voice_output(event)

    fake_vc.play.assert_called_once()
    # First arg should be a ChunkAudioSource
    source = fake_vc.play.call_args[0][0]
    assert hasattr(source, "read")
    assert hasattr(source, "is_opus")


@pytest.mark.asyncio
async def test_voice_output_mutes_during_playback():
    """VoiceManager should set _muted=True while playing."""
    from shannon.messaging.providers.discord_voice import VoiceManager
    from shannon.output.providers.tts.base import AudioChunk
    from shannon.events import VoiceOutput

    vm, bus, client = _make_voice_manager(enabled=True, mute_during_playback=True)

    fake_vc = FakeVoiceClient()
    fake_vc.channel = FakeVoiceChannel("vc_1")
    fake_vc.is_playing = MagicMock(return_value=False)
    vm._voice_clients["guild_1"] = fake_vc

    chunk = AudioChunk(data=b"\x00" * 4410, sample_rate=22050, channels=1)
    event = VoiceOutput(audio=chunk, channel="vc_1")

    # Capture muted state during play
    muted_during_play = None

    original_play = fake_vc.play

    def capture_play(source, **kwargs):
        nonlocal muted_during_play
        muted_during_play = vm._muted

    fake_vc.play = capture_play

    await vm._on_voice_output(event)

    assert muted_during_play is True


@pytest.mark.asyncio
async def test_voice_output_no_matching_channel():
    """VoiceOutput for a channel we're not in should be silently dropped."""
    from shannon.messaging.providers.discord_voice import VoiceManager
    from shannon.output.providers.tts.base import AudioChunk
    from shannon.events import VoiceOutput

    vm, bus, client = _make_voice_manager(enabled=True)
    # No voice clients connected

    chunk = AudioChunk(data=b"\x00" * 100, sample_rate=22050, channels=1)
    event = VoiceOutput(audio=chunk, channel="nonexistent")

    # Should not raise
    await vm._on_voice_output(event)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_discord_voice.py -k "voice_output" -v`
Expected: FAIL — `_on_voice_output` is a stub.

- [ ] **Step 3: Implement TTS playback handler**

Replace the `_on_voice_output` stub in `VoiceManager`:

```python
    async def _on_voice_output(self, event: Any) -> None:
        """Handle VoiceOutput event: play TTS audio in the voice channel."""
        target_channel = event.channel

        # Find the voice client for this channel
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_discord_voice.py -k "voice_output" -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add shannon/messaging/providers/discord_voice.py tests/test_discord_voice.py
git commit -m "feat: add TTS playback via VoiceOutput event"
```

---

### Task 13: Brain VoiceInput Handler

**Files:**
- Modify: `shannon/brain/brain.py:15-78`
- Modify: `tests/test_brain.py`

- [ ] **Step 1: Write failing tests for VoiceInput handler**

Add to `tests/test_brain.py`:

```python
from shannon.events import VoiceInput, VoiceOutput


@pytest.mark.asyncio
async def test_brain_handles_voice_input():
    """VoiceInput should produce an LLMResponseEvent and a VoiceOutput."""
    bus, brain = _make_brain()

    llm_responses: list[LLMResponseEvent] = []
    voice_outputs: list[VoiceOutput] = []

    bus.subscribe(LLMResponseEvent, lambda e: llm_responses.append(e))
    bus.subscribe(VoiceOutput, lambda e: voice_outputs.append(e))
    await brain.start()

    await bus.publish(VoiceInput(
        text="Alice: Hello Shannon!",
        speakers={"123": "Alice"},
        channel="vc_1",
    ))

    assert len(llm_responses) == 1
    assert llm_responses[0].text == "Hello!"


@pytest.mark.asyncio
async def test_brain_voice_input_skipped_by_probability():
    """VoiceInput with reply_probability=0 should be silently dropped."""
    bus, brain = _make_brain()

    # Set voice reply probability to 0
    brain._config.messaging.voice.voice_reply_probability = 0.0

    llm_responses: list[LLMResponseEvent] = []
    bus.subscribe(LLMResponseEvent, lambda e: llm_responses.append(e))
    await brain.start()

    await bus.publish(VoiceInput(
        text="Alice: Hello!",
        speakers={"123": "Alice"},
        channel="vc_1",
    ))

    assert len(llm_responses) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_brain.py -k "voice_input" -v`
Expected: FAIL — Brain doesn't subscribe to VoiceInput.

- [ ] **Step 3: Add VoiceInput handler to Brain**

In `shannon/brain/brain.py`, add `VoiceInput` and `VoiceOutput` to the imports from `shannon.events` (line 15-23):

```python
from shannon.events import (
    AutonomousTrigger,
    ChatMessage,
    ChatResponse,
    ExpressionChange,
    LLMResponse as LLMResponseEvent,
    UserInput,
    VisionFrame,
    VoiceInput,
    VoiceOutput,
)
```

Add subscription in `start()` (after line 78):

```python
        self._bus.subscribe(VoiceInput, self._on_voice_input)
```

Add the handler method (after `_on_chat_message`, around line 168):

```python
    async def _on_voice_input(self, event: VoiceInput) -> None:
        """Handle transcribed voice channel speech."""
        import random

        logger.debug("Received VoiceInput from %s: %r", event.channel, event.text)

        # Check voice reply probability
        prob = self._config.messaging.voice.voice_reply_probability
        if prob < 1.0 and random.random() > prob:
            logger.debug("Skipping voice input (probability check)")
            return

        # Build dynamic context with speaker info
        suffix_parts: list[str] = []
        if event.speakers:
            names = list(event.speakers.values())
            suffix_parts.append(f"Voice channel participants: {', '.join(names)}")
        dynamic_context = "\n".join(suffix_parts)

        request = GenerationRequest(
            text=event.text,
            dynamic_context=dynamic_context,
            tool_mode="chat",
            channel_id=event.channel,
            participants=event.speakers,
        )
        responses = await self._process_input(request)

        # Synthesize TTS audio for voice channel playback
        if responses and any(r.strip() for r in responses):
            full_text = "\n".join(r for r in responses if r.strip())
            try:
                chunk = await self._tts.synthesize(full_text)
                await self._bus.publish(VoiceOutput(
                    audio=chunk,
                    channel=event.channel,
                ))
            except Exception:
                logger.exception("Failed to synthesize voice response")
```

This requires Brain to have access to the TTS provider. Modify `Brain.__init__` to accept an optional `tts` parameter:

```python
    def __init__(
        self,
        bus: EventBus,
        claude: ClaudeClient,
        dispatcher: ToolDispatcher,
        registry: ToolRegistry,
        config: ShannonConfig,
        tts: "TTSProvider | None" = None,
    ) -> None:
```

Add `self._tts = tts` in the body.

Add to the TYPE_CHECKING block:

```python
    from shannon.output.providers.tts.base import TTSProvider
```

- [ ] **Step 4: Update `_make_brain` test helper**

In `tests/test_brain.py`, update `_make_brain`:

```python
def _make_brain(fake_claude=None, fake_dispatcher=None, fake_registry=None):
    bus = EventBus()
    claude = fake_claude or FakeClaude()
    dispatcher = fake_dispatcher or FakeDispatcher()
    registry = fake_registry or FakeRegistry()
    config = ShannonConfig()
    brain = Brain(bus=bus, claude=claude, dispatcher=dispatcher, registry=registry, config=config)
    return bus, brain
```

No change needed — `tts` defaults to None, and `test_brain_handles_voice_input` doesn't need TTS to test the LLMResponse path. The VoiceOutput publish will silently be skipped when `self._tts is None`.

Actually, guard the TTS call:

```python
            if self._tts is not None:
                try:
                    chunk = await self._tts.synthesize(full_text)
                    await self._bus.publish(VoiceOutput(
                        audio=chunk,
                        channel=event.channel,
                    ))
                except Exception:
                    logger.exception("Failed to synthesize voice response")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_brain.py -k "voice_input" -v`
Expected: All PASS.

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass (existing brain tests unaffected since `tts` defaults to None).

- [ ] **Step 7: Commit**

```bash
git add shannon/brain/brain.py tests/test_brain.py
git commit -m "feat: add Brain._on_voice_input handler for Discord voice"
```

---

### Task 14: Wire VoiceManager in app.py

**Files:**
- Modify: `shannon/app.py:265-343`

- [ ] **Step 1: Add voice wiring in the messaging block**

In `shannon/app.py`, after the MessagingManager creation (around line 287), add:

```python
        # Voice support (requires --speech)
        voice_manager = None
        if msg_cfg.voice.enabled:
            if not speech_mode:
                raise ValueError(
                    "Voice requires --speech flag. "
                    "Run: shannon --speech"
                )
            try:
                import nacl  # noqa: F401
            except ImportError:
                raise ValueError(
                    "Voice enabled but PyNaCl not installed. "
                    "Install with: pip install 'shannon[voice]'"
                )
            from shannon.messaging.providers.discord_voice import VoiceManager
            # discord_provider is the first (and only) messaging provider
            discord_provider = messaging_providers[0] if messaging_providers else None
            if discord_provider is not None:
                voice_manager = VoiceManager(
                    client=discord_provider.client,
                    stt=stt_provider,
                    tts=tts_provider,
                    bus=bus,
                    config=msg_cfg.voice,
                )
```

Note: at this point `discord_provider.client` may be `None` because `connect()` hasn't been called yet. VoiceManager needs the client to register voice state events. Two options:

(a) Wire VoiceManager after `messaging_manager.start()` (which calls `connect()` on providers), or
(b) Have VoiceManager's `start()` accept the client lazily.

Option (a) is simpler. Move the voice wiring to after `await messaging_manager.start()`:

```python
        await messaging_manager.start()

        # Voice support (requires --speech and messaging)
        voice_manager = None
        if msg_cfg.voice.enabled:
            if not speech_mode:
                raise ValueError(
                    "Voice requires --speech flag. "
                    "Run: shannon --speech"
                )
            try:
                import nacl  # noqa: F401
            except ImportError:
                raise ValueError(
                    "Voice enabled but PyNaCl not installed. "
                    "Install with: pip install 'shannon[voice]'"
                )
            from shannon.messaging.providers.discord_voice import VoiceManager
            discord_provider = messaging_providers[0] if messaging_providers else None
            if discord_provider is not None and discord_provider.client is not None:
                voice_manager = VoiceManager(
                    client=discord_provider.client,
                    stt=stt_provider,
                    tts=tts_provider,
                    bus=bus,
                    config=msg_cfg.voice,
                )
                await voice_manager.start()

                # Register voice state update handler on the discord client
                @discord_provider.client.event
                async def on_voice_state_update(member, before, after):
                    await voice_manager.handle_voice_state_update(member, before, after)

                logger.info("Discord voice support enabled")
```

- [ ] **Step 2: Pass TTS to Brain**

In the Brain creation section of `app.py` (around line 135), add the `tts` parameter:

```python
    brain = Brain(
        bus=bus,
        claude=claude,
        dispatcher=dispatcher,
        registry=registry,
        config=config,
        tts=tts_provider,  # For voice channel TTS synthesis
    )
```

- [ ] **Step 3: Update shutdown sequence**

In the shutdown block (around line 311), add voice manager stop before messaging:

```python
        # Stop voice before messaging
        if voice_manager is not None:
            await voice_manager.stop()

        await messaging_manager.stop()
```

- [ ] **Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add shannon/app.py
git commit -m "feat: wire VoiceManager in app.py with startup validation"
```

---

### Task 15: Update pyproject.toml and CLAUDE.md

**Files:**
- Modify: `pyproject.toml` (done in Task 3, verify)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Verify pyproject.toml has voice group**

Confirm `pyproject.toml` contains:

```toml
voice = ["PyNaCl>=1.5.0", "davey>=0.1.0"]
all = ["shannon[computer,vision,tts,stt,vtuber,messaging,voice]"]
```

- [ ] **Step 2: Update CLAUDE.md with voice documentation**

Add to the tool table in CLAUDE.md (in the "Tool Set" section):

No new tools are added — voice is not an LLM tool, it's an I/O channel.

Add a new section after "Continue (Multi-Message) System":

```markdown
## Discord Voice Channels

Shannon can join Discord voice channels for full-duplex audio communication. Requires `--speech` flag and `messaging.voice.enabled: true`.

**How it works:** VoiceManager auto-joins configured voice channels when users enter, captures per-user audio via raw UDP socket listener (RTP parse → decrypt → opus decode → PCM buffer), batches on silence gaps, transcribes via Whisper STT, and sends the combined input to the brain. Responses are synthesized via Piper TTS and played back through the VoiceClient.

**Config fields:** `messaging.voice.enabled` (default false), `messaging.voice.auto_join_channels` (list of channel IDs, empty = any), `messaging.voice.silence_threshold` (0.5-10.0, default 2.0), `messaging.voice.buffer_max_seconds` (5.0-60.0, default 30.0), `messaging.voice.voice_reply_probability` (0-1, default 1.0), `messaging.voice.mute_during_playback` (default true), `messaging.voice.volume` (0-2, default 1.0).

**Dependencies:** `PyNaCl`, `davey`, system `libopus`. Install with `pip install 'shannon[voice]'`.
```

Add to the Event Flow section:

```markdown
Voice: **User speaks in VC** → VoiceManager captures per-user audio → silence gap → Whisper STT → `VoiceInput` → **Brain** → `LLMResponse` (CLI) + `VoiceOutput` → **VoiceManager** plays TTS in VC
```

Update the Project Layout to include the new file:

```
├── messaging/          # MessagingManager + MessagingProvider (discord.py, discord_voice.py)
```

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CLAUDE.md
git commit -m "docs: add Discord voice channel support to CLAUDE.md"
```

---

### Task 16: Integration Test — Full Voice Flow

**Files:**
- Modify: `tests/test_discord_voice.py`

- [ ] **Step 1: Write integration test**

Add to `tests/test_discord_voice.py`:

```python
@pytest.mark.asyncio
async def test_full_voice_flow_integration():
    """End-to-end: audio buffer -> silence -> STT -> Brain -> TTS -> VoiceOutput."""
    from shannon.messaging.providers.discord_voice import (
        VoiceManager, UserAudioBuffer, _pcm_to_wav,
    )
    from shannon.events import VoiceInput, VoiceOutput, LLMResponse as LLMResponseEvent
    from shannon.output.providers.tts.base import AudioChunk

    vm, bus, client = _make_voice_manager(enabled=True, silence_threshold=0.3)

    # Mock STT: return fixed transcript
    vm._stt.transcribe = AsyncMock(return_value="Hey Shannon")

    # Set up user buffer with data past silence threshold
    buf = UserAudioBuffer(max_seconds=30.0, sample_rate=48000, channels=2)
    buf.append(b"\x00" * 3840)
    buf._last_activity = time.monotonic() - 1.0
    vm._user_buffers[42] = buf
    vm._ssrc_to_user[42] = ("user_1", "TestUser")

    fake_vc = FakeVoiceClient()
    fake_vc.channel = FakeVoiceChannel("vc_1")
    vm._voice_clients["guild_1"] = fake_vc

    # Collect all published events
    voice_inputs: list[VoiceInput] = []
    bus.subscribe(VoiceInput, lambda e: voice_inputs.append(e))

    # Trigger the silence check
    await vm._check_silence_and_transcribe()

    # VoiceInput should have been published
    assert len(voice_inputs) == 1
    assert "TestUser: Hey Shannon" in voice_inputs[0].text
    assert voice_inputs[0].speakers == {"user_1": "TestUser"}
    assert voice_inputs[0].channel == "vc_1"
```

- [ ] **Step 2: Run the integration test**

Run: `python3 -m pytest tests/test_discord_voice.py -k "full_voice_flow" -v`
Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_discord_voice.py
git commit -m "test: add full voice flow integration test"
```

---

### Task 17: SSRC-to-User Mapping via SPEAKING Events

**Files:**
- Modify: `shannon/messaging/providers/discord_voice.py`
- Modify: `tests/test_discord_voice.py`

This task fills in the SSRC→user mapping that Tasks 10-11 depend on in production. Discord's voice gateway sends SPEAKING (opcode 5) events containing `{user_id, ssrc, speaking}`. VoiceManager needs to capture these.

- [ ] **Step 1: Write failing test for SSRC mapping**

Add to `tests/test_discord_voice.py`:

```python
def test_voice_manager_registers_ssrc_from_speaking():
    """handle_speaking_update should map SSRC to user."""
    vm, bus, client = _make_voice_manager(enabled=True)

    vm.handle_speaking_update(user_id="user_1", ssrc=42, display_name="Alice")

    assert 42 in vm._ssrc_to_user
    assert vm._ssrc_to_user[42] == ("user_1", "Alice")


def test_voice_manager_updates_ssrc_mapping():
    """If the same user gets a new SSRC, the old mapping should be removed."""
    vm, bus, client = _make_voice_manager(enabled=True)

    vm.handle_speaking_update(user_id="user_1", ssrc=10, display_name="Alice")
    vm.handle_speaking_update(user_id="user_1", ssrc=20, display_name="Alice")

    assert 10 not in vm._ssrc_to_user
    assert 20 in vm._ssrc_to_user
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_discord_voice.py -k "ssrc" -v`
Expected: FAIL — method doesn't exist.

- [ ] **Step 3: Implement handle_speaking_update**

Add to `VoiceManager`:

```python
    def handle_speaking_update(self, user_id: str, ssrc: int, display_name: str) -> None:
        """Register or update SSRC-to-user mapping from a SPEAKING event."""
        # Remove old mapping for this user (SSRC may change)
        old_ssrcs = [s for s, (uid, _) in self._ssrc_to_user.items() if uid == user_id]
        for old_ssrc in old_ssrcs:
            del self._ssrc_to_user[old_ssrc]
        self._ssrc_to_user[ssrc] = (user_id, display_name)
        logger.debug("SSRC %d -> user %s (%s)", ssrc, user_id, display_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_discord_voice.py -k "ssrc" -v`
Expected: All PASS.

- [ ] **Step 5: Hook into discord.py's voice websocket**

The SPEAKING event comes through the voice websocket, not the main gateway. To capture it, VoiceManager needs to hook into the VoiceClient's internal websocket handling. In `_register_audio_listener`, add the speaking hook.

This requires monkey-patching the voice websocket's `received_message` to intercept SPEAKING (opcode 5) events. Add to `_register_audio_listener`:

```python
    def _register_audio_listener(self, vc: Any) -> None:
        """Register socket listener and speaking event hook."""
        try:
            vc._connection.add_socket_listener(self._on_udp_packet)
        except Exception:
            logger.exception("Failed to register socket listener")

        # Hook into the voice websocket to capture SPEAKING events for SSRC mapping.
        # Discord sends opcode 5 with {user_id, ssrc, speaking} when users start/stop speaking.
        self._hook_speaking_events(vc)

    def _hook_speaking_events(self, vc: Any) -> None:
        """Monkey-patch the voice websocket to intercept SPEAKING events."""
        try:
            ws = vc.ws
            if ws is None:
                return
            original_received = ws.received_message

            async def patched_received(msg: Any) -> None:
                # Intercept SPEAKING (opcode 5)
                if isinstance(msg, dict) and msg.get("op") == 5:
                    data = msg.get("d", {})
                    user_id = data.get("user_id", "")
                    ssrc = data.get("ssrc", 0)
                    if user_id and ssrc:
                        # Look up display name from guild members
                        display_name = str(user_id)  # fallback
                        if hasattr(vc, "channel") and vc.channel:
                            for m in vc.channel.members:
                                if str(m.id) == str(user_id):
                                    display_name = m.display_name
                                    break
                        self.handle_speaking_update(str(user_id), ssrc, display_name)
                await original_received(msg)

            ws.received_message = patched_received
        except Exception:
            logger.debug("Failed to hook speaking events", exc_info=True)
```

Note: This monkey-patching approach is fragile and depends on discord.py internals. It's the known risk area identified in the spec. If discord.py changes its voice websocket structure, this will break. The fallback is to look for SSRC mappings from `CLIENTS_CONNECT` events instead.

- [ ] **Step 6: Commit**

```bash
git add shannon/messaging/providers/discord_voice.py tests/test_discord_voice.py
git commit -m "feat: add SSRC-to-user mapping from SPEAKING events"
```

---

### Task 18: Final Validation

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python3 -c "from shannon.messaging.providers.discord_voice import VoiceManager; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verify config loads with voice section**

Run: `python3 -c "from shannon.config import ShannonConfig; c = ShannonConfig(); print(c.messaging.voice.enabled)"`
Expected: `False`

- [ ] **Step 4: Verify dependencies install**

Run: `pip install -e '.[all,dev]' && python3 -c "import nacl; import davey; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit any final fixes**

If any test failures were found and fixed, commit them.

```bash
git add -A
git commit -m "fix: address test failures from voice support integration"
```
