"""Tests for Discord voice support."""

import asyncio
import struct
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shannon.bus import EventBus
from shannon.config import VoiceConfig
from shannon.events import VoiceStateChange


# ---------------------------------------------------------------------------
# VoiceManager test helpers
# ---------------------------------------------------------------------------

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
    vm, bus, client = _make_voice_manager(enabled=True, auto_join_channels=["vc_1"])
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
    vm, bus, client = _make_voice_manager(enabled=True, auto_join_channels=["vc_99"])
    client.voice_clients = []

    channel = FakeVoiceChannel("vc_1")
    member = FakeMember()
    before = FakeVoiceState(channel=None)
    after = FakeVoiceState(channel=channel)

    await vm.handle_voice_state_update(member, before, after)
    channel.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_manager_joins_any_channel_when_empty_list():
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
    vm, bus, client = _make_voice_manager(enabled=True, auto_join_channels=[])

    channel = FakeVoiceChannel("vc_1")
    fake_vc = FakeVoiceClient()
    vm._voice_clients["guild_1"] = fake_vc

    bot = FakeMember("bot_1", "Bot", bot=True)
    channel.members = [bot]
    member = FakeMember("user_1", "Alice")
    before = FakeVoiceState(channel=channel)
    after = FakeVoiceState(channel=None)

    await vm.handle_voice_state_update(member, before, after)
    fake_vc.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_manager_publishes_state_change():
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
    await asyncio.sleep(0)
    assert len(received) == 1
    assert received[0].user_id == "user_1"
    assert received[0].channel == "vc_1"


# ---------------------------------------------------------------------------
# Audio conversion tests
# ---------------------------------------------------------------------------

def test_pcm_48k_stereo_to_16k_mono():
    """Convert 48kHz stereo PCM to 16kHz mono for Whisper."""
    from shannon.messaging.providers.discord_voice import pcm_48k_stereo_to_16k_mono

    # Generate 20ms of 48kHz stereo silence (3840 bytes)
    data_48k_stereo = b"\x00" * 3840
    result = pcm_48k_stereo_to_16k_mono(data_48k_stereo)

    # Should produce data (exact size depends on audioop.ratecv state)
    assert len(result) > 0
    # All silence in = all silence out
    assert all(b == 0 for b in result)


def test_pcm_mono_to_48k_stereo():
    """Convert TTS PCM (arbitrary rate, mono) to 48kHz stereo for Discord."""
    from shannon.messaging.providers.discord_voice import pcm_mono_to_48k_stereo

    # 20ms of 22050Hz mono silence
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


# ---------------------------------------------------------------------------
# RTP header parsing tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# UserAudioBuffer tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ChunkAudioSource tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Audio capture pipeline tests (Task 10)
# ---------------------------------------------------------------------------

def test_voice_manager_socket_callback_buffers_audio():
    """Raw UDP packets should be parsed and buffered per SSRC."""
    from shannon.messaging.providers.discord_voice import VoiceManager

    vm, bus, client = _make_voice_manager(enabled=True)

    # Register a known SSRC -> user mapping
    vm._ssrc_to_user[99] = ("user_1", "Alice")

    # Build a fake RTP packet with SSRC=99
    header = struct.pack(">BBHII", 0x80, 120, 1, 100, 99)
    fake_pcm = b"\x00" * 3840  # 20ms of 48kHz stereo

    # Mock decrypt and opus decode to return known PCM
    with patch.object(vm, "_decrypt_payload", return_value=b"\x00\x00"):
        with patch.object(vm, "_decode_opus", return_value=fake_pcm):
            vm._on_udp_packet(header + b"\x00\x00")

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


