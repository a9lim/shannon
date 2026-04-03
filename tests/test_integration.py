"""Integration tests for the full event pipeline."""
import pytest
from shannon.brain.brain import Brain
from shannon.brain.types import LLMResponse, LLMToolCall
from shannon.bus import EventBus
from shannon.config import ShannonConfig
from shannon.events import (
    ChatMessage, ChatResponse, LLMResponse as LLMResponseEvent, UserInput,
)

class FakeClaude:
    def __init__(self):
        self.call_count = 0
    async def generate(self, messages, tools=None, betas=None):
        self.call_count += 1
        return LLMResponse(text=f"Response #{self.call_count}", tool_calls=[], stop_reason="end_turn")

class FakeDispatcher:
    async def dispatch(self, tc): return "ok"
    @staticmethod
    def is_continue(name): return name == "continue"
    @staticmethod
    def is_expression(name): return name == "set_expression"
    @staticmethod
    def is_server_side(name): return name in {"web_search", "web_fetch", "code_execution"}

class FakeRegistry:
    def build(self, mode="full"): return []
    def beta_headers(self): return []

async def test_full_pipeline_text_to_response():
    bus = EventBus()
    brain = Brain(bus=bus, claude=FakeClaude(), dispatcher=FakeDispatcher(), registry=FakeRegistry(), config=ShannonConfig())
    await brain.start()
    events = []

    async def capture(e):
        events.append(e)

    bus.subscribe(LLMResponseEvent, capture)
    await bus.publish(UserInput(text="Hello", source="text"))
    assert len(events) == 1
    assert events[0].text == "Response #1"

async def test_chat_message_round_trip():
    bus = EventBus()
    brain = Brain(bus=bus, claude=FakeClaude(), dispatcher=FakeDispatcher(), registry=FakeRegistry(), config=ShannonConfig())
    await brain.start()
    responses = []

    async def capture(e):
        responses.append(e)

    bus.subscribe(ChatResponse, capture)
    await bus.publish(ChatMessage(text="hi", author="user", platform="discord", channel="general", message_id="msg_1"))
    assert len(responses) == 1
    assert responses[0].platform == "discord"
    assert responses[0].reply_to == "msg_1"
