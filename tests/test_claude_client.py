"""Tests for ClaudeClient — internal message conversion and response parsing."""

import base64
from unittest.mock import MagicMock

import pytest

from shannon.brain.claude import ClaudeClient, _detect_media_type
from shannon.brain.types import LLMMessage, LLMResponse, LLMToolCall
from shannon.config import LLMConfig


def make_client(**kwargs) -> ClaudeClient:
    cfg = LLMConfig(api_key="test-key", **kwargs)
    return ClaudeClient(cfg)


# ---------------------------------------------------------------------------
# _build_messages tests
# ---------------------------------------------------------------------------

def test_build_messages_extracts_system():
    client = make_client()
    messages = [
        LLMMessage(role="system", content="You are Shannon."),
        LLMMessage(role="user", content="Hello"),
    ]
    system_blocks, api_messages = client._build_messages(messages)

    # System message should be extracted and NOT appear in api_messages
    assert len(api_messages) == 1
    assert api_messages[0]["role"] == "user"

    # system_blocks should be a list with one text block containing the system prompt
    assert isinstance(system_blocks, list)
    assert len(system_blocks) == 1
    assert system_blocks[0]["type"] == "text"
    assert system_blocks[0]["text"] == "You are Shannon."


def test_build_messages_adds_cache_control_to_system():
    client = make_client()
    messages = [
        LLMMessage(role="system", content="You are Shannon."),
        LLMMessage(role="user", content="Hello"),
    ]
    system_blocks, _ = client._build_messages(messages)

    assert "cache_control" in system_blocks[0]
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_build_messages_handles_images():
    client = make_client()
    image_bytes = b"\x89PNG\r\n\x1a\n"
    messages = [
        LLMMessage(role="user", content="What is this?", images=[image_bytes]),
    ]
    _, api_messages = client._build_messages(messages)

    assert len(api_messages) == 1
    content = api_messages[0]["content"]
    assert isinstance(content, list)

    # Should have image block + text block
    types = [block["type"] for block in content]
    assert "image" in types
    assert "text" in types

    # Image should be base64-encoded
    img_block = next(b for b in content if b["type"] == "image")
    expected_b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    assert img_block["source"]["data"] == expected_b64
    assert img_block["source"]["type"] == "base64"
    assert img_block["source"]["media_type"] == "image/png"


def test_build_messages_preserves_content_blocks_compaction():
    """When content is already a list of blocks (compaction), pass through unchanged."""
    client = make_client()
    content_blocks = [
        {"type": "text", "text": "Some compacted content"},
        {"type": "tool_use", "id": "tu_1", "name": "foo", "input": {}},
    ]
    messages = [
        LLMMessage(role="assistant", content=content_blocks),
    ]
    _, api_messages = client._build_messages(messages)

    assert len(api_messages) == 1
    assert api_messages[0]["content"] is content_blocks


def test_build_messages_handles_tool_calls():
    client = make_client()
    messages = [
        LLMMessage(
            role="assistant",
            content="I will call a tool.",
            tool_calls=[{"id": "tc_1", "name": "save_memory", "arguments": {"content": "test"}}],
        ),
    ]
    _, api_messages = client._build_messages(messages)

    assert len(api_messages) == 1
    content = api_messages[0]["content"]
    types = [block["type"] for block in content]
    assert "text" in types
    assert "tool_use" in types


def test_build_messages_handles_tool_results():
    client = make_client()
    messages = [
        LLMMessage(
            role="user",
            content="",
            tool_results=[{"id": "tc_1", "content": "memory saved"}],
        ),
    ]
    _, api_messages = client._build_messages(messages)

    assert len(api_messages) == 1
    assert api_messages[0]["role"] == "user"
    content = api_messages[0]["content"]
    assert content[0]["type"] == "tool_result"
    assert content[0]["tool_use_id"] == "tc_1"


# ---------------------------------------------------------------------------
# _parse_response tests
# ---------------------------------------------------------------------------

