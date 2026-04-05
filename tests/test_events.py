"""Tests for typed event definitions."""

import pytest
from time import time


def test_user_input_construction():
    from shannon.events import UserInput
    event = UserInput(text="hello", source="text")
    assert event.text == "hello"
    assert event.source == "text"


def test_user_input_voice_source():
    from shannon.events import UserInput
    event = UserInput(text="hey there", source="voice")
    assert event.source == "voice"


def test_vision_frame_construction():
    from shannon.events import VisionFrame
    img = b"\x00\x01\x02"
    before = time()
    event = VisionFrame(image=img, source="screen")
    after = time()
    assert event.image == img
    assert event.source == "screen"
    assert before <= event.timestamp <= after


def test_vision_frame_explicit_timestamp():
    from shannon.events import VisionFrame
    event = VisionFrame(image=b"", source="cam", timestamp=1234.5)
    assert event.timestamp == 1234.5


def test_autonomous_trigger_construction():
    from shannon.events import AutonomousTrigger
    event = AutonomousTrigger(reason="screen_change", context="browser opened")
    assert event.reason == "screen_change"
    assert event.context == "browser opened"


def test_llm_response_construction():
    from shannon.events import LLMResponse
    event = LLMResponse(
        text="Hi!",
        expressions=[{"name": "smile", "intensity": 0.8}],
        actions=[{"type": "shell", "cmd": "ls"}],
        mood="happy",
    )
    assert event.text == "Hi!"
    assert event.expressions[0]["name"] == "smile"
    assert event.actions[0]["type"] == "shell"
    assert event.mood == "happy"


def test_speech_start_construction():
    from shannon.events import SpeechStart
    event = SpeechStart(duration=2.5)
    assert event.duration == 2.5
    assert event.phonemes == []


def test_speech_start_with_phonemes():
    from shannon.events import SpeechStart
    event = SpeechStart(duration=1.0, phonemes=["h", "EH", "l", "OW"])
    assert event.phonemes == ["h", "EH", "l", "OW"]


def test_speech_end_construction():
    from shannon.events import SpeechEnd
    event = SpeechEnd()
    assert isinstance(event, SpeechEnd)


def test_expression_change_construction():
    from shannon.events import ExpressionChange
    event = ExpressionChange(name="blink", intensity=0.5)
    assert event.name == "blink"
    assert event.intensity == 0.5


def test_config_change_construction():
    from shannon.events import ConfigChange
    event = ConfigChange(key="volume", old_value=0.5, new_value=0.8)
    assert event.key == "volume"
    assert event.old_value == 0.5
    assert event.new_value == 0.8


def test_config_change_any_types():
    from shannon.events import ConfigChange
    event = ConfigChange(key="model", old_value=None, new_value={"name": "claude"})
    assert event.old_value is None
    assert event.new_value == {"name": "claude"}


def test_chat_message_construction():
    from shannon.events import ChatMessage
    event = ChatMessage(
        text="hello shannon",
        author="user123",
        platform="twitch",
        channel="#general",
    )
    assert event.text == "hello shannon"
    assert event.author == "user123"
    assert event.platform == "twitch"
    assert event.channel == "#general"
    assert event.message_id == ""


def test_chat_message_with_id():
    from shannon.events import ChatMessage
    event = ChatMessage(
        text="hi",
        author="bob",
        platform="discord",
        channel="chat",
        message_id="msg-42",
    )
    assert event.message_id == "msg-42"


def test_chat_response_construction():
    from shannon.events import ChatResponse
    event = ChatResponse(text="Hello!", platform="twitch", channel="#general")
    assert event.text == "Hello!"
    assert event.platform == "twitch"
    assert event.channel == "#general"
    assert event.reply_to == ""


def test_chat_response_with_reply_to():
    from shannon.events import ChatResponse
    event = ChatResponse(
        text="Sure!", platform="discord", channel="chat", reply_to="msg-42"
    )
    assert event.reply_to == "msg-42"


from shannon.events import ChatMessage, ChatResponse, ChatReaction


class TestChatMessageExtended:
    def test_attachments_default_empty(self):
        msg = ChatMessage(text="hi", author="u", platform="discord", channel="c")
        assert msg.attachments == []

    def test_is_reply_to_bot_default_false(self):
        msg = ChatMessage(text="hi", author="u", platform="discord", channel="c")
        assert msg.is_reply_to_bot is False

    def test_is_mention_default_false(self):
        msg = ChatMessage(text="hi", author="u", platform="discord", channel="c")
        assert msg.is_mention is False

    def test_attachments_populated(self):
        att = {"filename": "img.png", "content_type": "image/png", "data": b"\x89PNG"}
        msg = ChatMessage(text="look", author="u", platform="d", channel="c", attachments=[att])
        assert len(msg.attachments) == 1
        assert msg.attachments[0]["filename"] == "img.png"


class TestChatResponseExtended:
    def test_reactions_default_empty(self):
        resp = ChatResponse(text="hi", platform="d", channel="c")
        assert resp.reactions == []

    def test_reactions_populated(self):
        resp = ChatResponse(text="hi", platform="d", channel="c", reactions=["👍", "🎉"])
        assert resp.reactions == ["👍", "🎉"]


class TestChatReaction:
    def test_chat_reaction_fields(self):
        r = ChatReaction(emoji="👍", platform="discord", channel="c", message_id="m1")
        assert r.emoji == "👍"
        assert r.platform == "discord"
        assert r.channel == "c"
        assert r.message_id == "m1"


from shannon.events import VoiceInput, VoiceOutput, VoiceStateChange


def test_voice_input():
    event = VoiceInput(
        text="Hello everyone",
        speakers={"123": "Alice", "456": "Bob"},
        channel="789",
    )
    assert event.text == "Hello everyone"
    assert event.speakers == {"123": "Alice", "456": "Bob"}
    assert event.channel == "789"
    assert event.platform == "discord"


def test_voice_output():
    from shannon.output.providers.tts.base import AudioChunk
    chunk = AudioChunk(data=b"\x00" * 100, sample_rate=22050, channels=1)
    event = VoiceOutput(audio=chunk, channel="789")
    assert event.audio is chunk
    assert event.channel == "789"
    assert event.platform == "discord"


def test_voice_state_change_join():
    event = VoiceStateChange(user_id="123", user_name="Alice", channel="789")
    assert event.channel == "789"
    assert event.platform == "discord"


def test_voice_state_change_leave():
    event = VoiceStateChange(user_id="123", user_name="Alice", channel=None)
    assert event.channel is None
