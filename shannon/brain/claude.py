"""Claude API client with streaming, caching, compaction, and adaptive thinking."""

import base64
import logging
from typing import Any

import anthropic

from shannon.brain.types import LLMMessage, LLMResponse, LLMToolCall
from shannon.config import LLMConfig

logger = logging.getLogger(__name__)


def _detect_media_type(image_bytes: bytes) -> str:
    """Detect image media type from magic bytes. Defaults to image/png."""
    if image_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_bytes[:4] == b"GIF8":
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and len(image_bytes) > 11 and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


class ClaudeClient:
    """Thin wrapper around the Anthropic SDK for Shannon's brain."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = anthropic.AsyncAnthropic(api_key=config.api_key or None)
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        messages: list[LLMMessage],
    ) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]]]:
        """Convert LLMMessage list to Anthropic API format.

        Returns:
            (system_blocks, api_messages) where system_blocks is a list of
            content blocks for the top-level ``system`` parameter (with
            cache_control applied), or None if no system message was present.
        """
        system_blocks: list[dict[str, Any]] | None = None
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                # Anthropic takes system as a top-level param.
                # Wrap in a text block and apply prompt caching.
                text = msg.content if isinstance(msg.content, str) else ""
                system_blocks = [
                    {
                        "type": "text",
                        "text": text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
                continue

            # Compaction: content is already a list of API blocks — pass through.
            if isinstance(msg.content, list):
                api_messages.append({"role": msg.role, "content": msg.content})
                continue

            if msg.tool_results:
                # Tool result turn — role="user", blocks of type "tool_result".
                content: list[dict[str, Any]] = [
                    {
                        "type": "tool_result",
                        "tool_use_id": result["id"],
                        "content": result["content"],
                    }
                    for result in msg.tool_results
                ]
                api_messages.append({"role": "user", "content": content})
                continue

            if msg.tool_calls:
                # Assistant message with tool_use blocks.
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for call in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["name"],
                        "input": call["arguments"],
                    })
                api_messages.append({"role": "assistant", "content": content})
                continue

            # Regular text (+ optional images).
            content = []
            for image_bytes in msg.images:
                b64 = base64.standard_b64encode(image_bytes).decode("ascii")
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": _detect_media_type(image_bytes),
                        "data": b64,
                    },
                })
            if msg.content:
                content.append({"type": "text", "text": msg.content})

            if len(content) == 1 and content[0]["type"] == "text":
                api_messages.append({"role": msg.role, "content": msg.content})
            elif content:
                api_messages.append({"role": msg.role, "content": content})
            else:
                api_messages.append({"role": msg.role, "content": ""})

        return system_blocks, self._normalize_messages(api_messages)

    @staticmethod
    def _normalize_messages(api_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge consecutive same-role messages to ensure strict alternation."""
        if not api_messages:
            return api_messages

        def _to_blocks(content: Any) -> list[dict[str, Any]]:
            if isinstance(content, list):
                return content
            if isinstance(content, str) and content:
                return [{"type": "text", "text": content}]
            return []

        merged: list[dict[str, Any]] = [api_messages[0]]
        for msg in api_messages[1:]:
            prev = merged[-1]
            if prev["role"] == msg["role"]:
                prev_blocks = _to_blocks(prev["content"])
                new_blocks = _to_blocks(msg["content"])
                combined = prev_blocks + new_blocks
                merged[-1] = {"role": msg["role"], "content": combined if combined else ""}
            else:
                merged.append(msg)

        return merged

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, response: Any) -> LLMResponse:
        """Extract text and tool_use blocks from an Anthropic response.

        Server-side blocks (server_tool_use, thinking, *_tool_result) are
        informational and are skipped.
        """
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []

        for block in response.content:
            btype = block.type
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(
                    LLMToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )
            # server_tool_use, thinking, *_tool_result — skip

        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason or "",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _build_kwargs(
        self,
        api_messages: list[dict[str, Any]],
        system_blocks: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        betas: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build kwargs dict shared across API calls."""
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "messages": api_messages,
        }

        if system_blocks:
            kwargs["system"] = system_blocks

        if tools:
            kwargs["tools"] = tools

        if betas:
            kwargs["betas"] = betas

        if self._config.thinking:
            kwargs["thinking"] = {"type": "adaptive"}

        if self._config.compaction:
            kwargs["context_management"] = {
                "edits": [{"type": "compact_20260112"}]
            }

        return kwargs

    async def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        betas: list[str] | None = None,
    ) -> LLMResponse:
        """Generate a response using streaming and return the final message."""
        system_blocks, api_messages = self._build_messages(messages)
        kwargs = self._build_kwargs(api_messages, system_blocks, tools, betas)

        logger.debug(
            "Claude API request: model=%s, max_tokens=%d, messages=%d",
            kwargs["model"],
            kwargs["max_tokens"],
            len(api_messages),
        )

        async with self._client.beta.messages.stream(**kwargs) as stream:
            response = await stream.get_final_message()

        input_tokens = getattr(response.usage, "input_tokens", 0)
        output_tokens = getattr(response.usage, "output_tokens", 0)
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

        if input_tokens + output_tokens > 5000:
            logger.info(
                "Expensive turn: input=%d output=%d (session total: in=%d out=%d)",
                input_tokens, output_tokens,
                self.total_input_tokens, self.total_output_tokens,
            )

        logger.debug(
            "Claude API response: stop_reason=%s, usage=%s",
            response.stop_reason,
            response.usage,
        )

        return self._parse_response(response)