def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(id: str, name: str, input: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.id = id
    block.name = name
    block.input = input
    return block


def _make_server_block(block_type: str) -> MagicMock:
    block = MagicMock()
    block.type = block_type
    return block


def _make_response(content: list, stop_reason: str = "end_turn") -> MagicMock:
    response = MagicMock()
    response.content = content
    response.stop_reason = stop_reason
    return response


def test_parse_response_text_only():
    client = make_client()
    response = _make_response([_make_text_block("Hello, world!")])

    result = client._parse_response(response)

    assert isinstance(result, LLMResponse)
    assert result.text == "Hello, world!"
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"


def test_parse_response_with_tool_use():
    client = make_client()
    response = _make_response([
        _make_text_block("I'll save a memory."),
        _make_tool_use_block("tc_1", "save_memory", {"content": "important thing"}),
    ], stop_reason="tool_use")

    result = client._parse_response(response)

    assert result.text == "I'll save a memory."
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert isinstance(call, LLMToolCall)
    assert call.id == "tc_1"
    assert call.name == "save_memory"
    assert call.arguments == {"content": "important thing"}
    assert result.stop_reason == "tool_use"


def test_parse_response_skips_server_blocks():
    """server_tool_use, thinking, and *_tool_result blocks should be ignored."""
    client = make_client()
    response = _make_response([
        _make_server_block("server_tool_use"),
        _make_server_block("thinking"),
        _make_server_block("web_search_tool_result"),
        _make_text_block("Final answer."),
    ])

    result = client._parse_response(response)

    assert result.text == "Final answer."
    assert result.tool_calls == []


def test_parse_response_multiple_text_blocks_joined():
    client = make_client()
    response = _make_response([
        _make_text_block("Part one. "),
        _make_text_block("Part two."),
    ])

    result = client._parse_response(response)

    assert result.text == "Part one. Part two."


# ---------------------------------------------------------------------------
# _normalize_messages tests
# ---------------------------------------------------------------------------

class TestNormalizeMessages:
    def test_consecutive_user_messages_merged(self):
        client = make_client()
        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="user", content="How are you?"),
        ]
        _, api_messages = client._build_messages(messages)
        assert len(api_messages) == 1
        assert api_messages[0]["role"] == "user"
        texts = [b["text"] for b in api_messages[0]["content"] if b["type"] == "text"]
        assert "Hello" in texts
        assert "How are you?" in texts

    def test_consecutive_assistant_messages_merged(self):
        client = make_client()
        messages = [
            LLMMessage(role="user", content="Hi"),
            LLMMessage(role="assistant", content="Hello!"),
            LLMMessage(role="assistant", content="How can I help?"),
        ]
        _, api_messages = client._build_messages(messages)
        assert len(api_messages) == 2
        assert api_messages[0]["role"] == "user"
        assert api_messages[1]["role"] == "assistant"
        texts = [b["text"] for b in api_messages[1]["content"] if b["type"] == "text"]
        assert "Hello!" in texts
        assert "How can I help?" in texts

    def test_alternating_messages_unchanged(self):
        client = make_client()
        messages = [
            LLMMessage(role="user", content="Hi"),
            LLMMessage(role="assistant", content="Hello"),
            LLMMessage(role="user", content="Bye"),
        ]
        _, api_messages = client._build_messages(messages)
        assert len(api_messages) == 3

    def test_normalization_merges_list_and_string_content(self):
        """Content blocks (from compaction) followed by string should merge."""
        client = make_client()
        blocks = [{"type": "text", "text": "compacted"}]
        messages = [
            LLMMessage(role="assistant", content=blocks),
            LLMMessage(role="assistant", content="More text"),
        ]
        _, api_messages = client._build_messages(messages)
        # Mixed content types are now merged into a single block list
        assert len(api_messages) == 1
        assert api_messages[0]["role"] == "assistant"
        combined = api_messages[0]["content"]
        assert isinstance(combined, list)
        texts = [b["text"] for b in combined if b["type"] == "text"]
        assert "compacted" in texts
        assert "More text" in texts

    def test_normalize_messages_does_not_merge_tool_result_with_string(self):
        """A tool_result message must not be merged with an adjacent plain-text message."""
        tool_result_block = {"type": "tool_result", "tool_use_id": "tu_1", "content": "done"}
        msgs = [
            {"role": "user", "content": [tool_result_block]},
            {"role": "user", "content": "Follow-up question"},
        ]
        result = ClaudeClient._normalize_messages(msgs)
        assert len(result) == 2
        assert result[0]["content"] == [tool_result_block]
        assert result[1]["content"] == "Follow-up question"

    def test_normalize_messages_does_not_merge_string_with_tool_result(self):
        """A plain-text message must not be merged with an adjacent tool_result message."""
        tool_result_block = {"type": "tool_result", "tool_use_id": "tu_2", "content": "ok"}
        msgs = [
            {"role": "user", "content": "Initial message"},
            {"role": "user", "content": [tool_result_block]},
        ]
        result = ClaudeClient._normalize_messages(msgs)
        assert len(result) == 2
        assert result[0]["content"] == "Initial message"
        assert result[1]["content"] == [tool_result_block]

    def test_normalize_messages_still_merges_two_strings(self):
        """Backward compatibility: two consecutive string-content messages still merge."""
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "How are you?"},
        ]
        result = ClaudeClient._normalize_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        combined = result[0]["content"]
        assert isinstance(combined, list)
        texts = [b["text"] for b in combined if b["type"] == "text"]
        assert "Hello" in texts
        assert "How are you?" in texts

    def test_normalize_messages_empty_content_merged(self):
        """Two consecutive user messages where one has empty string content merge without error."""
        msgs = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "Non-empty message"},
        ]
        result = ClaudeClient._normalize_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        # empty string produces no blocks, only the non-empty message block remains
        combined = result[0]["content"]
        assert isinstance(combined, list)
        assert {"type": "text", "text": "Non-empty message"} in combined


