# shannon/brain/tool_registry.py
"""ToolRegistry — assembles the Anthropic API tools list and beta headers from config."""

from __future__ import annotations

from shannon.config import ShannonConfig

# Default display dimensions for computer-use tool (ComputerUseConfig has no dim fields)
_DEFAULT_DISPLAY_WIDTH = 1280
_DEFAULT_DISPLAY_HEIGHT = 800


class ToolRegistry:
    """Build the tools list and beta headers for the Anthropic API."""

    def __init__(self, config: ShannonConfig) -> None:
        self._config = config

    def build(self, mode: str = "full") -> list[dict]:
        """Return tools in Anthropic API format.

        Args:
            mode: "full" for all tools, "chat" for minimal conversational set.
        """
        tools: list[dict] = []

        if mode == "full":
            # --- Conditionally-included Anthropic-hosted tools ---

            if self._config.tools.computer_use.enabled:
                tools.append({
                    "type": "computer_20251124",
                    "name": "computer",
                    "display_width_px": _DEFAULT_DISPLAY_WIDTH,
                    "display_height_px": _DEFAULT_DISPLAY_HEIGHT,
                })

            if self._config.tools.bash.enabled:
                tools.append({
                    "type": "bash_20250124",
                    "name": "bash",
                })

            if self._config.tools.text_editor.enabled:
                tools.append({
                    "type": "text_editor_20250728",
                    "name": "str_replace_based_edit_tool",
                })

            # --- Server-side tools (full mode only) ---

            tools.append({"type": "code_execution_20260120", "name": "code_execution"})
            tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 3})
            tools.append({"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3})

        # --- Both modes ---

        tools.append({"type": "memory_20250818", "name": "memory"})

        # --- Always-included user-defined tools ---

        tools.append({
            "name": "set_expression",
            "description": (
                "Set Shannon's facial expression or emotional state."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Expression name, e.g. 'happy', 'surprised', 'sad', 'thinking'.",
                    },
                    "intensity": {
                        "type": "number",
                        "description": "Intensity of the expression, between 0.0 (subtle) and 1.0 (full).",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
                "required": ["name"],
            },
        })

        tools.append({
            "name": "continue",
            "description": (
                "Signal to send another follow-up message. Call this when you have more "
                "to say — your current text will be sent immediately, then you get another "
                "turn to speak. Do NOT use this if you're done talking."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        })

        return tools

    def beta_headers(self) -> list[str]:
        """Return the list of Anthropic beta header strings based on config."""
        headers: list[str] = []

        if self._config.tools.computer_use.enabled:
            headers.append("computer-use-2025-11-24")

        if self._config.llm.compaction:
            headers.append("compact-2026-01-12")

        if self._config.llm.enable_1m_context:
            headers.append("context-1m-2025-08-07")

        return headers
