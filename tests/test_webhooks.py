"""Tests for webhook models, config, handlers, and server."""

import asyncio
import hashlib
import hmac
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from shannon.config import Settings, WebhookEndpointConfig, WebhooksConfig
from shannon.core.bus import EventBus, EventType, WebhookReceived
from shannon.webhooks.handlers import (
    normalize_generic_event,
    normalize_github_event,
    normalize_sentry_event,
    validate_generic_secret,
    validate_github_signature,
    validate_sentry_signature,
)
from shannon.webhooks.models import WebhookEvent
from shannon.webhooks.server import WebhookServer


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestWebhookEvent:
    def test_field_values(self):
        event = WebhookEvent(
            source="github",
            event_type="push",
            summary="pushed 3 commits",
            payload={"ref": "refs/heads/main"},
            channel_target="dev-channel",
        )
        assert event.source == "github"
        assert event.event_type == "push"
        assert event.summary == "pushed 3 commits"
        assert event.payload == {"ref": "refs/heads/main"}
        assert event.channel_target == "dev-channel"

    def test_defaults(self):
        event = WebhookEvent(source="test", event_type="ping", summary="hi")
        assert event.payload == {}
        assert event.channel_target == ""


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestWebhooksConfig:
    def test_defaults(self):
        cfg = WebhooksConfig()
        assert cfg.enabled is False
        assert cfg.port == 8420
        assert cfg.bind == "0.0.0.0"
        assert cfg.endpoints == []

    def test_endpoint_fields(self):
        ep = WebhookEndpointConfig(
            name="github",
            path="/webhooks/github",
            secret="s3cret",
            channel="dev",
            prompt_template="A push happened: {summary}",
        )
        assert ep.name == "github"
        assert ep.path == "/webhooks/github"
        assert ep.secret == "s3cret"
        assert ep.channel == "dev"
        assert ep.prompt_template == "A push happened: {summary}"

    def test_settings_has_webhooks(self):
        settings = Settings()
        assert hasattr(settings, "webhooks")
        assert isinstance(settings.webhooks, WebhooksConfig)


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestGitHubSignature:
    def test_valid_signature(self):
        secret = "my-secret"
        body = b'{"action": "push"}'
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert validate_github_signature(body, sig, secret) is True

    def test_invalid_signature(self):
        body = b'{"action": "push"}'
        assert validate_github_signature(body, "sha256=bad", "my-secret") is False

    def test_missing_signature(self):
        body = b'{"action": "push"}'
        assert validate_github_signature(body, "", "my-secret") is False

    def test_no_secret_configured_rejects(self):
        body = b'{"action": "push"}'
        assert validate_github_signature(body, "", "") is False


class TestGenericSecret:
    def test_valid(self):
        assert validate_generic_secret("token123", "token123") is True

    def test_invalid(self):
        assert validate_generic_secret("wrong", "token123") is False

    def test_no_secret_configured_rejects(self):
        assert validate_generic_secret("", "") is False


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------

class TestNormalizeGitHub:
    def test_push(self):
        payload = {
            "ref": "refs/heads/main",
            "pusher": {"name": "alice"},
            "commits": [{"id": "abc"}, {"id": "def"}],
            "repository": {"full_name": "org/repo"},
        }
        event = normalize_github_event("push", payload, "dev-channel")
        assert event.source == "github"
        assert event.event_type == "push"
        assert "alice" in event.summary
        assert "2 commit(s)" in event.summary
        assert "org/repo" in event.summary
        assert event.channel_target == "dev-channel"

    def test_pull_request(self):
        payload = {
            "action": "opened",
            "pull_request": {
                "number": 42,
                "title": "Add feature",
                "user": {"login": "bob"},
            },
            "repository": {"full_name": "org/repo"},
        }
        event = normalize_github_event("pull_request", payload, "pr-channel")
        assert event.source == "github"
        assert event.event_type == "pull_request"
        assert "bob" in event.summary
        assert "opened" in event.summary
        assert "#42" in event.summary
        assert event.channel_target == "pr-channel"


class TestNormalizeSentry:
    def test_sentry_event(self):
        payload = {
            "project_name": "my-app",
            "data": {
                "event": {
                    "title": "ZeroDivisionError",
                    "level": "error",
                },
            },
        }
        event = normalize_sentry_event(payload, "alerts")
        assert event.source == "sentry"
        assert event.event_type == "alert"
        assert "ZeroDivisionError" in event.summary
        assert "my-app" in event.summary
        assert event.channel_target == "alerts"


class TestNormalizeGeneric:
    def test_generic_event(self):
        payload = {"message": "Deploy complete", "event_type": "deploy"}
        event = normalize_generic_event(payload, "ops")
        assert event.source == "generic"
        assert event.event_type == "deploy"
        assert "Deploy complete" in event.summary
        assert event.channel_target == "ops"


# ---------------------------------------------------------------------------
# Server tests
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def github_endpoint():
    return WebhookEndpointConfig(
        name="github",
        path="/webhooks/github",
        secret="gh-secret",
        channel="dev",
    )


@pytest.fixture
def webhook_config(github_endpoint):
    return WebhooksConfig(
        enabled=True,
        port=0,  # not used by test client
        endpoints=[github_endpoint],
    )


@pytest.fixture
def server(webhook_config, bus):
    return WebhookServer(webhook_config, bus)


@pytest.fixture
async def client(server):
    app = server._build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


class TestWebhookServer:
    async def test_malformed_payload_returns_400(self, client):
        resp = await client.post(
            "/webhooks/github",
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400

    async def test_invalid_signature_returns_401(self, client):
        payload = {"ref": "refs/heads/main"}
        resp = await client.post(
            "/webhooks/github",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=invalid"},
        )
        assert resp.status == 401

    async def test_valid_github_push_returns_200(self, client, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.WEBHOOK_RECEIVED, handler)
        await bus.start()

        payload = {
            "ref": "refs/heads/main",
            "pusher": {"name": "alice"},
            "commits": [{"id": "abc"}],
            "repository": {"full_name": "org/repo"},
        }
        body = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(b"gh-secret", body, hashlib.sha256).hexdigest()

        resp = await client.post(
            "/webhooks/github",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "push",
            },
        )
        assert resp.status == 200

        await asyncio.sleep(0.1)
        assert len(received) == 1
        assert received[0].data["source"] == "github"
        assert received[0].data["event_type"] == "push"

        await bus.stop()

    async def test_unknown_path_returns_404(self, client):
        resp = await client.post("/webhooks/unknown", json={"test": True})
        assert resp.status == 404

    async def test_channel_routing_from_config(self, client, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.WEBHOOK_RECEIVED, handler)
        await bus.start()

        payload = {
            "ref": "refs/heads/main",
            "pusher": {"name": "alice"},
            "commits": [],
            "repository": {"full_name": "org/repo"},
        }
        body = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(b"gh-secret", body, hashlib.sha256).hexdigest()

        resp = await client.post(
            "/webhooks/github",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "push",
            },
        )
        assert resp.status == 200

        await asyncio.sleep(0.1)
        assert received[0].data["channel_target"] == "dev"

        await bus.stop()
