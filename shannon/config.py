"""Configuration management with Pydantic Settings + optional YAML."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from shannon.utils.platform import get_config_dir, get_data_dir


class LLMConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    max_context_tokens: int = 100_000
    rate_limit_rpm: int = 50


class DiscordConfig(BaseModel):
    token: str = ""
    guild_ids: list[int] = Field(default_factory=list)
    command_prefix: str = "!"


class SignalConfig(BaseModel):
    """Signal transport config — present but unused until later phase."""
    phone_number: str = ""
    signal_cli_path: str = ""
    data_dir: str = ""


class AuthConfig(BaseModel):
    admin_users: list[str] = Field(default_factory=list)
    operator_users: list[str] = Field(default_factory=list)
    trusted_users: list[str] = Field(default_factory=list)
    default_level: int = 0  # public


class SchedulerConfig(BaseModel):
    heartbeat_interval: int = 30
    heartbeat_file: str = ""
    enabled: bool = True


class ChunkerConfig(BaseModel):
    discord_limit: int = 1900
    signal_limit: int = 2000
    typing_delay: float = 0.5
    min_chunk_size: int = 100


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SHANNON_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    llm: LLMConfig = Field(default_factory=LLMConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    signal: SignalConfig = Field(default_factory=SignalConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    chunker: ChunkerConfig = Field(default_factory=ChunkerConfig)
    data_dir: str = ""
    log_level: str = "INFO"
    log_json: bool = False

    def get_data_dir(self) -> Path:
        if self.data_dir:
            return Path(self.data_dir)
        return get_data_dir()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from env vars, optionally overlaying a YAML config."""
    yaml_data: dict[str, Any] = {}

    # Determine config file path
    if config_path is None:
        config_path = os.environ.get("SHANNON_CONFIG")
    if config_path is None:
        default = get_config_dir() / "config.yaml"
        if default.exists():
            config_path = default

    # Load YAML if found
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                yaml_data = yaml.safe_load(f) or {}

    # Build settings: YAML values as defaults, env vars override
    return Settings(**yaml_data)
