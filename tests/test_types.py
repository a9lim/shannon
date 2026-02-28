"""Tests for shannon/brain/types.py."""

import pytest

from shannon.brain.types import LLMMessage, LLMToolCall, LLMResponse


def test_llm_message_basic():
    """LLMMessage with string content and required fields."""
    msg = LLMMessage(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"
    assert msg.images == []
    assert msg.tool_calls == []
    assert msg.tool_results == []


def test_llm_message_with_content_blocks():
    """LLMMessage content can be a list of dicts (Anthropic content blocks)."""
    blocks = [
        {"type": "text", "text": "Look at this image"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}},
    ]
    msg = LLMMessage(role="user", content=blocks)
    assert isinstance(msg.content, list)
    assert len(msg.content) == 2
    assert msg.content[0]["type"] == "text"


def test_llm_message_defaults():
    """LLMMessage default fields are independent instances (no shared mutable defaults)."""
    msg1 = LLMMessage(role="user", content="a")
    msg2 = LLMMessage(role="user", content="b")
    msg1.images.append(b"img")
    msg1.tool_calls.append({"id": "1"})
    msg1.tool_results.append({"id": "1"})
    assert msg2.images == []
    assert msg2.tool_calls == []
    assert msg2.tool_results == []


def test_llm_tool_call_fields():
    """LLMToolCall stores id, name, and arguments."""
    call = LLMToolCall(id="call_1", name="run_shell", arguments={"cmd": "ls"})
    assert call.id == "call_1"
    assert call.name == "run_shell"
    assert call.arguments == {"cmd": "ls"}


def test_llm_response_defaults_and_with_tool_calls():
    """LLMResponse defaults and field access including tool_calls and stop_reason."""
    # Defaults
    resp = LLMResponse(text="Hello!")
    assert resp.text == "Hello!"
    assert resp.tool_calls == []
    assert resp.stop_reason == ""

    # With tool_calls and stop_reason
    tool_call = LLMToolCall(id="tc_1", name="save_memory", arguments={"note": "remember"})
    resp2 = LLMResponse(text="", tool_calls=[tool_call], stop_reason="tool_use")
    assert len(resp2.tool_calls) == 1
    assert resp2.tool_calls[0].name == "save_memory"
    assert resp2.stop_reason == "tool_use"


def test_llm_tool_call_is_frozen():
    """LLMToolCall should not allow mutation after construction."""
    call = LLMToolCall(id="call_1", name="bash", arguments={"cmd": "ls"})
    with pytest.raises(AttributeError):
        call.name = "other"


def test_llm_response_is_frozen():
    """LLMResponse should not allow mutation after construction."""
    resp = LLMResponse(text="hello")
    with pytest.raises(AttributeError):
        resp.text = "changed"
