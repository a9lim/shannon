# tests/test_config.py
"""Tests for the config system."""

import logging
import tempfile
from pathlib import Path

import pytest
import yaml

from shannon.config import (
    AutonomyConfig,
    BashConfig,
    ComputerUseConfig,
    LLMConfig,
    MemoryConfig,
    MessagingConfig,
    PersonalityConfig,
    STTConfig,
    ShannonConfig,
    TTSConfig,
    TextEditorConfig,
    ToolsConfig,
    VTuberConfig,
    VisionConfig,
    load_config,
)


class TestLLMConfigDefaults:
    def test_model_default(self):
        cfg = LLMConfig()
        assert cfg.model == "claude-sonnet-4-5-20250514"

    def test_max_tokens_default(self):
        cfg = LLMConfig()
        assert cfg.max_tokens == 8192

    def test_thinking_default(self):
        cfg = LLMConfig()
        assert cfg.thinking is True

    def test_thinking_budget_default(self):
        cfg = LLMConfig()
        assert cfg.thinking_budget == 4096

    def test_compaction_default(self):
        cfg = LLMConfig()
        assert cfg.compaction is True

    def test_api_key_default(self):
        cfg = LLMConfig()
        assert cfg.api_key == ""

    def test_no_type_field(self):
        cfg = LLMConfig()
        assert not hasattr(cfg, "type")


