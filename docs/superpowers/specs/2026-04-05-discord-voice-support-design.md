# Discord Voice Channel Support

## Overview

Add full-duplex voice support to Shannon's Discord integration. Shannon auto-joins configured voice channels when users enter, listens to per-user speech via STT, and responds with TTS audio playback. Voice responses also print to CLI via the existing OutputManager path.

## Requirements

- Requires `--speech` flag (TTS and STT providers must be available)
- Requires `messaging.voice.enabled: true` in config
- Requires `PyNaCl` and `davey` packages (new `voice` optional dep group)
- Requires system `libopus` for opus decoding (discord.py provides `discord.opus.Decoder` wrapper)

## Architecture

### New File: `shannon/messaging/providers/discord_voice.py`

`VoiceManager` class — owned by `DiscordProvider`, receives the `discord.Client` instance.

**Responsibilities:**

1. **Connection lifecycle** — monitors `on_voice_state_update`. When a non-bot user joins a configured voice channel and the bot isn't connected in that guild, join. When the last non-bot user leaves, disconnect. One `VoiceClient` per guild (Discord limitation).

2. **Audio capture** — registers a callback via `VoiceClient._connection.add_socket_listener()` to receive raw UDP packets from the voice socket. discord.py 2.7.1 has no high-level `AudioSink` API, so VoiceManager must handle the full receive pipeline:
   - Parse RTP headers (12 bytes: version, payload type, sequence, timestamp, SSRC)
   - Decrypt payload using the session's `secret_key` (AES256-GCM AEAD, via PyNaCl)
   - If DAVE E2EE is active, decrypt the DAVE layer via `davey.DaveSession`
   - Map SSRC to user ID using `CLIENTS_CONNECT` / `CLIENT_CONNECT` voice gateway events
   - Decode opus frames to PCM via `discord.opus.Decoder` (already available, wraps system libopus)
   - Append PCM to per-user `bytearray` buffers (capped at `buffer_max_seconds`)
   - Track last-packet timestamp per user for silence detection

3. **Silence-gap batching** — background task polls every 200ms. When all active speakers have been silent for `silence_threshold` seconds, collects non-empty buffers, transcribes each via `STTProvider`, clears buffers, publishes `VoiceInput` event with speaker attribution.

4. **TTS playback** — subscribes to `VoiceOutput` event. Wraps `AudioChunk` in a custom `discord.AudioSource` subclass (resampled to 48kHz stereo for Discord). Queues sequentially if already playing.

5. **Echo prevention** — pauses audio capture while playing TTS to avoid Shannon hearing herself.

**Class interface:**

```python
class VoiceManager:
    def __init__(self, client: discord.Client, stt: STTProvider,
                 tts: TTSProvider, bus: EventBus, config: VoiceConfig):
        ...

    async def start(self) -> None       # register events, start silence monitor
    async def stop(self) -> None        # disconnect all, cancel tasks
    async def _on_voice_state(self, member, before, after) -> None
    async def _silence_monitor(self) -> None
    async def _play_audio(self, chunk: AudioChunk) -> None
```

### New Events in `shannon/events.py`

```python
@dataclass
class VoiceInput:
    """Batched transcription from voice channel after silence gap."""
    text: str                       # combined transcription
    speakers: dict[str, str]        # user_id -> display_name
    channel: str                    # voice channel ID
    platform: str = "discord"

@dataclass
class VoiceStateChange:
    """User joined/left a voice channel."""
    user_id: str
    user_name: str
    channel: str | None             # None = left all voice
    platform: str = "discord"

@dataclass
class VoiceOutput:
    """TTS audio to play in a voice channel."""
    audio: AudioChunk
    channel: str                    # voice channel ID
    platform: str = "discord"
```

### Brain Integration

New handler `Brain._on_voice_input` subscribes to `VoiceInput`:

- Formats speaker-attributed transcription into message context (e.g., "In voice channel: Alice said '...', Bob said '...'")
- Checks `voice_reply_probability` to decide whether to respond
- Sends to LLM with `source: "voice_channel"` tag in history (signals conversational tone)
- On response: publishes `LLMResponse` (OutputManager prints to CLI) and `VoiceOutput` (VoiceManager plays in Discord)
- Voice interactions go into conversation history same as chat