# ---------------------------------------------------------------------------
# Silence monitor / STT transcription tests (Task 11)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_silence_monitor_triggers_transcription():
    """When all speakers are silent past threshold, transcribe and publish VoiceInput."""
    from shannon.messaging.providers.discord_voice import VoiceManager, UserAudioBuffer
    from shannon.events import VoiceInput

    vm, bus, client = _make_voice_manager(enabled=True, silence_threshold=0.5)
    vm._stt.transcribe = AsyncMock(return_value="hello world")

    buf = UserAudioBuffer(max_seconds=30.0, sample_rate=48000, channels=2)
    buf.append(b"\x00" * 3840)
    buf._last_activity = time.monotonic() - 1.0  # 1s ago, past 0.5s threshold
    vm._user_buffers[99] = buf
    vm._ssrc_to_user[99] = ("user_1", "Alice")

    fake_vc = FakeVoiceClient()
    fake_vc.channel = FakeVoiceChannel("vc_1")
    vm._voice_clients["guild_1"] = fake_vc

    received: list[VoiceInput] = []
    bus.subscribe(VoiceInput, lambda e: received.append(e))

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

    muted_during_play = None
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

    chunk = AudioChunk(data=b"\x00" * 100, sample_rate=22050, channels=1)
    event = VoiceOutput(audio=chunk, channel="nonexistent")

    await vm._on_voice_output(event)  # Should not raise


@pytest.mark.asyncio
async def test_silence_monitor_multiple_speakers():
    """Multiple speakers should each be transcribed independently."""
    from shannon.messaging.providers.discord_voice import VoiceManager, UserAudioBuffer
    from shannon.events import VoiceInput

    vm, bus, client = _make_voice_manager(enabled=True, silence_threshold=0.5)

    call_count = 0
    async def mock_transcribe(audio):
        nonlocal call_count
        call_count += 1
        return f"text_{call_count}"

    vm._stt.transcribe = mock_transcribe

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
    assert "Alice:" in received[0].text
    assert "Bob:" in received[0].text


# ---------------------------------------------------------------------------
# Integration test — full voice flow (Task 16)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_voice_flow_integration():
    """End-to-end: audio buffer -> silence -> STT -> VoiceInput."""
    from shannon.messaging.providers.discord_voice import VoiceManager, UserAudioBuffer
    from shannon.events import VoiceInput

    vm, bus, client = _make_voice_manager(enabled=True, silence_threshold=0.3)
    vm._stt.transcribe = AsyncMock(return_value="Hey Shannon")

    buf = UserAudioBuffer(max_seconds=30.0, sample_rate=48000, channels=2)
    buf.append(b"\x00" * 3840)
    buf._last_activity = time.monotonic() - 1.0
    vm._user_buffers[42] = buf
    vm._ssrc_to_user[42] = ("user_1", "TestUser")

    fake_vc = FakeVoiceClient()
    fake_vc.channel = FakeVoiceChannel("vc_1")
    vm._voice_clients["guild_1"] = fake_vc

    voice_inputs: list[VoiceInput] = []
    bus.subscribe(VoiceInput, lambda e: voice_inputs.append(e))

    await vm._check_silence_and_transcribe()

    assert len(voice_inputs) == 1
    assert "TestUser: Hey Shannon" in voice_inputs[0].text
    assert voice_inputs[0].speakers == {"user_1": "TestUser"}
    assert voice_inputs[0].channel == "vc_1"


# ---------------------------------------------------------------------------
# SSRC-to-user mapping (Task 17)
# ---------------------------------------------------------------------------

def test_voice_manager_registers_ssrc_from_speaking():
    vm, bus, client = _make_voice_manager(enabled=True)
    vm.handle_speaking_update(user_id="user_1", ssrc=42, display_name="Alice")
    assert 42 in vm._ssrc_to_user
    assert vm._ssrc_to_user[42] == ("user_1", "Alice")


def test_voice_manager_updates_ssrc_mapping():
    vm, bus, client = _make_voice_manager(enabled=True)
    vm.handle_speaking_update(user_id="user_1", ssrc=10, display_name="Alice")
    vm.handle_speaking_update(user_id="user_1", ssrc=20, display_name="Alice")
    assert 10 not in vm._ssrc_to_user
    assert 20 in vm._ssrc_to_user