class TestToolsConfigDefaults:
    def test_tools_config_has_computer_use(self):
        cfg = ToolsConfig()
        assert isinstance(cfg.computer_use, ComputerUseConfig)

    def test_tools_config_has_bash(self):
        cfg = ToolsConfig()
        assert isinstance(cfg.bash, BashConfig)

    def test_tools_config_has_text_editor(self):
        cfg = ToolsConfig()
        assert isinstance(cfg.text_editor, TextEditorConfig)

    def test_computer_use_defaults(self):
        cfg = ComputerUseConfig()
        assert cfg.enabled is True
        assert cfg.require_confirmation is True

    def test_bash_defaults(self):
        cfg = BashConfig()
        assert cfg.enabled is True
        assert cfg.require_confirmation is True

    def test_bash_blocklist_defaults(self):
        cfg = BashConfig()
        expected = ["rm -rf", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
        for entry in expected:
            assert entry in cfg.blocklist, f"'{entry}' not in bash blocklist"

    def test_bash_timeout_default(self):
        cfg = BashConfig()
        assert cfg.timeout_seconds == 30

    def test_text_editor_defaults(self):
        cfg = TextEditorConfig()
        assert cfg.enabled is True
        assert cfg.require_confirmation is True


class TestOtherConfigDefaults:
    def test_tts_defaults(self):
        cfg = TTSConfig()
        assert cfg.type == "piper"
        assert cfg.model == "en_US-lessac-medium"
        assert cfg.rate == 1.0

    def test_stt_defaults(self):
        cfg = STTConfig()
        assert cfg.type == "whisper"
        assert cfg.model == "base.en"
        assert cfg.device == "auto"

    def test_vision_defaults(self):
        cfg = VisionConfig()
        assert cfg.screen is True
        assert cfg.webcam is False
        assert cfg.interval_seconds == 60.0

    def test_vtuber_defaults(self):
        cfg = VTuberConfig()
        assert cfg.type == "vtube_studio"
        assert cfg.host == "localhost"
        assert cfg.port == 8001

    def test_messaging_defaults(self):
        cfg = MessagingConfig()
        assert cfg.type == "discord"
        assert cfg.enabled is False
        assert cfg.token == ""

    def test_autonomy_defaults(self):
        cfg = AutonomyConfig()
        assert cfg.enabled is True
        assert cfg.cooldown_seconds == 120
        assert cfg.idle_timeout_seconds == 600

    def test_personality_defaults(self):
        cfg = PersonalityConfig()
        assert cfg.name == "Shannon"
        assert cfg.prompt_file == "personality.md"

    def test_memory_defaults(self):
        cfg = MemoryConfig()
        assert cfg.dir == "memory"
        assert cfg.conversation_window == 20
        assert cfg.recall_top_k == 5


class TestShannonConfigDefaults:
    def test_shannon_config_has_llm_at_top_level(self):
        cfg = ShannonConfig()
        assert isinstance(cfg.llm, LLMConfig)

    def test_shannon_config_has_tools_at_top_level(self):
        cfg = ShannonConfig()
        assert isinstance(cfg.tools, ToolsConfig)

    def test_shannon_config_has_tts_at_top_level(self):
        cfg = ShannonConfig()
        assert isinstance(cfg.tts, TTSConfig)

    def test_shannon_config_has_stt_at_top_level(self):
        cfg = ShannonConfig()
        assert isinstance(cfg.stt, STTConfig)

    def test_shannon_config_has_vision_at_top_level(self):
        cfg = ShannonConfig()
        assert isinstance(cfg.vision, VisionConfig)

    def test_shannon_config_has_vtuber_at_top_level(self):
        cfg = ShannonConfig()
        assert isinstance(cfg.vtuber, VTuberConfig)

    def test_shannon_config_has_messaging_at_top_level(self):
        cfg = ShannonConfig()
        assert isinstance(cfg.messaging, MessagingConfig)

    def test_shannon_config_has_autonomy(self):
        cfg = ShannonConfig()
        assert isinstance(cfg.autonomy, AutonomyConfig)

    def test_shannon_config_has_personality(self):
        cfg = ShannonConfig()
        assert isinstance(cfg.personality, PersonalityConfig)

    def test_shannon_config_has_memory(self):
        cfg = ShannonConfig()
        assert isinstance(cfg.memory, MemoryConfig)

    def test_shannon_config_no_providers_wrapper(self):
        cfg = ShannonConfig()
        assert not hasattr(cfg, "providers")

    def test_shannon_config_no_actions_wrapper(self):
        cfg = ShannonConfig()
        assert not hasattr(cfg, "actions")


class TestApplyDangerouslySkipPermissions:
    def test_sets_require_confirmation_false_on_computer_use(self):
        cfg = ShannonConfig()
        cfg.apply_dangerously_skip_permissions()
        assert cfg.tools.computer_use.require_confirmation is False

    def test_sets_require_confirmation_false_on_bash(self):
        cfg = ShannonConfig()
        cfg.apply_dangerously_skip_permissions()
        assert cfg.tools.bash.require_confirmation is False

    def test_sets_require_confirmation_false_on_text_editor(self):
        cfg = ShannonConfig()
        cfg.apply_dangerously_skip_permissions()
        assert cfg.tools.text_editor.require_confirmation is False

    def test_does_not_change_enabled_fields(self):
        cfg = ShannonConfig()
        cfg.apply_dangerously_skip_permissions()
        assert cfg.tools.computer_use.enabled is True
        assert cfg.tools.bash.enabled is True
        assert cfg.tools.text_editor.enabled is True

    def test_does_not_change_bash_blocklist(self):
        cfg = ShannonConfig()
        original_blocklist = list(cfg.tools.bash.blocklist)
        cfg.apply_dangerously_skip_permissions()
        assert cfg.tools.bash.blocklist == original_blocklist


class TestLoadConfig:
    def test_load_nonexistent_returns_defaults(self):
        cfg = load_config("/nonexistent/path/config.yaml")
        assert isinstance(cfg, ShannonConfig)
        assert cfg.llm.model == "claude-sonnet-4-5-20250514"
        assert cfg.tools.bash.require_confirmation is True

    def test_load_empty_yaml_returns_defaults(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write("")
            tmp_path = f.name
        cfg = load_config(tmp_path)
        assert cfg.llm.model == "claude-sonnet-4-5-20250514"
        assert cfg.tools.bash.require_confirmation is True

    def test_partial_override_preserves_defaults(self):
        data = {
            "llm": {
                "model": "claude-sonnet-4-5",
            }
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump(data, f)
            tmp_path = f.name
        cfg = load_config(tmp_path)
        assert cfg.llm.model == "claude-sonnet-4-5"
        assert cfg.llm.max_tokens == 8192
        assert cfg.llm.thinking is True
        assert cfg.tts.type == "piper"
        assert cfg.tools.bash.require_confirmation is True

    def test_override_tool_require_confirmation(self):
        data = {
            "tools": {
                "bash": {
                    "require_confirmation": False,
                }
            }
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump(data, f)
            tmp_path = f.name
        cfg = load_config(tmp_path)
        assert cfg.tools.bash.require_confirmation is False
        assert cfg.tools.computer_use.require_confirmation is True
        assert cfg.tools.text_editor.require_confirmation is True

    def test_override_flat_providers(self):
        data = {
            "stt": {"model": "small.en", "device": "cuda"},
            "vision": {"webcam": True},
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump(data, f)
            tmp_path = f.name
        cfg = load_config(tmp_path)
        assert cfg.stt.model == "small.en"
        assert cfg.stt.device == "cuda"
        assert cfg.stt.type == "whisper"
        assert cfg.vision.webcam is True
        assert cfg.vision.screen is True

    def test_override_autonomy(self):
        data = {"autonomy": {"cooldown_seconds": 60, "enabled": False}}
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump(data, f)
            tmp_path = f.name
        cfg = load_config(tmp_path)
        assert cfg.autonomy.cooldown_seconds == 60
        assert cfg.autonomy.enabled is False
        assert cfg.autonomy.idle_timeout_seconds == 600

    def test_override_memory(self):
        data = {"memory": {"conversation_window": 100}}
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump(data, f)
            tmp_path = f.name
        cfg = load_config(tmp_path)
        assert cfg.memory.conversation_window == 100
        assert cfg.memory.recall_top_k == 5
        assert cfg.memory.dir == "memory"

    def test_load_path_object(self):
        """load_config should accept both str and Path."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump({}, f)
            tmp_path = Path(f.name)
        cfg = load_config(tmp_path)
        assert isinstance(cfg, ShannonConfig)

    def test_load_config_clamps_out_of_range_values(self):
        data = {"messaging": {"debounce_delay": 100.0, "reply_probability": 2.0}}
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump(data, f)
            tmp_path = f.name
        cfg = load_config(tmp_path)
        assert cfg.messaging.debounce_delay == 3.0
        assert cfg.messaging.reply_probability == 0.0


class TestConfigFailHard:
    def test_llm_config_raises_without_api_key(self, monkeypatch):
        """LLMConfig raises ValueError when no API key in config or env."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="API key"):
            LLMConfig(api_key="")

    def test_llm_config_accepts_env_api_key(self, monkeypatch):
        """LLMConfig accepts ANTHROPIC_API_KEY from environment."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        cfg = LLMConfig(api_key="")
        assert cfg.api_key == ""  # field stays empty, but no error

    def test_llm_config_accepts_config_api_key(self, monkeypatch):
        """LLMConfig accepts api_key from config field."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = LLMConfig(api_key="sk-test")
        assert cfg.api_key == "sk-test"

    def test_messaging_config_raises_when_enabled_without_token(self):
        """MessagingConfig raises ValueError when enabled=True but token is empty."""
        with pytest.raises(ValueError, match="token"):
            MessagingConfig(enabled=True, token="")

    def test_messaging_config_ok_when_disabled_without_token(self):
        """MessagingConfig does not raise when enabled=False and token is empty."""
        cfg = MessagingConfig(enabled=False, token="")
        assert cfg.token == ""

    def test_messaging_config_ok_when_enabled_with_token(self):
        """MessagingConfig does not raise when enabled=True and token is provided."""
        cfg = MessagingConfig(enabled=True, token="bot-token-123")
        assert cfg.token == "bot-token-123"


class TestMessagingConfigDefaults:
    def test_debounce_delay_default(self):
        cfg = MessagingConfig()
        assert cfg.debounce_delay == 3.0

    def test_reply_probability_default(self):
        cfg = MessagingConfig()
        assert cfg.reply_probability == 0.0

    def test_reaction_probability_default(self):
        cfg = MessagingConfig()
        assert cfg.reaction_probability == 0.0

    def test_conversation_expiry_default(self):
        cfg = MessagingConfig()
        assert cfg.conversation_expiry == 300.0

    def test_max_context_messages_default(self):
        cfg = MessagingConfig()
        assert cfg.max_context_messages == 20


class TestConfigValidation:
    def test_messaging_debounce_delay_clamped_high(self):
        cfg = MessagingConfig(debounce_delay=100.0)
        assert cfg.debounce_delay == 3.0

    def test_messaging_debounce_delay_clamped_low(self):
        cfg = MessagingConfig(debounce_delay=-1.0)
        assert cfg.debounce_delay == 3.0

    def test_messaging_debounce_delay_valid_unchanged(self):
        cfg = MessagingConfig(debounce_delay=5.0)
        assert cfg.debounce_delay == 5.0

    def test_messaging_reply_probability_clamped_high(self):
        cfg = MessagingConfig(reply_probability=2.0)
        assert cfg.reply_probability == 0.0

    def test_messaging_reply_probability_valid_unchanged(self):
        cfg = MessagingConfig(reply_probability=0.5)
        assert cfg.reply_probability == 0.5

    def test_messaging_reaction_probability_clamped_high(self):
        cfg = MessagingConfig(reaction_probability=1.5)
        assert cfg.reaction_probability == 0.0

    def test_messaging_conversation_expiry_clamped_high(self):
        cfg = MessagingConfig(conversation_expiry=5000.0)
        assert cfg.conversation_expiry == 300.0

    def test_messaging_max_context_messages_clamped_negative(self):
        cfg = MessagingConfig(max_context_messages=-1)
        assert cfg.max_context_messages == 0

    def test_llm_max_tokens_clamped_to_minimum(self):
        cfg = LLMConfig(max_tokens=0)
        assert cfg.max_tokens == 1

    def test_llm_max_tokens_valid_unchanged(self):
        cfg = LLMConfig(max_tokens=8000)
        assert cfg.max_tokens == 8000

    def test_config_validation_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            MessagingConfig(debounce_delay=100.0)
        assert "debounce_delay" in caplog.text