### DiscordProvider Changes

- Expose `client` property (currently private)
- Add `voice_states` to `Intents`
- No other changes — text messaging untouched

## Data Flow

### Voice Input (Listening)

```
User speaks in VC
    |
SocketReader callback receives raw UDP packets
    |
VoiceManager parses RTP, decrypts, maps SSRC -> user, decodes opus -> PCM, buffers per-user
    |
Silence gap detected (all speakers silent for threshold)
    |
WhisperProvider.transcribe() for each user's buffer
    |
VoiceInput event published (combined text, speaker attribution)
    |
Brain._on_voice_input processes
    |
LLM generates response
```

### Voice Output (Speaking)

```
Brain publishes LLMResponse + VoiceOutput
    |                |
    v                v
OutputManager    VoiceManager
prints to CLI    resamples AudioChunk to 48kHz stereo
                     |
                 custom AudioSource feeds frames
                     |
                 VoiceClient.play()
                     |
                 Audio plays in Discord VC
```

## Voice Receive Pipeline (Low-Level Details)

discord.py 2.7.1 exposes raw UDP voice packets via `VoiceConnectionState.add_socket_listener(callback)`. The callback receives raw `bytes` from the voice UDP socket. VoiceManager must implement the full decode chain:

### 1. RTP Header Parsing

Discord voice packets use standard RTP format:
- Bytes 0-1: version (2), padding, extension, CSRC count, marker, payload type
- Bytes 2-3: sequence number (big-endian uint16)
- Bytes 4-7: timestamp (big-endian uint32)
- Bytes 8-11: SSRC (big-endian uint32) — identifies the sender

### 2. Decryption

Discord uses AEAD encryption (AES256-GCM or XSalsa20-Poly1305 depending on negotiated mode). The `secret_key` is available from `VoiceConnectionState.secret_key` after session establishment. Decrypt the payload after the RTP header using PyNaCl.

If DAVE E2EE is active (discord.py negotiates this automatically when `davey` is installed), there's a second encryption layer handled by `davey.DaveSession`. The VoiceManager accesses this via the VoiceConnectionState's `dave_session`.

### 3. SSRC to User Mapping

Discord's voice gateway sends `CLIENTS_CONNECT` (opcode 11) and `CLIENT_CONNECT` (opcode 12) events containing SSRC-to-user-ID mappings. VoiceManager must hook into the voice websocket to capture these. The `DiscordVoiceWebSocket.received_message` handler processes these opcodes — VoiceManager can register a listener or monkey-patch to intercept the mapping data.

Alternative: the gateway also dispatches `SPEAKING` (opcode 5) events with `{user_id, ssrc, speaking}` — this is simpler to capture and sufficient for mapping.

### 4. Opus Decode

