"""OutputManager — routes LLM responses to TTS/display and expressions to VTuber."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shannon.events import ExpressionChange, LLMResponse, SpeechEnd, SpeechStart

if TYPE_CHECKING:
    from shannon.bus import EventBus
    from shannon.output.providers.tts.base import TTSProvider
    from shannon.output.providers.vtuber.base import VTuberProvider


class OutputManager:
    """Subscribes to LLMResponse and ExpressionChange events.

    In **text mode** (``speech_output=False``) the response text is printed to
    stdout.  In **speech mode** (``speech_output=True``) the text is synthesised
    via the TTS provider and ``SpeechStart`` / ``SpeechEnd`` events are emitted.

    Expression changes are always forwarded to the VTuber provider when one is
    configured.
    """

    def __init__(
        self,
        bus: "EventBus",
        tts_provider: "TTSProvider | None" = None,
        vtuber_provider: "VTuberProvider | None" = None,
        speech_output: bool = False,
    ) -> None:
        self._bus = bus
        self._tts = tts_provider
        self._vtuber = vtuber_provider
        self._speech_output = speech_output

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Subscribe to bus events."""
        self._bus.subscribe(LLMResponse, self._on_llm_response)
        self._bus.subscribe(ExpressionChange, self._on_expression_change)

    def stop(self) -> None:
        """Unsubscribe from bus events."""
        self._bus.unsubscribe(LLMResponse, self._on_llm_response)
        self._bus.unsubscribe(ExpressionChange, self._on_expression_change)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_llm_response(self, event: LLMResponse) -> None:
        if self._speech_output and self._tts is not None:
            await self._speak(event.text)
        else:
            print(event.text)

    async def _on_expression_change(self, event: ExpressionChange) -> None:
        if self._vtuber is not None:
            await self._vtuber.set_expression(event.name, event.intensity)

    # ------------------------------------------------------------------
    # TTS helpers
    # ------------------------------------------------------------------

    async def _speak(self, text: str) -> None:
        """Synthesize *text* via TTS and emit SpeechStart/SpeechEnd events."""
        assert self._tts is not None

        # Collect phonemes for lip-sync (best-effort)
        try:
            phonemes = await self._tts.get_phonemes(text)
        except Exception:
            phonemes = []

        # Synthesize audio
        chunk = await self._tts.synthesize(text)

        # Estimate duration from PCM byte count
        duration = _estimate_duration(chunk)

        await self._bus.publish(SpeechStart(duration=duration, phonemes=phonemes))

        # Drive VTuber lip-sync if available
        if self._vtuber is not None:
            await self._vtuber.start_speaking(phonemes=phonemes)

        # NOTE: actual audio playback is intentionally out of scope here.
        # A real implementation would feed `chunk.data` to a sound device.

        if self._vtuber is not None:
            await self._vtuber.stop_speaking()

        await self._bus.publish(SpeechEnd())


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _estimate_duration(chunk: object) -> float:
    """Estimate playback duration in seconds from raw PCM byte count.

    Expects an AudioChunk-like object with ``data``, ``sample_rate``, and
    ``channels`` attributes.  Assumes 16-bit (2-byte) samples; falls back to
    0.0 on any error.
    """
    try:
        bytes_per_sample = 2  # 16-bit PCM
        num_samples = len(chunk.data) / bytes_per_sample / chunk.channels  # type: ignore[attr-defined]
        return num_samples / chunk.sample_rate  # type: ignore[attr-defined]
    except Exception:
        return 0.0
