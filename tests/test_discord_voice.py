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