Decrypted payload is opus-encoded audio (48kHz, stereo). Decode to PCM using `discord.opus.Decoder`. Each packet decodes to a 20ms frame (3840 bytes at 48kHz stereo 16-bit). discord.py already wraps libopus via ctypes — no additional Python opus library needed, just the system `libopus` shared library (usually present on macOS via Homebrew or bundled with discord.py's voice extras).

## Audio Format Conversion

### Capture path (Discord -> Whisper)

Discord provides 48kHz stereo PCM. Whisper expects 16kHz mono WAV.

- Stereo to mono via `audioop.tomono()` (from `audioop-lts`, already in deps)
- 48kHz to 16kHz via `audioop.ratecv()`
- Wrap in WAV header for Whisper's temp-file transcription path

### Playback path (Piper -> Discord)

Piper produces mono PCM at model sample rate (typically 22050Hz). Discord expects 48kHz stereo.

- Resample to 48kHz via `audioop.ratecv()`
- Mono to stereo via `audioop.tostereo()`
- Feed 20ms frames (3840 bytes at 48kHz stereo 16-bit) via `AudioSource.read()`

## Configuration

### New `VoiceConfig` dataclass in `shannon/config.py`

```python
@dataclass
class VoiceConfig:
    enabled: bool = False
    auto_join_channels: list[str] = field(default_factory=list)  # channel IDs; empty = any
    silence_threshold: float = 2.0       # seconds before transcribing
    buffer_max_seconds: float = 30.0     # per-user ring buffer cap
    voice_reply_probability: float = 1.0 # response probability
    mute_during_playback: bool = True    # pause capture while speaking
    volume: float = 1.0                  # playback volume
```

Nested under `MessagingConfig` as `voice: VoiceConfig`.

**Validation (`__post_init__`):**

- `silence_threshold`: clamp 0.5-10.0
- `buffer_max_seconds`: clamp 5.0-60.0
- `voice_reply_probability`: clamp 0.0-1.0
- `volume`: clamp 0.0-2.0

### Example config.yaml

```yaml
messaging:
  enabled: true
  token: "bot-token-here"
  voice:
    enabled: true
    auto_join_channels: ["123456789012345678"]
    silence_threshold: 2.0
    voice_reply_probability: 1.0
    volume: 1.0
```

## Dependencies

New optional group in `pyproject.toml`:

```toml
voice = ["PyNaCl>=1.5.0", "davey>=0.1.0"]
all = ["shannon[computer,vision,tts,stt,vtuber,messaging,voice]"]
```

Voice also requires `tts` and `stt` deps (Piper, Whisper). Startup validation checks all are importable when `voice.enabled` is true.

## App Wiring (`app.py`)

Voice setup goes inside the existing messaging block, after DiscordProvider creation:

```python
if config.messaging.voice.enabled:
    if not speech_mode:
        raise ValueError("Voice requires --speech flag")
    try:
        import nacl  # noqa: F401
    except ImportError:
        raise ValueError("Voice enabled but PyNaCl not installed. pip install 'shannon[voice]'")

    voice_manager = VoiceManager(
        client=discord_provider.client,
        stt=whisper_provider,
        tts=piper_provider,
        bus=bus,
        config=config.messaging.voice,
    )
    await voice_manager.start()
```

**Shutdown order:** `voice_manager.stop()` before `messaging_manager.stop()` — disconnect voice before text.

## Discord Intents

`DiscordProvider` must include `Intents.voice_states` when voice is enabled. Currently only `message_content` is set as a privileged intent. Voice states is a non-privileged intent but must be explicitly enabled.

## Known Risks

1. **No high-level audio receive API** — discord.py 2.7.1 provides only raw UDP socket callbacks, not a structured `AudioSink`. VoiceManager must implement RTP parsing, AEAD decryption, SSRC→user mapping, and opus decoding manually. This is the bulk of the implementation complexity. If it proves too fragile, fallback is speak-only mode (Shannon talks in VC but doesn't hear users; they'd type in text chat to interact).

2. **Opus decode quality** — we use `discord.opus.Decoder` (ctypes wrapper around system libopus). Edge cases (packet loss, silence frames, out-of-order packets) may produce artifacts. The decoder supports FEC (forward error correction) and packet loss concealment (`decode(None, fec=False)` generates comfort noise). Packet reordering is mitigated by RTP sequence numbers.

3. **Whisper latency** — transcription adds latency on top of the silence gap. For a 2s silence threshold plus ~1-2s transcription, Shannon's response lag is 3-4s minimum. Acceptable for conversational flow but worth noting.

4. **Concurrent speakers** — if many people talk simultaneously, we transcribe each buffer independently. This scales linearly with speaker count. For large channels, consider a max-speakers cap.

## Testing Strategy

- Unit tests: RTP header parsing with synthetic packet bytes
- Unit tests: SSRC-to-user mapping from mock SPEAKING events
- Unit tests: audio format conversion (48kHz stereo <-> 16kHz mono, sample rate conversion)
- Unit tests: silence detection logic with synthetic timestamp sequences
- Unit tests: per-user buffer management (accumulation, capping, clearing)
- Unit tests: AudioSource subclass (frame sizing, resampling correctness)
- Unit tests: brain VoiceInput handler with mocked ClaudeClient
- Unit tests: VoiceManager connection lifecycle (auto-join, auto-leave)
- Integration: mock the full flow from raw UDP packet through to VoiceOutput event
- No real Discord connections in tests (same pattern as existing messaging tests)
- Decryption tested with known-good packet + key pairs (not live Discord)
