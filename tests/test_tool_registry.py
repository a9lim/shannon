# tests/test_tool_registry.py
"""Tests for ToolRegistry — Anthropic API tool list builder."""

import pytest
from shannon.config import ShannonConfig, ToolsConfig, ComputerUseConfig, BashConfig, TextEditorConfig, LLMConfig
from shannon.brain.tool_registry import ToolRegistry

COMPUTER_USE_TYPE = "computer_20251124"
BASH_TYPE = "bash_20250124"
TEXT_EDITOR_TYPE = "text_editor_20250728"
CODE_EXECUTION_TYPE = "code_execution_20260120"
MEMORY_TYPE = "memory_20250818"
WEB_SEARCH_TYPE = "web_search_20260209"
WEB_FETCH_TYPE = "web_fetch_20260209"

DEFAULT_DISPLAY_WIDTH = 1280
DEFAULT_DISPLAY_HEIGHT = 800


def make_config(**kwargs) -> ShannonConfig:
    """Build a ShannonConfig with all tools enabled and compaction on by default."""
    return ShannonConfig(**kwargs)


def get_tool(tools: list[dict], name: str) -> dict | None:
    for t in tools:
        if t.get("name") == name:
            return t
    return None


def get_tool_by_type(tools: list[dict], type_: str) -> dict | None:
    for t in tools:
        if t.get("type") == type_:
            return t
    return None


# ---------------------------------------------------------------------------
# Test: total count with all tools enabled
# ---------------------------------------------------------------------------

def test_build_returns_nine_tools_when_all_enabled():
    config = make_config()
    registry = ToolRegistry(config)
    tools = registry.build()
    assert len(tools) == 9


# ---------------------------------------------------------------------------
# Test: computer tool has correct display dimensions
# ---------------------------------------------------------------------------

def test_computer_tool_has_display_dimensions():
    config = make_config()
    registry = ToolRegistry(config)
    tools = registry.build()
    computer = get_tool(tools, "computer")
    assert computer is not None
    assert computer["display_width_px"] == DEFAULT_DISPLAY_WIDTH
    assert computer["display_height_px"] == DEFAULT_DISPLAY_HEIGHT
    assert computer["type"] == COMPUTER_USE_TYPE


# ---------------------------------------------------------------------------
# Test: disabled tools are excluded
# ---------------------------------------------------------------------------

def test_computer_excluded_when_disabled():
    config = make_config(
        tools=ToolsConfig(computer_use=ComputerUseConfig(enabled=False))
    )
    registry = ToolRegistry(config)
    tools = registry.build()
    names = [t.get("name") for t in tools]
    assert "computer" not in names
    # Total drops by 1
    assert len(tools) == 8


def test_bash_excluded_when_disabled():
    config = make_config(
        tools=ToolsConfig(bash=BashConfig(enabled=False))
    )
    registry = ToolRegistry(config)
    tools = registry.build()
    names = [t.get("name") for t in tools]
    assert "bash" not in names
    assert len(tools) == 8


def test_text_editor_excluded_when_disabled():
    config = make_config(
        tools=ToolsConfig(text_editor=TextEditorConfig(enabled=False))
    )
    registry = ToolRegistry(config)
    tools = registry.build()
    names = [t.get("name") for t in tools]
    assert "str_replace_based_edit_tool" not in names
    assert len(tools) == 8


def test_all_three_optional_tools_excluded():
    config = make_config(
        tools=ToolsConfig(
            computer_use=ComputerUseConfig(enabled=False),
            bash=BashConfig(enabled=False),
            text_editor=TextEditorConfig(enabled=False),
        )
    )
    registry = ToolRegistry(config)
    tools = registry.build()
    assert len(tools) == 6


# ---------------------------------------------------------------------------
# Test: Anthropic-hosted tools have a "type" field
# ---------------------------------------------------------------------------

def test_anthropic_tools_have_type_field():
    config = make_config()
    registry = ToolRegistry(config)
    tools = registry.build()
    anthropic_types = {
        COMPUTER_USE_TYPE, BASH_TYPE, TEXT_EDITOR_TYPE,
        CODE_EXECUTION_TYPE, MEMORY_TYPE, WEB_SEARCH_TYPE, WEB_FETCH_TYPE,
    }
    for tool in tools:
        if tool.get("type") in anthropic_types:
            assert "type" in tool


