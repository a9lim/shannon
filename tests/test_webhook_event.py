"""Tests for WEBHOOK_RECEIVED event type on the bus."""

import asyncio
import pytest
from shannon.core.bus import EventBus, EventType, WebhookReceived


class TestWebhookEventType:
    def test_webhook_received_exists(self):
        assert EventType.WEBHOOK_RECEIVED == "webhook.received"

    async def test_publish_subscribe_webhook(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.WEBHOOK_RECEIVED, handler)
        await bus.start()

        event = WebhookReceived(data={"source": "github", "summary": "test push"})
        await bus.publish(event)
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].type == EventType.WEBHOOK_RECEIVED
        assert received[0].data["source"] == "github"

        await bus.stop()
