"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _set_api_key_env(monkeypatch):
    """Provide a dummy API key so LLMConfig.__post_init__ doesn't raise."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")