# ---------------------------------------------------------------------------
# Test: user-defined tools have "input_schema"
# ---------------------------------------------------------------------------

def test_user_defined_tools_have_input_schema():
    config = make_config()
    registry = ToolRegistry(config)
    tools = registry.build()
    user_defined_names = {"set_expression", "continue"}
    for tool in tools:
        if tool.get("name") in user_defined_names:
            assert "input_schema" in tool, f"{tool['name']} missing input_schema"
            assert "description" in tool, f"{tool['name']} missing description"


# ---------------------------------------------------------------------------
# Test: beta_headers
# ---------------------------------------------------------------------------

def test_beta_headers_always_includes_context_1m():
    config = make_config()
    registry = ToolRegistry(config)
    headers = registry.beta_headers()
    assert "context-1m-2025-08-07" in headers


def test_beta_headers_includes_computer_use_when_enabled():
    config = make_config()
    assert config.tools.computer_use.enabled is True
    registry = ToolRegistry(config)
    headers = registry.beta_headers()
    assert "computer-use-2025-11-24" in headers


def test_beta_headers_excludes_computer_use_when_disabled():
    config = make_config(
        tools=ToolsConfig(computer_use=ComputerUseConfig(enabled=False))
    )
    registry = ToolRegistry(config)
    headers = registry.beta_headers()
    assert "computer-use-2025-11-24" not in headers


def test_beta_headers_includes_compact_when_compaction_enabled():
    config = make_config(llm=LLMConfig(compaction=True))
    registry = ToolRegistry(config)
    headers = registry.beta_headers()
    assert "compact-2026-01-12" in headers


def test_beta_headers_excludes_compact_when_compaction_disabled():
    config = make_config(llm=LLMConfig(compaction=False))
    registry = ToolRegistry(config)
    headers = registry.beta_headers()
    assert "compact-2026-01-12" not in headers


# ---------------------------------------------------------------------------
# Test: max_uses rate limits on web_search and web_fetch
# ---------------------------------------------------------------------------

def test_web_search_has_max_uses():
    """web_search tool should have max_uses set."""
    config = ShannonConfig()
    registry = ToolRegistry(config)
    tools = registry.build()
    ws = next(t for t in tools if t.get("name") == "web_search")
    assert ws["max_uses"] == 3


def test_web_fetch_has_max_uses():
    """web_fetch tool should have max_uses set."""
    config = ShannonConfig()
    registry = ToolRegistry(config)
    tools = registry.build()
    wf = next(t for t in tools if t.get("name") == "web_fetch")
    assert wf["max_uses"] == 3


def test_code_execution_no_max_uses():
    """code_execution should NOT have max_uses (it's self-contained)."""
    config = ShannonConfig()
    registry = ToolRegistry(config)
    tools = registry.build()
    ce = next(t for t in tools if t.get("name") == "code_execution")
    assert "max_uses" not in ce


# ---------------------------------------------------------------------------
# Test: chat mode
# ---------------------------------------------------------------------------

def test_build_chat_mode_excludes_server_tools():
    config = make_config()
    registry = ToolRegistry(config)
    tools = registry.build(mode="chat")
    names = [t.get("name") for t in tools]
    assert "code_execution" not in names
    assert "web_search" not in names
    assert "web_fetch" not in names
    assert "set_expression" in names
    assert "continue" in names
    assert "memory" in names


def test_build_chat_mode_excludes_agentic_tools():
    config = make_config()
    registry = ToolRegistry(config)
    tools = registry.build(mode="chat")
    names = [t.get("name") for t in tools]
    assert "computer" not in names
    assert "bash" not in names
    assert "str_replace_based_edit_tool" not in names


def test_build_chat_mode_returns_three_tools():
    config = make_config()
    registry = ToolRegistry(config)
    tools = registry.build(mode="chat")
    assert len(tools) == 3  # memory, set_expression, continue


def test_build_default_mode_is_full():
    config = make_config()
    registry = ToolRegistry(config)
    tools_default = registry.build()
    tools_full = registry.build(mode="full")
    assert len(tools_default) == len(tools_full)
