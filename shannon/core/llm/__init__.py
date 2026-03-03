"""LLM provider subpackage — re-exports for backward compatibility."""

from shannon.core.llm.types import LLMMessage, LLMResponse, ToolCall, ToolCallResult
from shannon.core.llm.base import LLMProvider
from shannon.core.llm.anthropic import AnthropicProvider
from shannon.core.llm.local import LocalProvider
from shannon.config import LLMConfig

__all__ = [
    "LLMMessage",
    "LLMResponse",
    "ToolCall",
    "ToolCallResult",
    "LLMProvider",
    "AnthropicProvider",
    "LocalProvider",
    "create_provider",
]


def create_provider(config: LLMConfig) -> LLMProvider:
    """Factory to create the appropriate LLM provider from config."""
    if config.provider == "local":
        return LocalProvider(config)
    return AnthropicProvider(config)
