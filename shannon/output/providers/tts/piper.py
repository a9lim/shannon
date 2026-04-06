"""PiperProvider — lazy-loads piper-tts and synthesizes speech."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from shannon.output.providers.tts.base import AudioChunk, TTSProvider

if TYPE_CHECKING:
    pass

_logger = logging.getLogger(__name__)

# Standard directories where piper voices may be installed.
_VOICE_SEARCH_DIRS = [
    Path.home() / ".local" / "share" / "piper_voices",
    Path.home() / ".local" / "share" / "piper-voices",
    Path("/usr/share/piper-voices"),
    Path("/usr/local/share/piper-voices"),
]


def _resolve_model_path(model_path: str) -> str:
    """Resolve a bare model name to a full path if needed.

    If *model_path* already points to an existing file, return it as-is.
    Otherwise search standard voice directories for ``<name>.onnx``.
    """
    p = Path(model_path)
    if p.exists():
        return model_path
    # Try appending .onnx
    if p.with_suffix(".onnx").exists():
        return str(p.with_suffix(".onnx"))
    # Search standard directories
    name = p.stem  # strip any extension the caller may have added
    for d in _VOICE_SEARCH_DIRS:
        candidate = d / f"{name}.onnx"
        if candidate.exists():
            _logger.debug("Resolved piper model %s → %s", model_path, candidate)
            return str(candidate)
    # Give up — return original and let piper raise a clear error
    return model_path


class PiperProvider(TTSProvider):
    """TTS provider backed by piper-tts (lazy-loaded)."""

    def __init__(
        self,
        model_path: str,
        config_path: str | None = None,
        speaker: str = "",
        rate: float = 1.0,
        noise_scale: float = 0.333,
        noise_w_scale: float = 0.333,
        sentence_silence: float = 0.3,
    ) -> None:
        self._model_path = _resolve_model_path(model_path)
        self._config_path = config_path
        self._speaker = speaker
        self._rate = rate
        self._noise_scale = noise_scale
        self._noise_w_scale = noise_w_scale
        self._sentence_silence = sentence_silence
        self._voice: object | None = None  # piper.voice.PiperVoice, loaded lazily
        self._syn_config: object | None = None  # piper.config.SynthesisConfig
        self._is_pinyin: bool = False  # set after load

    # ------------------------------------------------------------------
    # Lazy loader
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Import and initialise piper on first use."""
        if self._voice is not None:
            return
        try:
            from piper.voice import PiperVoice  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "piper-tts is not installed. "
                "Install it with: pip install piper-tts"
            ) from exc
        self._voice = PiperVoice.load(
            model_path=self._model_path,
            config_path=self._config_path,
        )
        from piper.config import PhonemeType, SynthesisConfig  # type: ignore[import]

        self._is_pinyin = self._voice.config.phoneme_type == PhonemeType.PINYIN

        # Resolve speaker name to ID for multi-speaker models
        speaker_id = None
        if self._speaker:
            sid_map = getattr(self._voice.config, "speaker_id_map", None) or {}
            # Try exact match, then case-insensitive
            if self._speaker in sid_map:
                speaker_id = sid_map[self._speaker]
            else:
                upper = self._speaker.upper()
                for name, sid in sid_map.items():
                    if name.upper() == upper:
                        speaker_id = sid
                        break
            if speaker_id is not None:
                _logger.info("Using piper speaker %s (id=%d)", self._speaker, speaker_id)
            else:
                _logger.warning(
                    "Speaker %r not found in model; available: %s",
                    self._speaker, ", ".join(sid_map.keys()),
                )
        self._syn_config = SynthesisConfig(
            speaker_id=speaker_id,
            length_scale=1.0 / self._rate if self._rate != 1.0 else None,
            noise_scale=self._noise_scale,
            noise_w_scale=self._noise_w_scale,
        )

    # ------------------------------------------------------------------
    # TTSProvider interface
    # ------------------------------------------------------------------

    async def synthesize(self, text: str) -> AudioChunk:
        """Synthesize the entire text and return a single AudioChunk."""
        self._load()
        assert self._voice is not None

        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> AudioChunk:
        """Synchronous synthesis — runs in thread pool."""
        if self._is_pinyin:
            return self._synthesize_pinyin_english(text)

        import numpy as np

        sample_rate = self._voice.config.sample_rate  # type: ignore[attr-defined]
        chunks = list(self._voice.synthesize(text, self._syn_config))  # type: ignore[attr-defined]
        if not chunks:
            return AudioChunk(data=b"", sample_rate=sample_rate, channels=1)

        # Interleave silence between sentence chunks
        silence_samples = int(sample_rate * self._sentence_silence)
        silence = np.zeros(silence_samples, dtype=np.float32)
        parts: list[np.ndarray] = []
        for i, c in enumerate(chunks):
            if i > 0 and silence_samples > 0:
                parts.append(silence)
            parts.append(c.audio_float_array)

        audio = np.concatenate(parts)
        pcm = (audio * 32767).astype(np.int16)
        return AudioChunk(data=pcm.tobytes(), sample_rate=sample_rate, channels=1)

    def _synthesize_pinyin_english(self, text: str) -> AudioChunk:
        """Synthesize English text through a pinyin model.

        Converts English → IPA → approximate pinyin phonemes, then feeds
        phoneme IDs directly to the model, bypassing the Chinese G2P.

        All sentences are flattened into a single phoneme-ID sequence so
        the model produces one continuous audio stream (no inter-sentence
        pauses or BOS/EOS boundaries that cause choppiness).
        """
        import numpy as np

        from shannon.output.providers.tts.en_to_pinyin import (
            english_to_pinyin_phonemes,
            pinyin_to_ids,
        )

        sentences = english_to_pinyin_phonemes(text)
        # Flatten all sentences into one phoneme list
        flat: list[str] = []
        for phonemes in sentences:
            flat.extend(phonemes)

        if not flat:
            sample_rate = self._voice.config.sample_rate  # type: ignore[attr-defined]
            return AudioChunk(data=b"", sample_rate=sample_rate, channels=1)

        ids = pinyin_to_ids(flat, self._voice.config.phoneme_id_map)  # type: ignore[attr-defined]
        audio = self._voice.phoneme_ids_to_audio(ids, self._syn_config)  # type: ignore[attr-defined]
        if isinstance(audio, tuple):
            audio = audio[0]

        audio = np.clip(audio, -1.0, 1.0)
        pcm = (audio * 32767).astype(np.int16)

        sample_rate = self._voice.config.sample_rate  # type: ignore[attr-defined]
        return AudioChunk(data=pcm.tobytes(), sample_rate=sample_rate, channels=1)

    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Synthesize text and yield AudioChunks one sentence at a time."""
        self._load()
        assert self._voice is not None

        import asyncio

        loop = asyncio.get_running_loop()

        chunks = await loop.run_in_executor(None, self._stream_sync, text)
        for chunk in chunks:
            yield chunk

    def _stream_sync(self, text: str) -> list[AudioChunk]:
        """Collect all stream chunks synchronously — runs in thread pool."""
        if self._is_pinyin:
            return self._stream_pinyin_english(text)

        import numpy as np

        result = []
        sample_rate = self._voice.config.sample_rate  # type: ignore[attr-defined]
        silence_samples = int(sample_rate * self._sentence_silence)
        for i, chunk in enumerate(self._voice.synthesize(text, self._syn_config)):  # type: ignore[attr-defined]
            if i > 0 and silence_samples > 0:
                silence = np.zeros(silence_samples, dtype=np.int16)
                result.append(AudioChunk(
                    data=silence.tobytes(),
                    sample_rate=sample_rate,
                    channels=1,
                ))
            pcm = (chunk.audio_float_array * 32767).astype(np.int16)
            result.append(AudioChunk(
                data=pcm.tobytes(),
                sample_rate=sample_rate,
                channels=1,
            ))
        return result

    def _stream_pinyin_english(self, text: str) -> list[AudioChunk]:
        """Stream English text through a pinyin model as one chunk.

        Flattened into a single synthesis call for smooth flow (no
        inter-sentence pauses).  Returns a one-element list for
        interface compatibility.
        """
        import numpy as np

        from shannon.output.providers.tts.en_to_pinyin import (
            english_to_pinyin_phonemes,
            pinyin_to_ids,
        )

        sentences = english_to_pinyin_phonemes(text)
        flat: list[str] = []
        for phonemes in sentences:
            flat.extend(phonemes)

        if not flat:
            return []

        sample_rate = self._voice.config.sample_rate  # type: ignore[attr-defined]
        ids = pinyin_to_ids(flat, self._voice.config.phoneme_id_map)  # type: ignore[attr-defined]
        audio = self._voice.phoneme_ids_to_audio(ids, self._syn_config)  # type: ignore[attr-defined]
        if isinstance(audio, tuple):
            audio = audio[0]
        audio = np.clip(audio, -1.0, 1.0)
        pcm = (audio * 32767).astype(np.int16)

        return [AudioChunk(
            data=pcm.tobytes(),
            sample_rate=sample_rate,
            channels=1,
        )]

    async def get_phonemes(self, text: str) -> list[str]:
        """Return phoneme strings for the given text using piper's phonemiser."""
        self._load()
        assert self._voice is not None

        try:
            phonemes: list[str] = self._voice.get_phonemes(text)  # type: ignore[attr-defined]
            return phonemes
        except AttributeError:
            # piper may not expose get_phonemes directly; return empty list
            return []