def test_normalize_does_not_merge_tool_use_messages():
    """Consecutive assistant messages containing tool_use blocks must not be merged."""
    client = make_client()
    messages = [
        {"role": "assistant", "content": [
            {"type": "text", "text": "calling tool"},
            {"type": "tool_use", "id": "tu1", "name": "bash", "input": {}},
        ]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "calling another tool"},
            {"type": "tool_use", "id": "tu2", "name": "bash", "input": {}},
        ]},
    ]
    result = client._normalize_messages(messages)
    assert len(result) == 2
    assert result[0]["content"][1]["id"] == "tu1"
    assert result[1]["content"][1]["id"] == "tu2"


def test_normalize_does_not_merge_tool_result_messages():
    """Consecutive user messages containing tool_result blocks must not be merged."""
    client = make_client()
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "ok"},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu2", "content": "ok"},
        ]},
    ]
    result = client._normalize_messages(messages)
    assert len(result) == 2


def test_usage_tracking_initial_state():
    client = make_client()
    assert client.total_input_tokens == 0
    assert client.total_output_tokens == 0


# ---------------------------------------------------------------------------
# _detect_media_type tests
# ---------------------------------------------------------------------------

def test_detect_media_type_jpeg():
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 20
    assert _detect_media_type(jpeg_bytes) == "image/jpeg"


def test_detect_media_type_gif():
    gif_bytes = b"GIF89a" + b"\x00" * 20
    assert _detect_media_type(gif_bytes) == "image/gif"


def test_detect_media_type_webp():
    webp_bytes = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20
    assert _detect_media_type(webp_bytes) == "image/webp"


def test_detect_media_type_png_default():
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    assert _detect_media_type(png_bytes) == "image/png"


def test_detect_media_type_unknown_defaults_to_png():
    random_bytes = b"\x00\x01\x02\x03" + b"\x00" * 20
    assert _detect_media_type(random_bytes) == "image/png"


def test_build_messages_uses_detected_media_type():
    client = make_client()
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 20
    messages = [
        LLMMessage(role="user", content="What is this?", images=[jpeg_bytes]),
    ]
    _, api_messages = client._build_messages(messages)

    content = api_messages[0]["content"]
    img_block = next(b for b in content if b["type"] == "image")
    assert img_block["source"]["media_type"] == "image/jpeg"
