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
