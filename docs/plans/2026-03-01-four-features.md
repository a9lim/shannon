# Shannon Four Features Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add webhook triggers, persistent memory, multi-step planning, and pause/resume to Shannon.

**Architecture:** Each feature is a new package under `shannon/` that integrates via the existing EventBus and tool registration patterns. All features follow the existing lifecycle (`start()`/`stop()`), config (Pydantic sub-models added to `Settings`), and permission patterns.

**Tech Stack:** Python 3.11+, aiohttp (webhooks), aiosqlite (memory + plans), existing EventBus, existing tool/command patterns.

---

## Task 1: Add `aiohttp` dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add aiohttp to dependencies**

In `pyproject.toml`, add `"aiohttp>=3.9",` to the dependencies list after `"aiosqlite>=0.20",`.

**Step 2: Install updated dependencies**

Run: `pip install -e ".[dev]"`
Expected: SUCCESS, aiohttp installed.

**Step 3: Commit**

```
feat: add aiohttp dependency for webhook server
```

---

## Task 2: Add `WEBHOOK_RECEIVED` event type to EventBus

**Files:**
- Modify: `shannon/core/bus.py`

**Step 1: Write test for new event type**

Create `tests/test_webhook_event.py`:

```python
"""Tests for WebhookReceived event type."""

import asyncio
import pytest
from shannon.core.bus import EventBus, EventType, WebhookReceived


class TestWebhookEvent:
    async def test_webhook_event_type_exists(self):
        assert EventType.WEBHOOK_RECEIVED == "webhook.received"

    async def test_publish_subscribe_webhook(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.WEBHOOK_RECEIVED, handler)
        await bus.start()

        event = WebhookReceived(data={"source": "github", "summary": "push to main"})
        await bus.publish(event)
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].type == EventType.WEBHOOK_RECEIVED
        assert received[0].data["source"] == "github"

        await bus.stop()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhook_event.py -v`
Expected: FAIL — `WebhookReceived` not defined, `WEBHOOK_RECEIVED` not in EventType.

**Step 3: Add `WEBHOOK_RECEIVED` to EventType and create `WebhookReceived` event class**

In `shannon/core/bus.py`:

Add to `EventType` enum:
```python
WEBHOOK_RECEIVED = "webhook.received"
```

Add new event dataclass after `SchedulerTrigger`:
```python
@dataclass
class WebhookReceived(Event):
    type: EventType = field(default=EventType.WEBHOOK_RECEIVED, init=False)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_webhook_event.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All existing tests still pass.

**Step 6: Commit**

```
feat: add WEBHOOK_RECEIVED event type to EventBus
```

---

## Task 3: Webhook models and config

**Files:**
- Create: `shannon/webhooks/__init__.py`
- Create: `shannon/webhooks/models.py`
- Modify: `shannon/config.py`

**Step 1: Write test for webhook models and config**

Create `tests/test_webhooks.py`:

```python
"""Tests for webhook models and config."""

import pytest
from shannon.webhooks.models import WebhookEvent
from shannon.config import WebhookEndpointConfig, WebhooksConfig, Settings


class TestWebhookEvent:
    def test_webhook_event_fields(self):
        evt = WebhookEvent(
            source="github",
            event_type="push",
            summary="Push to main by user",
            payload={"ref": "refs/heads/main"},
            channel_target="discord:123456",
        )
        assert evt.source == "github"
        assert evt.event_type == "push"
        assert evt.summary == "Push to main by user"
        assert evt.payload == {"ref": "refs/heads/main"}
        assert evt.channel_target == "discord:123456"

    def test_webhook_event_defaults(self):
        evt = WebhookEvent(
            source="generic",
            event_type="unknown",
            summary="Something happened",
            payload={},
            channel_target="discord:123",
        )
        assert evt.payload == {}


class TestWebhooksConfig:
    def test_default_config(self):
        cfg = WebhooksConfig()
        assert cfg.enabled is False
        assert cfg.port == 8420
        assert cfg.bind == "0.0.0.0"
        assert cfg.endpoints == []

    def test_endpoint_config(self):
        ep = WebhookEndpointConfig(
            name="github",
            path="/hooks/github",
            secret="mysecret",
            channel="discord:123",
        )
        assert ep.name == "github"
        assert ep.prompt_template == ""

    def test_settings_has_webhooks(self):
        s = Settings()
        assert hasattr(s, "webhooks")
        assert s.webhooks.enabled is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhooks.py -v`
Expected: FAIL — modules don't exist.

**Step 3: Create webhook models**

Create `shannon/webhooks/__init__.py`:
```python
"""Webhook/event-driven triggers."""

from shannon.webhooks.models import WebhookEvent

__all__ = ["WebhookEvent"]
```

Create `shannon/webhooks/models.py`:
```python
"""Webhook event models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WebhookEvent:
    """Normalized webhook event across providers."""

    source: str  # "github", "sentry", "generic"
    event_type: str  # "push", "pull_request", "alert", etc.
    summary: str  # Human-readable summary
    payload: dict[str, Any]  # Raw payload
    channel_target: str  # "discord:123456" or "signal:+1234567890"
```

**Step 4: Add config classes to `shannon/config.py`**

Add before `Settings`:
```python
class WebhookEndpointConfig(BaseModel):
    name: str = ""
    path: str = ""
    secret: str = ""
    channel: str = ""
    prompt_template: str = ""


class WebhooksConfig(BaseModel):
    enabled: bool = False
    port: int = 8420
    bind: str = "0.0.0.0"
    endpoints: list[WebhookEndpointConfig] = Field(default_factory=list)
```

Add `webhooks` field to `Settings`:
```python
webhooks: WebhooksConfig = Field(default_factory=WebhooksConfig)
```

**Step 5: Run tests**

Run: `pytest tests/test_webhooks.py -v`
Expected: PASS

Run: `pytest tests/ -v`
Expected: All pass.

**Step 6: Commit**

```
feat: add webhook models and config
```

---

## Task 4: Webhook handlers (HMAC validation + event normalization)

**Files:**
- Create: `shannon/webhooks/handlers.py`

**Step 1: Write tests for HMAC validation and normalization**

Add to `tests/test_webhooks.py`:

```python
import hashlib
import hmac
import json
from shannon.webhooks.handlers import validate_github_signature, validate_generic_secret, normalize_github_event, normalize_sentry_event, normalize_generic_event


class TestHMACValidation:
    def test_github_signature_valid(self):
        secret = "mysecret"
        body = b'{"action": "push"}'
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert validate_github_signature(body, sig, secret) is True

    def test_github_signature_invalid(self):
        assert validate_github_signature(b"body", "sha256=wrong", "secret") is False

    def test_github_signature_missing(self):
        assert validate_github_signature(b"body", "", "secret") is False

    def test_github_signature_no_secret_configured(self):
        # If no secret configured, skip validation
        assert validate_github_signature(b"body", "", "") is True

    def test_generic_secret_valid(self):
        assert validate_generic_secret("correct", "correct") is True

    def test_generic_secret_invalid(self):
        assert validate_generic_secret("wrong", "correct") is False

    def test_generic_secret_no_secret_configured(self):
        assert validate_generic_secret("", "") is True


class TestEventNormalization:
    def test_normalize_github_push(self):
        payload = {
            "ref": "refs/heads/main",
            "repository": {"full_name": "user/repo"},
            "pusher": {"name": "user"},
            "commits": [{"message": "fix bug"}],
        }
        evt = normalize_github_event("push", payload, "discord:123")
        assert evt.source == "github"
        assert evt.event_type == "push"
        assert "user/repo" in evt.summary
        assert evt.channel_target == "discord:123"

    def test_normalize_github_pull_request(self):
        payload = {
            "action": "opened",
            "pull_request": {"title": "Add feature", "number": 42},
            "repository": {"full_name": "user/repo"},
        }
        evt = normalize_github_event("pull_request", payload, "discord:123")
        assert evt.event_type == "pull_request"
        assert "Add feature" in evt.summary

    def test_normalize_sentry_event(self):
        payload = {
            "data": {
                "event": {
                    "title": "ZeroDivisionError",
                    "culprit": "app.views.divide",
                },
            },
        }
        evt = normalize_sentry_event(payload, "discord:123")
        assert evt.source == "sentry"
        assert "ZeroDivisionError" in evt.summary

    def test_normalize_generic_event(self):
        payload = {"message": "deployment complete", "status": "success"}
        evt = normalize_generic_event(payload, "discord:123")
        assert evt.source == "generic"
        assert evt.event_type == "generic"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhooks.py::TestHMACValidation -v`
Expected: FAIL — module not found.

**Step 3: Implement handlers**

Create `shannon/webhooks/handlers.py`:
```python
"""Webhook handler functions: validation and event normalization."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from shannon.webhooks.models import WebhookEvent


def validate_github_signature(body: bytes, signature: str, secret: str) -> bool:
    """Validate GitHub X-Hub-Signature-256 HMAC."""
    if not secret:
        return True
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def validate_sentry_signature(body: bytes, signature: str, secret: str) -> bool:
    """Validate Sentry sentry-hook-signature HMAC."""
    if not secret:
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def validate_generic_secret(provided: str, configured: str) -> bool:
    """Validate generic X-Webhook-Secret header."""
    if not configured:
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided, configured)


def normalize_github_event(
    event_type: str, payload: dict[str, Any], channel: str
) -> WebhookEvent:
    """Normalize a GitHub webhook payload."""
    repo = payload.get("repository", {}).get("full_name", "unknown")

    if event_type == "push":
        pusher = payload.get("pusher", {}).get("name", "unknown")
        ref = payload.get("ref", "")
        branch = ref.split("/")[-1] if "/" in ref else ref
        commits = payload.get("commits", [])
        summary = f"{pusher} pushed {len(commits)} commit(s) to {branch} in {repo}"
    elif event_type == "pull_request":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        title = pr.get("title", "")
        number = pr.get("number", "")
        summary = f"PR #{number} {action}: {title} in {repo}"
    elif event_type == "issues":
        action = payload.get("action", "")
        issue = payload.get("issue", {})
        title = issue.get("title", "")
        number = issue.get("number", "")
        summary = f"Issue #{number} {action}: {title} in {repo}"
    elif event_type == "workflow_run":
        wf = payload.get("workflow_run", {})
        name = wf.get("name", "")
        conclusion = wf.get("conclusion", "")
        summary = f"Workflow '{name}' {conclusion} in {repo}"
    else:
        summary = f"GitHub {event_type} event in {repo}"

    return WebhookEvent(
        source="github",
        event_type=event_type,
        summary=summary,
        payload=payload,
        channel_target=channel,
    )


def normalize_sentry_event(
    payload: dict[str, Any], channel: str
) -> WebhookEvent:
    """Normalize a Sentry webhook payload."""
    data = payload.get("data", {})
    event = data.get("event", {})
    title = event.get("title", "Unknown error")
    culprit = event.get("culprit", "")
    summary = f"Sentry alert: {title}"
    if culprit:
        summary += f" in {culprit}"

    return WebhookEvent(
        source="sentry",
        event_type="alert",
        summary=summary,
        payload=payload,
        channel_target=channel,
    )


def normalize_generic_event(
    payload: dict[str, Any], channel: str
) -> WebhookEvent:
    """Normalize a generic webhook payload."""
    summary = payload.get("message", payload.get("summary", str(payload)[:200]))
    return WebhookEvent(
        source="generic",
        event_type="generic",
        summary=str(summary),
        payload=payload,
        channel_target=channel,
    )
```

**Step 4: Run tests**

Run: `pytest tests/test_webhooks.py -v`
Expected: All pass.

**Step 5: Commit**

```
feat: add webhook HMAC validation and event normalization
```

---

## Task 5: Webhook HTTP server

**Files:**
- Create: `shannon/webhooks/server.py`
- Modify: `shannon/webhooks/__init__.py`

**Step 1: Write tests for webhook server**

Add to `tests/test_webhooks.py`:

```python
import hashlib
import hmac
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer
from shannon.webhooks.server import WebhookServer
from shannon.config import WebhooksConfig, WebhookEndpointConfig
from shannon.core.bus import EventBus, EventType


class TestWebhookServer:
    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def config(self):
        return WebhooksConfig(
            enabled=True,
            port=0,  # random port for tests
            endpoints=[
                WebhookEndpointConfig(
                    name="github",
                    path="/hooks/github",
                    secret="ghsecret",
                    channel="discord:123",
                    prompt_template="GitHub {event_type}: {summary}",
                ),
                WebhookEndpointConfig(
                    name="generic",
                    path="/hooks/general",
                    secret="",
                    channel="discord:456",
                ),
            ],
        )

    @pytest.fixture
    async def server(self, bus, config):
        srv = WebhookServer(config, bus)
        return srv

    async def test_malformed_payload_returns_400(self, server, bus):
        app = server._build_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/hooks/github", data=b"not json")
            assert resp.status == 400

    async def test_invalid_signature_returns_401(self, server, bus):
        app = server._build_app()
        async with TestClient(TestServer(app)) as client:
            body = json.dumps({"action": "push"}).encode()
            resp = await client.post(
                "/hooks/github",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "push",
                    "X-Hub-Signature-256": "sha256=wrong",
                },
            )
            assert resp.status == 401

    async def test_valid_github_push_returns_200(self, server, bus):
        received = []
        async def handler(event):
            received.append(event)
        bus.subscribe(EventType.WEBHOOK_RECEIVED, handler)
        await bus.start()

        app = server._build_app()
        async with TestClient(TestServer(app)) as client:
            body = json.dumps({
                "ref": "refs/heads/main",
                "repository": {"full_name": "user/repo"},
                "pusher": {"name": "user"},
                "commits": [],
            }).encode()
            secret = "ghsecret"
            sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            resp = await client.post(
                "/hooks/github",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "push",
                    "X-Hub-Signature-256": sig,
                },
            )
            assert resp.status == 200

        await asyncio.sleep(0.1)
        assert len(received) == 1
        await bus.stop()

    async def test_unknown_path_returns_404(self, server, bus):
        app = server._build_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/hooks/unknown")
            assert resp.status == 404

    async def test_channel_routing(self, server, bus, config):
        """Verify the event carries the correct channel_target from config."""
        received = []
        async def handler(event):
            received.append(event)
        bus.subscribe(EventType.WEBHOOK_RECEIVED, handler)
        await bus.start()

        app = server._build_app()
        async with TestClient(TestServer(app)) as client:
            body = json.dumps({"message": "hello"}).encode()
            resp = await client.post(
                "/hooks/general",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            assert resp.status == 200

        await asyncio.sleep(0.1)
        assert len(received) == 1
        assert received[0].data["event"].channel_target == "discord:456"
        await bus.stop()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhooks.py::TestWebhookServer -v`
Expected: FAIL — WebhookServer not found.

**Step 3: Implement WebhookServer**

Create `shannon/webhooks/server.py`:
```python
"""Lightweight aiohttp webhook server."""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from shannon.config import WebhookEndpointConfig, WebhooksConfig
from shannon.core.bus import EventBus, WebhookReceived
from shannon.webhooks.handlers import (
    normalize_generic_event,
    normalize_github_event,
    normalize_sentry_event,
    validate_generic_secret,
    validate_github_signature,
    validate_sentry_signature,
)
from shannon.webhooks.models import WebhookEvent
from shannon.utils.logging import get_logger

log = get_logger(__name__)


class WebhookServer:
    """Runs an aiohttp server to receive webhook events."""

    def __init__(self, config: WebhooksConfig, bus: EventBus) -> None:
        self._config = config
        self._bus = bus
        self._runner: web.AppRunner | None = None
        self._endpoint_map: dict[str, WebhookEndpointConfig] = {
            ep.path: ep for ep in config.endpoints
        }

    def _build_app(self) -> web.Application:
        app = web.Application()
        for path in self._endpoint_map:
            app.router.add_post(path, self._handle_webhook)
        return app

    async def start(self) -> None:
        if not self._config.enabled:
            return
        app = self._build_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._config.bind, self._config.port)
        await site.start()
        log.info("webhook_server_started", port=self._config.port, bind=self._config.bind)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        path = request.path
        endpoint = self._endpoint_map.get(path)
        if not endpoint:
            return web.Response(status=404, text="Unknown endpoint")

        # Read body
        body = await request.read()

        # Parse JSON
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.Response(status=400, text="Invalid JSON")

        # Validate signature based on endpoint name
        if not self._validate(endpoint, request, body):
            return web.Response(status=401, text="Invalid signature")

        # Normalize event
        event = self._normalize(endpoint, request, payload)

        # Publish to bus
        await self._bus.publish(
            WebhookReceived(data={
                "event": event,
                "prompt_template": endpoint.prompt_template,
            })
        )

        log.info("webhook_received", source=event.source, event_type=event.event_type)
        return web.Response(status=200, text="OK")

    def _validate(
        self, endpoint: WebhookEndpointConfig, request: web.Request, body: bytes
    ) -> bool:
        name = endpoint.name.lower()
        if name == "github":
            sig = request.headers.get("X-Hub-Signature-256", "")
            return validate_github_signature(body, sig, endpoint.secret)
        elif name == "sentry":
            sig = request.headers.get("sentry-hook-signature", "")
            return validate_sentry_signature(body, sig, endpoint.secret)
        else:
            provided = request.headers.get("X-Webhook-Secret", "")
            return validate_generic_secret(provided, endpoint.secret)

    def _normalize(
        self,
        endpoint: WebhookEndpointConfig,
        request: web.Request,
        payload: dict[str, Any],
    ) -> WebhookEvent:
        name = endpoint.name.lower()
        channel = endpoint.channel
        if name == "github":
            event_type = request.headers.get("X-GitHub-Event", "unknown")
            return normalize_github_event(event_type, payload, channel)
        elif name == "sentry":
            return normalize_sentry_event(payload, channel)
        else:
            return normalize_generic_event(payload, channel)
```

Update `shannon/webhooks/__init__.py`:
```python
"""Webhook/event-driven triggers."""

from shannon.webhooks.models import WebhookEvent
from shannon.webhooks.server import WebhookServer

__all__ = ["WebhookEvent", "WebhookServer"]
```

**Step 4: Run tests**

Run: `pytest tests/test_webhooks.py -v`
Expected: All pass.

Run: `pytest tests/ -v`
Expected: All pass.

**Step 5: Commit**

```
feat: add webhook HTTP server with signature validation
```

---

## Task 6: Wire webhooks into Shannon main

**Files:**
- Modify: `shannon/main.py`

**Step 1: Integrate WebhookServer into Shannon lifecycle**

In `shannon/main.py`:

Add import:
```python
from shannon.webhooks.server import WebhookServer
```

In `Shannon.__init__()`, after transports init:
```python
self._webhook_server = WebhookServer(settings.webhooks, self.bus)
```

In `Shannon.start()`, after transports start but before `bus.start()`:
```python
await self._webhook_server.start()
```

In `Shannon.stop()`, after transports stop:
```python
await self._webhook_server.stop()
```

**Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All pass.

**Step 3: Commit**

```
feat: wire webhook server into Shannon lifecycle
```

---

## Task 7: Persistent memory store

**Files:**
- Create: `shannon/memory/__init__.py`
- Create: `shannon/memory/store.py`

**Step 1: Write tests for MemoryStore**

Create `tests/test_memory.py`:

```python
"""Tests for persistent memory store."""

import pytest
from pathlib import Path
from shannon.memory.store import MemoryStore


@pytest.fixture
async def store(tmp_path):
    s = MemoryStore(db_path=tmp_path / "memory.db")
    await s.start()
    yield s
    await s.stop()


class TestMemoryCRUD:
    async def test_set_and_get(self, store):
        await store.set("name", "Shannon", category="identity", source="self")
        result = await store.get("name")
        assert result is not None
        assert result["value"] == "Shannon"
        assert result["category"] == "identity"
        assert result["source"] == "self"

    async def test_get_nonexistent(self, store):
        result = await store.get("nonexistent")
        assert result is None

    async def test_update_existing(self, store):
        await store.set("key", "old_value")
        await store.set("key", "new_value")
        result = await store.get("key")
        assert result["value"] == "new_value"

    async def test_delete(self, store):
        await store.set("key", "value")
        deleted = await store.delete("key")
        assert deleted is True
        result = await store.get("key")
        assert result is None

    async def test_delete_nonexistent(self, store):
        deleted = await store.delete("nonexistent")
        assert deleted is False


class TestMemorySearch:
    async def test_search_by_key(self, store):
        await store.set("favorite_color", "blue")
        await store.set("favorite_food", "pizza")
        await store.set("name", "Shannon")
        results = await store.search("favorite")
        assert len(results) == 2

    async def test_search_by_value(self, store):
        await store.set("color", "blue sky")
        await store.set("mood", "blue feeling")
        results = await store.search("blue")
        assert len(results) == 2

    async def test_search_no_results(self, store):
        await store.set("key", "value")
        results = await store.search("nonexistent")
        assert len(results) == 0


class TestMemoryCategory:
    async def test_list_category(self, store):
        await store.set("a", "1", category="prefs")
        await store.set("b", "2", category="prefs")
        await store.set("c", "3", category="facts")
        results = await store.list_category("prefs")
        assert len(results) == 2

    async def test_list_empty_category(self, store):
        results = await store.list_category("empty")
        assert len(results) == 0


class TestExportContext:
    async def test_export_empty(self, store):
        result = await store.export_context()
        assert result == ""

    async def test_export_with_memories(self, store):
        await store.set("name", "Shannon", category="identity")
        await store.set("goal", "Be helpful", category="identity")
        result = await store.export_context()
        assert "name" in result
        assert "Shannon" in result

    async def test_export_truncation(self, store):
        # Add many large memories
        for i in range(100):
            await store.set(f"key_{i}", "x" * 200, category="bulk")
        result = await store.export_context(max_tokens=500)
        # Should be bounded, not contain all 100 entries
        assert len(result) < 100 * 200
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory.py -v`
Expected: FAIL — module not found.

**Step 3: Implement MemoryStore**

Create `shannon/memory/__init__.py`:
```python
"""Persistent cross-session memory."""

from shannon.memory.store import MemoryStore

__all__ = ["MemoryStore"]
```

Create `shannon/memory/store.py`:
```python
"""Key-value memory store backed by SQLite."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from shannon.utils.logging import get_logger

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT DEFAULT ''
);
"""


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def set(
        self,
        key: str,
        value: str,
        category: str = "general",
        source: str = "",
    ) -> None:
        assert self._db is not None
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO memory (key, value, category, created_at, updated_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=?, category=?, updated_at=?, source=?",
            (key, value, category, now, now, source, value, category, now, source),
        )
        await self._db.commit()

    async def get(self, key: str) -> dict[str, Any] | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT key, value, category, created_at, updated_at, source "
            "FROM memory WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "key": row[0],
            "value": row[1],
            "category": row[2],
            "created_at": row[3],
            "updated_at": row[4],
            "source": row[5],
        }

    async def delete(self, key: str) -> bool:
        assert self._db is not None
        cursor = await self._db.execute("DELETE FROM memory WHERE key = ?", (key,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def search(self, query: str) -> list[dict[str, Any]]:
        assert self._db is not None
        pattern = f"%{query}%"
        cursor = await self._db.execute(
            "SELECT key, value, category, created_at, updated_at, source "
            "FROM memory WHERE key LIKE ? OR value LIKE ? "
            "ORDER BY updated_at DESC",
            (pattern, pattern),
        )
        rows = await cursor.fetchall()
        return [
            {"key": r[0], "value": r[1], "category": r[2],
             "created_at": r[3], "updated_at": r[4], "source": r[5]}
            for r in rows
        ]

    async def list_category(self, category: str) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT key, value, category, created_at, updated_at, source "
            "FROM memory WHERE category = ? ORDER BY updated_at DESC",
            (category,),
        )
        rows = await cursor.fetchall()
        return [
            {"key": r[0], "value": r[1], "category": r[2],
             "created_at": r[3], "updated_at": r[4], "source": r[5]}
            for r in rows
        ]

    async def clear(self) -> int:
        assert self._db is not None
        cursor = await self._db.execute("DELETE FROM memory")
        await self._db.commit()
        return cursor.rowcount

    async def export_context(self, max_tokens: int = 2000) -> str:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT key, value, category FROM memory ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        if not rows:
            return ""

        lines: list[str] = []
        char_budget = max_tokens * 4  # rough chars-per-token estimate
        used = 0
        for key, value, category in rows:
            line = f"[{category}] {key}: {value}"
            if used + len(line) > char_budget:
                lines.append(f"... ({len(rows) - len(lines)} more memories truncated)")
                break
            lines.append(line)
            used += len(line)

        return "\n".join(lines)
```

**Step 4: Run tests**

Run: `pytest tests/test_memory.py -v`
Expected: All pass.

**Step 5: Commit**

```
feat: add persistent key-value memory store
```

---

## Task 8: Memory tools (LLM tool integration)

**Files:**
- Create: `shannon/tools/memory_tools.py`

**Step 1: Write tests for memory tools**

Create `tests/test_memory_tools.py`:

```python
"""Tests for memory LLM tools."""

import pytest
from pathlib import Path
from shannon.memory.store import MemoryStore
from shannon.tools.memory_tools import MemorySetTool, MemoryGetTool, MemoryDeleteTool
from shannon.core.auth import PermissionLevel


@pytest.fixture
async def store(tmp_path):
    s = MemoryStore(db_path=tmp_path / "memory.db")
    await s.start()
    yield s
    await s.stop()


class TestMemorySetTool:
    def test_metadata(self):
        tool = MemorySetTool(MemoryStore(Path("/tmp/x")))
        assert tool.name == "memory_set"
        assert tool.required_permission == PermissionLevel.TRUSTED

    async def test_set_value(self, store):
        tool = MemorySetTool(store)
        result = await tool.execute(key="name", value="Shannon")
        assert result.success is True
        stored = await store.get("name")
        assert stored["value"] == "Shannon"

    async def test_set_with_category(self, store):
        tool = MemorySetTool(store)
        result = await tool.execute(key="color", value="blue", category="prefs")
        assert result.success is True
        stored = await store.get("color")
        assert stored["category"] == "prefs"


class TestMemoryGetTool:
    def test_metadata(self):
        tool = MemoryGetTool(MemoryStore(Path("/tmp/x")))
        assert tool.name == "memory_get"
        assert tool.required_permission == PermissionLevel.TRUSTED

    async def test_get_by_key(self, store):
        await store.set("name", "Shannon")
        tool = MemoryGetTool(store)
        result = await tool.execute(key="name")
        assert result.success is True
        assert "Shannon" in result.output

    async def test_get_nonexistent(self, store):
        tool = MemoryGetTool(store)
        result = await tool.execute(key="nonexistent")
        assert result.success is True
        assert "not found" in result.output.lower()

    async def test_search(self, store):
        await store.set("fav_color", "blue")
        await store.set("fav_food", "pizza")
        tool = MemoryGetTool(store)
        result = await tool.execute(query="fav")
        assert result.success is True
        assert "blue" in result.output
        assert "pizza" in result.output


class TestMemoryDeleteTool:
    def test_metadata(self):
        tool = MemoryDeleteTool(MemoryStore(Path("/tmp/x")))
        assert tool.name == "memory_delete"
        assert tool.required_permission == PermissionLevel.OPERATOR

    async def test_delete(self, store):
        await store.set("key", "value")
        tool = MemoryDeleteTool(store)
        result = await tool.execute(key="key")
        assert result.success is True
        assert await store.get("key") is None

    async def test_delete_nonexistent(self, store):
        tool = MemoryDeleteTool(store)
        result = await tool.execute(key="nope")
        assert result.success is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_tools.py -v`
Expected: FAIL — module not found.

**Step 3: Implement memory tools**

Create `shannon/tools/memory_tools.py`:
```python
"""Memory LLM tools: set, get, delete."""

from __future__ import annotations

from typing import Any

from shannon.core.auth import PermissionLevel
from shannon.memory.store import MemoryStore
from shannon.tools.base import BaseTool, ToolResult


class MemorySetTool(BaseTool):
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "memory_set"

    @property
    def description(self) -> str:
        return "Store a key-value pair in persistent memory. Survives restarts."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key."},
                "value": {"type": "string", "description": "Value to store."},
                "category": {
                    "type": "string",
                    "description": "Optional category (default: general).",
                    "default": "general",
                },
            },
            "required": ["key", "value"],
        }

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.TRUSTED

    async def execute(self, **kwargs: Any) -> ToolResult:
        key = kwargs["key"]
        value = kwargs["value"]
        category = kwargs.get("category", "general")
        await self._store.set(key, value, category=category, source="llm")
        return ToolResult(success=True, output=f"Stored: {key} = {value}")


class MemoryGetTool(BaseTool):
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return "Retrieve a memory by key, or search memories by query."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Exact key to look up."},
                "query": {"type": "string", "description": "Search query (searches keys and values)."},
            },
        }

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.TRUSTED

    async def execute(self, **kwargs: Any) -> ToolResult:
        key = kwargs.get("key")
        query = kwargs.get("query")

        if key:
            result = await self._store.get(key)
            if result:
                return ToolResult(
                    success=True,
                    output=f"[{result['category']}] {result['key']}: {result['value']}",
                )
            return ToolResult(success=True, output=f"Key '{key}' not found.")

        if query:
            results = await self._store.search(query)
            if not results:
                return ToolResult(success=True, output=f"No memories matching '{query}'.")
            lines = [f"[{r['category']}] {r['key']}: {r['value']}" for r in results]
            return ToolResult(success=True, output="\n".join(lines))

        return ToolResult(success=False, error="Provide either 'key' or 'query'.")


class MemoryDeleteTool(BaseTool):
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "memory_delete"

    @property
    def description(self) -> str:
        return "Delete a memory entry by key."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key to delete."},
            },
            "required": ["key"],
        }

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.OPERATOR

    async def execute(self, **kwargs: Any) -> ToolResult:
        key = kwargs["key"]
        deleted = await self._store.delete(key)
        if deleted:
            return ToolResult(success=True, output=f"Deleted memory: {key}")
        return ToolResult(success=False, error=f"Key '{key}' not found.")
```

**Step 4: Run tests**

Run: `pytest tests/test_memory_tools.py -v`
Expected: All pass.

**Step 5: Commit**

```
feat: add memory LLM tools (set, get, delete)
```

---

## Task 9: Wire memory into Shannon (store, tools, system prompt, commands)

**Files:**
- Modify: `shannon/main.py`
- Modify: `shannon/core/system_prompt.py`
- Modify: `shannon/core/commands.py`

**Step 1: Write tests for memory commands**

Add to `tests/test_commands.py`:

```python
class TestMemoryCommands:
    async def test_memory_list(self, handler, send_fn):
        # Handler needs memory_store attribute
        handler._memory_store = AsyncMock()
        handler._memory_store.search = AsyncMock(return_value=[
            {"key": "name", "value": "Shannon", "category": "identity",
             "created_at": "", "updated_at": "", "source": ""},
        ])
        handler._memory_store.list_category = AsyncMock(return_value=[])
        # We need to mock the export for /memory list
        handler._memory_store.export_context = AsyncMock(return_value="[identity] name: Shannon")
        await handler.handle("discord", "ch1", "user1", "/memory")
        send_fn.assert_awaited()

    async def test_memory_search(self, handler, send_fn):
        handler._memory_store = AsyncMock()
        handler._memory_store.search = AsyncMock(return_value=[
            {"key": "color", "value": "blue", "category": "prefs",
             "created_at": "", "updated_at": "", "source": ""},
        ])
        await handler.handle("discord", "ch1", "user1", "/memory search color")
        send_fn.assert_awaited()
        assert "blue" in send_fn.call_args[0][2]

    async def test_memory_clear_requires_admin(self, handler, send_fn, auth):
        handler._memory_store = AsyncMock()
        handler._memory_store.clear = AsyncMock(return_value=5)
        auth.check_permission.return_value = False
        await handler.handle("discord", "ch1", "user1", "/memory clear")
        assert "Admin" in send_fn.call_args[0][2]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_commands.py::TestMemoryCommands -v`
Expected: FAIL — handler doesn't know about memory.

**Step 3: Update CommandHandler to handle /memory**

In `shannon/core/commands.py`:

Add `memory_store` parameter to `__init__()`:
```python
def __init__(
    self,
    context: ContextManager,
    scheduler: Scheduler,
    auth: AuthManager,
    send_fn: SendFn,
    memory_store: "MemoryStore | None" = None,
) -> None:
    ...
    self._memory_store = memory_store
```

Add `/memory` handling in `handle()`, before the `else` clause:
```python
elif command == "/memory":
    await self._handle_memory(platform, channel, user_id, args)
```

Update `/help` to include `/memory`:
```python
"**Commands:** /forget, /context, /summarize, /jobs, /sudo, /memory, /help",
```

Add `_handle_memory()`:
```python
async def _handle_memory(
    self, platform: str, channel: str, user_id: str, args: str
) -> None:
    if not self._memory_store:
        await self._send(platform, channel, "Memory store not configured.")
        return

    if args.startswith("search "):
        query = args[7:].strip()
        results = await self._memory_store.search(query)
        if not results:
            await self._send(platform, channel, f"No memories matching '{query}'.")
        else:
            lines = [f"**{r['key']}**: {r['value']} ({r['category']})" for r in results[:20]]
            await self._send(platform, channel, "\n".join(lines))
    elif args.strip() == "clear":
        if not self._auth.check_permission(platform, user_id, PermissionLevel.ADMIN):
            await self._send(platform, channel, "Admin access required to clear memory.")
            return
        count = await self._memory_store.clear()
        await self._send(platform, channel, f"Cleared {count} memories.")
    else:
        # List all memories
        export = await self._memory_store.export_context()
        if not export:
            await self._send(platform, channel, "No memories stored.")
        else:
            await self._send(platform, channel, f"**Memories:**\n{export}")
```

**Step 4: Update system prompt to include memories**

In `shannon/core/system_prompt.py`, modify `build_system_prompt()` to accept optional memory context:
```python
def build_system_prompt(
    tools: list[BaseTool], memory_context: str = ""
) -> str:
    parts = [_BASE_PROMPT]
    if tools:
        parts.append("\nAvailable tools:")
        for tool in tools:
            parts.append(f"- **{tool.name}**: {tool.description}")
    if memory_context:
        parts.append(f"\nCurrent Memory:\n{memory_context}")
    return "\n".join(parts)
```

**Step 5: Update MessageHandler to pass memory context**

In `shannon/core/pipeline.py`, add `memory_store` to `__init__()`:
```python
def __init__(
    self,
    auth, context, tool_executor, command_handler,
    bus, tools, dry_run=False,
    memory_store=None,
):
    ...
    self._memory_store = memory_store
```

In `handle()`, when building system prompt:
```python
memory_context = ""
if self._memory_store:
    memory_context = await self._memory_store.export_context()
system = build_system_prompt(available_tools, memory_context=memory_context)
```

**Step 6: Wire memory into Shannon main**

In `shannon/main.py`:

Add imports:
```python
from shannon.memory.store import MemoryStore
from shannon.tools.memory_tools import MemorySetTool, MemoryGetTool, MemoryDeleteTool
```

In `Shannon.__init__()`:
```python
self.memory = MemoryStore(db_path=settings.get_data_dir() / "memory.db")
```

Add memory tools to tools list:
```python
self.tools: list[BaseTool] = [
    ShellTool(),
    BrowserTool(settings.browser),
    ClaudeCodeTool(),
    InteractiveTool(settings.interactive),
    MemorySetTool(self.memory),
    MemoryGetTool(self.memory),
    MemoryDeleteTool(self.memory),
]
```

Pass memory to command handler:
```python
command_handler = CommandHandler(
    self.context, self.scheduler, self.auth, self._send,
    memory_store=self.memory,
)
```

Pass memory to pipeline:
```python
self._pipeline = MessageHandler(
    self.auth, self.context, tool_executor, command_handler,
    self.bus, self.tools, dry_run=dry_run,
    memory_store=self.memory,
)
```

In `start()`, add memory start:
```python
await self.memory.start()
```

In `stop()`, add memory stop (before llm close):
```python
await self.memory.stop()
```

**Step 7: Run tests**

Run: `pytest tests/ -v`
Expected: All pass. Fix any test fixture issues in `test_commands.py` (the fixture may need updating since CommandHandler now takes an optional memory_store param — existing tests should still work since it defaults to None).

**Step 8: Commit**

```
feat: wire memory store, tools, and commands into Shannon
```

---

## Task 10: Multi-step task planner models

**Files:**
- Create: `shannon/planner/__init__.py`
- Create: `shannon/planner/models.py`

**Step 1: Write tests for planner models**

Create `tests/test_planner.py`:

```python
"""Tests for multi-step task planner."""

import pytest
from datetime import datetime, timezone
from shannon.planner.models import PlanStep, Plan


class TestPlanModels:
    def test_plan_step_defaults(self):
        step = PlanStep(id=1, description="Do something")
        assert step.status == "pending"
        assert step.tool is None
        assert step.result is None
        assert step.error is None

    def test_plan_creation(self):
        steps = [
            PlanStep(id=1, description="Step 1", tool="shell"),
            PlanStep(id=2, description="Step 2"),
        ]
        plan = Plan(
            id="plan-1",
            goal="Deploy app",
            steps=steps,
            status="planning",
            channel="discord:123",
        )
        assert plan.goal == "Deploy app"
        assert len(plan.steps) == 2
        assert plan.status == "planning"

    def test_plan_step_status_values(self):
        for status in ("pending", "running", "done", "failed", "skipped"):
            step = PlanStep(id=1, description="test", status=status)
            assert step.status == status
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_planner.py::TestPlanModels -v`
Expected: FAIL — module not found.

**Step 3: Implement planner models**

Create `shannon/planner/__init__.py`:
```python
"""Multi-step task planner."""

from shannon.planner.models import Plan, PlanStep

__all__ = ["Plan", "PlanStep"]
```

Create `shannon/planner/models.py`:
```python
"""Planner data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass
class PlanStep:
    id: int
    description: str
    tool: str | None = None
    status: Literal["pending", "running", "done", "failed", "skipped"] = "pending"
    result: str | None = None
    error: str | None = None


@dataclass
class Plan:
    id: str
    goal: str
    steps: list[PlanStep]
    status: Literal["planning", "executing", "completed", "failed"] = "planning"
    channel: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

**Step 4: Run tests**

Run: `pytest tests/test_planner.py -v`
Expected: PASS.

**Step 5: Commit**

```
feat: add planner data models
```

---

## Task 11: Plan engine (creation + execution + persistence)

**Files:**
- Create: `shannon/planner/engine.py`
- Modify: `shannon/planner/__init__.py`

**Step 1: Write tests for plan engine**

Add to `tests/test_planner.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from shannon.planner.engine import PlanEngine
from shannon.planner.models import Plan, PlanStep
from shannon.core.llm import LLMResponse, LLMMessage
from shannon.core.auth import PermissionLevel


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.count_tokens = MagicMock(return_value=10)
    return llm


@pytest.fixture
def mock_tool_map():
    tool = AsyncMock()
    tool.name = "shell"
    tool.required_permission = PermissionLevel.OPERATOR
    from shannon.tools.base import ToolResult
    tool.execute = AsyncMock(return_value=ToolResult(success=True, output="done"))
    return {"shell": tool}


@pytest.fixture
async def engine(tmp_path, mock_llm, mock_tool_map):
    e = PlanEngine(
        llm=mock_llm,
        tool_map=mock_tool_map,
        db_path=tmp_path / "plans.db",
    )
    await e.start()
    yield e
    await e.stop()


class TestPlanCreation:
    async def test_create_plan(self, engine, mock_llm):
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({
                "steps": [
                    {"description": "List files", "tool": "shell"},
                    {"description": "Analyze output", "tool": None},
                ]
            }),
            tool_calls=[],
            stop_reason="end_turn",
            input_tokens=100,
            output_tokens=50,
        ))
        plan = await engine.create_plan("Find large files", channel="discord:123")
        assert plan.goal == "Find large files"
        assert len(plan.steps) == 2
        assert plan.steps[0].tool == "shell"
        assert plan.status == "planning"

    async def test_create_plan_caps_steps(self, engine, mock_llm):
        # LLM returns too many steps — should be capped at 8
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({
                "steps": [{"description": f"Step {i}", "tool": "shell"} for i in range(12)]
            }),
            tool_calls=[], stop_reason="end_turn", input_tokens=100, output_tokens=50,
        ))
        plan = await engine.create_plan("Big task", channel="discord:123")
        assert len(plan.steps) <= 8


class TestPlanExecution:
    async def test_execute_plan(self, engine, mock_llm, mock_tool_map):
        plan = Plan(
            id="test-1",
            goal="Test",
            steps=[
                PlanStep(id=1, description="Run ls", tool="shell"),
                PlanStep(id=2, description="Think about it"),
            ],
            status="executing",
            channel="discord:123",
        )
        # Mock LLM for reasoning steps
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content="Looks good", tool_calls=[], stop_reason="end_turn",
            input_tokens=10, output_tokens=10,
        ))

        send = AsyncMock()
        result = await engine.execute_plan(plan, user_level=PermissionLevel.OPERATOR, send_fn=send)
        assert result.status == "completed"
        assert result.steps[0].status == "done"
        assert result.steps[1].status == "done"

    async def test_execute_plan_tool_failure(self, engine, mock_llm, mock_tool_map):
        from shannon.tools.base import ToolResult
        mock_tool_map["shell"].execute = AsyncMock(
            return_value=ToolResult(success=False, error="command not found")
        )
        # LLM decides to skip remaining steps after failure
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"action": "skip"}),
            tool_calls=[], stop_reason="end_turn", input_tokens=10, output_tokens=10,
        ))

        plan = Plan(
            id="test-2",
            goal="Test",
            steps=[
                PlanStep(id=1, description="Run bad cmd", tool="shell"),
                PlanStep(id=2, description="Next step", tool="shell"),
            ],
            status="executing",
            channel="discord:123",
        )
        send = AsyncMock()
        result = await engine.execute_plan(plan, user_level=PermissionLevel.OPERATOR, send_fn=send)
        assert result.steps[0].status == "failed"

    async def test_tool_invocation_cap(self, engine, mock_llm, mock_tool_map):
        # Plan with 16 tool steps — should cap at 15
        plan = Plan(
            id="test-3",
            goal="Test",
            steps=[PlanStep(id=i, description=f"Step {i}", tool="shell") for i in range(16)],
            status="executing",
            channel="discord:123",
        )
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content="ok", tool_calls=[], stop_reason="end_turn",
            input_tokens=10, output_tokens=10,
        ))
        send = AsyncMock()
        result = await engine.execute_plan(plan, user_level=PermissionLevel.OPERATOR, send_fn=send)
        # Count how many steps were actually executed (done status)
        done_count = sum(1 for s in result.steps if s.status == "done")
        assert done_count <= 15


class TestPlanPersistence:
    async def test_save_and_load_plan(self, engine):
        plan = Plan(
            id="persist-1",
            goal="Persist test",
            steps=[PlanStep(id=1, description="Step 1", tool="shell")],
            status="executing",
            channel="discord:123",
        )
        await engine.save_plan(plan)
        loaded = await engine.load_plan("persist-1")
        assert loaded is not None
        assert loaded.goal == "Persist test"
        assert len(loaded.steps) == 1

    async def test_load_nonexistent(self, engine):
        loaded = await engine.load_plan("nonexistent")
        assert loaded is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_planner.py::TestPlanCreation -v`
Expected: FAIL — PlanEngine not found.

**Step 3: Implement PlanEngine**

Create `shannon/planner/engine.py`:
```python
"""Plan creation, execution, and persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine
from uuid import uuid4

import aiosqlite

from shannon.core.auth import PermissionLevel
from shannon.core.llm import LLMMessage, LLMProvider, LLMResponse
from shannon.planner.models import Plan, PlanStep
from shannon.tools.base import BaseTool
from shannon.utils.logging import get_logger

log = get_logger(__name__)

SendFn = Callable[[str, str, str], Coroutine[Any, Any, None]]

_PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    status TEXT NOT NULL,
    channel TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_CREATE_PLAN_PROMPT = """\
Decompose the following goal into 2-8 concrete steps. Each step should be \
a single action. For steps that use a tool, specify the tool name. \
For reasoning/analysis steps, set tool to null.

Available tools: {tools}

Respond with ONLY a JSON object:
{{"steps": [{{"description": "...", "tool": "tool_name_or_null"}}]}}

Goal: {goal}

Context: {context}
"""

_FAILURE_PROMPT = """\
Step {step_id} failed with error: {error}

Current plan state:
{plan_state}

Should we retry this step, skip it, or abort the plan?
Respond with ONLY a JSON object: {{"action": "retry" | "skip" | "abort"}}
"""

MAX_TOOL_INVOCATIONS = 15
MAX_STEPS = 8


class PlanEngine:
    def __init__(
        self,
        llm: LLMProvider,
        tool_map: dict[str, BaseTool],
        db_path: Path,
    ) -> None:
        self._llm = llm
        self._tool_map = tool_map
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.executescript(_PLAN_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def create_plan(
        self, goal: str, channel: str, context: str = ""
    ) -> Plan:
        tool_names = ", ".join(self._tool_map.keys()) or "none"
        prompt = _CREATE_PLAN_PROMPT.format(
            tools=tool_names, goal=goal, context=context or "No additional context.",
        )

        response = await self._llm.complete(
            messages=[LLMMessage(role="user", content=prompt)],
            max_tokens=1024,
            temperature=0.3,
        )

        steps = self._parse_steps(response.content)
        plan_id = uuid4().hex[:12]
        plan = Plan(
            id=plan_id,
            goal=goal,
            steps=steps,
            status="planning",
            channel=channel,
        )
        await self.save_plan(plan)
        return plan

    def _parse_steps(self, content: str) -> list[PlanStep]:
        try:
            # Try to extract JSON from response
            text = content.strip()
            if "```" in text:
                # Extract from code block
                start = text.index("```") + 3
                if text[start:].startswith("json"):
                    start += 4
                end = text.index("```", start)
                text = text[start:end].strip()
            data = json.loads(text)
            raw_steps = data.get("steps", [])
        except (json.JSONDecodeError, ValueError, KeyError):
            log.warning("plan_parse_failed", content=content[:200])
            return [PlanStep(id=1, description="Execute the goal directly")]

        steps: list[PlanStep] = []
        for i, raw in enumerate(raw_steps[:MAX_STEPS], start=1):
            tool = raw.get("tool")
            if tool == "null" or tool is None:
                tool = None
            steps.append(PlanStep(
                id=i,
                description=raw.get("description", f"Step {i}"),
                tool=tool,
            ))
        return steps or [PlanStep(id=1, description="Execute the goal directly")]

    async def execute_plan(
        self,
        plan: Plan,
        user_level: PermissionLevel,
        send_fn: SendFn | None = None,
    ) -> Plan:
        plan.status = "executing"
        tool_invocations = 0

        for step in plan.steps:
            if tool_invocations >= MAX_TOOL_INVOCATIONS:
                step.status = "skipped"
                step.error = "Tool invocation cap reached"
                continue

            step.status = "running"
            plan.updated_at = datetime.now(timezone.utc)
            await self.save_plan(plan)

            if step.tool:
                tool = self._tool_map.get(step.tool)
                if not tool:
                    step.status = "failed"
                    step.error = f"Unknown tool: {step.tool}"
                    # Ask LLM what to do
                    action = await self._handle_failure(plan, step)
                    if action == "abort":
                        plan.status = "failed"
                        break
                    elif action == "retry":
                        step.status = "failed"  # Can't retry unknown tool
                    continue

                if user_level < tool.required_permission:
                    step.status = "failed"
                    step.error = f"Permission denied for {step.tool}"
                    action = await self._handle_failure(plan, step)
                    if action == "abort":
                        plan.status = "failed"
                        break
                    continue

                result = await tool.execute(command=step.description)
                tool_invocations += 1

                if result.success:
                    step.status = "done"
                    step.result = result.output
                else:
                    step.status = "failed"
                    step.error = result.error
                    action = await self._handle_failure(plan, step)
                    if action == "abort":
                        plan.status = "failed"
                        break
                    elif action == "skip":
                        step.status = "skipped"
            else:
                # LLM reasoning step
                reasoning_prompt = (
                    f"Plan goal: {plan.goal}\n"
                    f"Current step: {step.description}\n"
                    f"Previous results: {self._summarize_results(plan)}"
                )
                response = await self._llm.complete(
                    messages=[LLMMessage(role="user", content=reasoning_prompt)],
                    max_tokens=512,
                    temperature=0.5,
                )
                step.status = "done"
                step.result = response.content

            # Send progress update
            if send_fn and plan.channel:
                parts = plan.channel.split(":", 1)
                if len(parts) == 2:
                    platform, channel = parts
                    done = sum(1 for s in plan.steps if s.status in ("done", "skipped", "failed"))
                    total = len(plan.steps)
                    status_icon = "+" if step.status == "done" else "x" if step.status == "failed" else "~"
                    await send_fn(
                        platform, channel,
                        f"Step {step.id}/{total} {step.status}: {step.description} [{status_icon}]",
                    )

        if plan.status != "failed":
            plan.status = "completed"

        plan.updated_at = datetime.now(timezone.utc)
        await self.save_plan(plan)
        return plan

    async def _handle_failure(self, plan: Plan, step: PlanStep) -> str:
        """Ask LLM whether to retry, skip, or abort after a failure."""
        plan_state = "\n".join(
            f"  {s.id}. [{s.status}] {s.description}" for s in plan.steps
        )
        prompt = _FAILURE_PROMPT.format(
            step_id=step.id, error=step.error, plan_state=plan_state,
        )
        try:
            response = await self._llm.complete(
                messages=[LLMMessage(role="user", content=prompt)],
                max_tokens=64,
                temperature=0.1,
            )
            data = json.loads(response.content.strip())
            return data.get("action", "skip")
        except Exception:
            return "skip"

    def _summarize_results(self, plan: Plan) -> str:
        parts = []
        for step in plan.steps:
            if step.status == "done" and step.result:
                parts.append(f"Step {step.id}: {step.result[:200]}")
        return "\n".join(parts) or "No results yet."

    # --- Persistence ---

    async def save_plan(self, plan: Plan) -> None:
        assert self._db is not None
        steps_json = json.dumps([
            {
                "id": s.id, "description": s.description, "tool": s.tool,
                "status": s.status, "result": s.result, "error": s.error,
            }
            for s in plan.steps
        ])
        await self._db.execute(
            "INSERT INTO plans (id, goal, steps_json, status, channel, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET steps_json=?, status=?, updated_at=?",
            (
                plan.id, plan.goal, steps_json, plan.status, plan.channel,
                plan.created_at.isoformat(), plan.updated_at.isoformat(),
                steps_json, plan.status, plan.updated_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def load_plan(self, plan_id: str) -> Plan | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, goal, steps_json, status, channel, created_at, updated_at "
            "FROM plans WHERE id = ?",
            (plan_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        steps_data = json.loads(row[2])
        steps = [
            PlanStep(
                id=s["id"], description=s["description"], tool=s.get("tool"),
                status=s.get("status", "pending"), result=s.get("result"),
                error=s.get("error"),
            )
            for s in steps_data
        ]
        return Plan(
            id=row[0], goal=row[1], steps=steps, status=row[3],
            channel=row[4],
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
        )
```

Update `shannon/planner/__init__.py`:
```python
"""Multi-step task planner."""

from shannon.planner.models import Plan, PlanStep
from shannon.planner.engine import PlanEngine

__all__ = ["Plan", "PlanStep", "PlanEngine"]
```

**Step 4: Run tests**

Run: `pytest tests/test_planner.py -v`
Expected: All pass.

**Step 5: Commit**

```
feat: add plan engine with creation, execution, and persistence
```

---

## Task 12: Plan tool and wire into Shannon

**Files:**
- Create: `shannon/tools/plan_tool.py`
- Modify: `shannon/main.py`

**Step 1: Write tests for plan tool**

Create `tests/test_plan_tool.py`:

```python
"""Tests for plan meta-tool."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from shannon.tools.plan_tool import PlanTool
from shannon.planner.engine import PlanEngine
from shannon.core.auth import PermissionLevel
from shannon.core.llm import LLMResponse


class TestPlanTool:
    def test_metadata(self):
        engine = MagicMock()
        tool = PlanTool(engine)
        assert tool.name == "plan"
        assert tool.required_permission == PermissionLevel.OPERATOR
        assert "goal" in tool.parameters["properties"]

    async def test_execute_creates_and_runs_plan(self, tmp_path):
        llm = AsyncMock()
        llm.count_tokens = MagicMock(return_value=10)
        llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"steps": [{"description": "Say hello", "tool": None}]}),
            tool_calls=[], stop_reason="end_turn", input_tokens=10, output_tokens=10,
        ))
        engine = PlanEngine(llm=llm, tool_map={}, db_path=tmp_path / "plans.db")
        await engine.start()

        tool = PlanTool(engine)
        result = await tool.execute(goal="Test goal")
        assert result.success is True
        assert "completed" in result.output.lower() or "Test goal" in result.output

        await engine.stop()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_plan_tool.py -v`
Expected: FAIL — PlanTool not found.

**Step 3: Implement PlanTool**

Create `shannon/tools/plan_tool.py`:
```python
"""Plan meta-tool: create and execute multi-step plans."""

from __future__ import annotations

from typing import Any

from shannon.core.auth import PermissionLevel
from shannon.planner.engine import PlanEngine
from shannon.tools.base import BaseTool, ToolResult


class PlanTool(BaseTool):
    def __init__(self, engine: PlanEngine) -> None:
        self._engine = engine

    @property
    def name(self) -> str:
        return "plan"

    @property
    def description(self) -> str:
        return (
            "Create and execute a multi-step plan for a complex goal. "
            "Decomposes into steps, executes sequentially, reports progress."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The goal to accomplish.",
                },
            },
            "required": ["goal"],
        }

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.OPERATOR

    async def execute(self, **kwargs: Any) -> ToolResult:
        goal = kwargs["goal"]

        try:
            plan = await self._engine.create_plan(goal, channel="")
            plan = await self._engine.execute_plan(
                plan, user_level=PermissionLevel.OPERATOR,
            )

            # Build summary
            lines = [f"Plan: {plan.goal} [{plan.status}]"]
            for step in plan.steps:
                icon = {"done": "+", "failed": "x", "skipped": "~"}.get(step.status, "?")
                lines.append(f"  [{icon}] {step.description}")
                if step.result:
                    lines.append(f"      Result: {step.result[:200]}")
                if step.error:
                    lines.append(f"      Error: {step.error[:200]}")

            return ToolResult(
                success=plan.status == "completed",
                output="\n".join(lines),
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
```

**Step 4: Wire into Shannon main**

In `shannon/main.py`, add imports:
```python
from shannon.planner.engine import PlanEngine
from shannon.tools.plan_tool import PlanTool
```

In `Shannon.__init__()`:
```python
self.planner = PlanEngine(
    llm=self.llm, tool_map=tool_map,
    db_path=settings.get_data_dir() / "plans.db",
)
```

Add PlanTool to tools list (after creating tool_map, but PlanTool doesn't need to be in tool_map itself — it uses the engine which has tool_map):
```python
self.tools.append(PlanTool(self.planner))
# Rebuild tool_map to include new tools
tool_map = {t.name: t for t in self.tools}
```

Wait — this is circular. The `PlanEngine` needs `tool_map`, but `PlanTool` is added to `self.tools` after `tool_map` is built. The fix: build initial tool_map without PlanTool, create PlanEngine with that, then add PlanTool to tools list. The PlanTool doesn't need to be in the PlanEngine's tool_map (it shouldn't recursively plan).

In `start()`:
```python
await self.planner.start()
```

In `stop()`:
```python
await self.planner.stop()
```

**Step 5: Run tests**

Run: `pytest tests/ -v`
Expected: All pass.

**Step 6: Commit**

```
feat: add plan tool and wire planner into Shannon
```

---

## Task 13: Pause/resume — duration parsing and state

**Files:**
- Create: `shannon/core/pause.py`

**Step 1: Write tests for pause manager**

Create `tests/test_pause.py`:

```python
"""Tests for pause/resume functionality."""

import asyncio
import pytest
from shannon.core.pause import PauseManager, parse_duration


class TestDurationParsing:
    def test_hours(self):
        assert parse_duration("2h") == 7200

    def test_minutes(self):
        assert parse_duration("30m") == 1800

    def test_seconds(self):
        assert parse_duration("45s") == 45

    def test_combined(self):
        assert parse_duration("1h30m") == 5400

    def test_full_combo(self):
        assert parse_duration("1h30m15s") == 5415

    def test_invalid(self):
        assert parse_duration("abc") is None

    def test_empty(self):
        assert parse_duration("") is None

    def test_zero(self):
        assert parse_duration("0m") == 0


class TestPauseManager:
    def test_initial_state(self):
        pm = PauseManager()
        assert pm.is_paused is False

    def test_pause_resume(self):
        pm = PauseManager()
        pm.pause()
        assert pm.is_paused is True
        pm.resume()
        assert pm.is_paused is False

    async def test_auto_resume(self):
        pm = PauseManager()
        pm.pause(duration_seconds=0.1)
        assert pm.is_paused is True
        await asyncio.sleep(0.2)
        # Auto-resume task should have fired
        assert pm.is_paused is False

    def test_queue_event(self):
        pm = PauseManager()
        pm.pause()
        pm.queue_event({"type": "webhook", "data": "test"})
        assert len(pm.queued_events) == 1

    def test_drain_queue(self):
        pm = PauseManager()
        pm.pause()
        pm.queue_event({"type": "webhook", "data": "1"})
        pm.queue_event({"type": "webhook", "data": "2"})
        events = pm.drain_queue()
        assert len(events) == 2
        assert len(pm.queued_events) == 0

    async def test_resume_reports_queued_count(self):
        pm = PauseManager()
        pm.pause()
        pm.queue_event({"data": "1"})
        pm.queue_event({"data": "2"})
        count = pm.resume()
        assert count == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pause.py -v`
Expected: FAIL — module not found.

**Step 3: Implement PauseManager**

Create `shannon/core/pause.py`:
```python
"""Pause/resume manager for autonomous behaviors."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from shannon.utils.logging import get_logger

log = get_logger(__name__)

_DURATION_RE = re.compile(
    r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", re.IGNORECASE
)


def parse_duration(text: str) -> int | None:
    """Parse duration string like '2h', '30m', '1h30m'. Returns seconds or None."""
    if not text:
        return None
    m = _DURATION_RE.match(text.strip())
    if not m or not any(m.groups()):
        return None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


class PauseManager:
    def __init__(self) -> None:
        self._paused = False
        self._queued_events: list[dict[str, Any]] = []
        self._resume_task: asyncio.Task[None] | None = None

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def queued_events(self) -> list[dict[str, Any]]:
        return self._queued_events

    def pause(self, duration_seconds: float | None = None) -> None:
        self._paused = True
        log.info("shannon_paused", duration=duration_seconds)

        if duration_seconds is not None and duration_seconds > 0:
            self._resume_task = asyncio.get_event_loop().create_task(
                self._auto_resume(duration_seconds)
            )

    def resume(self) -> int:
        """Resume and return count of queued events."""
        if self._resume_task and not self._resume_task.done():
            self._resume_task.cancel()
            self._resume_task = None

        self._paused = False
        count = len(self._queued_events)
        log.info("shannon_resumed", queued_events=count)
        return count

    def drain_queue(self) -> list[dict[str, Any]]:
        events = list(self._queued_events)
        self._queued_events.clear()
        return events

    def queue_event(self, event: dict[str, Any]) -> None:
        self._queued_events.append(event)

    async def _auto_resume(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        self.resume()
        log.info("shannon_auto_resumed")
```

**Step 4: Run tests**

Run: `pytest tests/test_pause.py -v`
Expected: All pass.

**Step 5: Commit**

```
feat: add pause/resume manager with duration parsing
```

---

## Task 14: Wire pause/resume into Shannon (commands, scheduler, webhooks)

**Files:**
- Modify: `shannon/core/commands.py`
- Modify: `shannon/core/scheduler.py`
- Modify: `shannon/main.py`

**Step 1: Write tests for pause commands**

Add to `tests/test_commands.py`:

```python
from shannon.core.pause import PauseManager


class TestPauseCommands:
    async def test_pause_command(self, handler, send_fn, auth):
        handler._pause_manager = PauseManager()
        auth.check_permission.return_value = True
        await handler.handle("discord", "ch1", "op1", "/pause")
        send_fn.assert_awaited()
        assert handler._pause_manager.is_paused is True

    async def test_pause_with_duration(self, handler, send_fn, auth):
        handler._pause_manager = PauseManager()
        auth.check_permission.return_value = True
        await handler.handle("discord", "ch1", "op1", "/pause 2h")
        assert handler._pause_manager.is_paused is True
        assert "2h" in send_fn.call_args[0][2] or "Paused" in send_fn.call_args[0][2]

    async def test_pause_requires_operator(self, handler, send_fn, auth):
        handler._pause_manager = PauseManager()
        auth.check_permission.return_value = False
        await handler.handle("discord", "ch1", "user1", "/pause")
        assert handler._pause_manager.is_paused is False

    async def test_resume_command(self, handler, send_fn, auth):
        handler._pause_manager = PauseManager()
        handler._pause_manager.pause()
        auth.check_permission.return_value = True
        await handler.handle("discord", "ch1", "op1", "/resume")
        assert handler._pause_manager.is_paused is False

    async def test_status_command(self, handler, send_fn, auth):
        handler._pause_manager = PauseManager()
        await handler.handle("discord", "ch1", "user1", "/status")
        send_fn.assert_awaited()
        assert "active" in send_fn.call_args[0][2].lower() or "Active" in send_fn.call_args[0][2]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_commands.py::TestPauseCommands -v`
Expected: FAIL — pause commands not implemented.

**Step 3: Add pause commands to CommandHandler**

In `shannon/core/commands.py`:

Add import:
```python
from shannon.core.pause import PauseManager, parse_duration
```

Add `pause_manager` to `__init__()`:
```python
def __init__(
    self,
    context, scheduler, auth, send_fn,
    memory_store=None,
    pause_manager: PauseManager | None = None,
):
    ...
    self._pause_manager = pause_manager
```

Add command handlers in `handle()`:
```python
elif command == "/pause":
    await self._handle_pause(platform, channel, user_id, args)
elif command == "/resume":
    await self._handle_resume(platform, channel, user_id)
elif command == "/status":
    await self._handle_status(platform, channel)
```

Update `/help`:
```python
"**Commands:** /forget, /context, /summarize, /jobs, /sudo, /memory, /pause, /resume, /status, /help",
```

Add handler methods:
```python
async def _handle_pause(
    self, platform: str, channel: str, user_id: str, args: str
) -> None:
    if not self._auth.check_permission(platform, user_id, PermissionLevel.OPERATOR):
        await self._send(platform, channel, "Operator access required.")
        return
    if not self._pause_manager:
        await self._send(platform, channel, "Pause manager not configured.")
        return

    duration = parse_duration(args.strip()) if args.strip() else None
    self._pause_manager.pause(duration_seconds=duration)

    if duration:
        await self._send(
            platform, channel,
            f"Paused for {args.strip()}. I'll still respond if you message me directly.",
        )
    else:
        await self._send(
            platform, channel,
            "Paused indefinitely. Use /resume to resume. I'll still respond to direct messages.",
        )

async def _handle_resume(
    self, platform: str, channel: str, user_id: str
) -> None:
    if not self._auth.check_permission(platform, user_id, PermissionLevel.OPERATOR):
        await self._send(platform, channel, "Operator access required.")
        return
    if not self._pause_manager:
        await self._send(platform, channel, "Pause manager not configured.")
        return

    count = self._pause_manager.resume()
    events = self._pause_manager.drain_queue()
    if count:
        await self._send(platform, channel, f"Resumed. {count} queued event(s) were missed.")
    else:
        await self._send(platform, channel, "Resumed.")

async def _handle_status(self, platform: str, channel: str) -> None:
    if self._pause_manager and self._pause_manager.is_paused:
        queued = len(self._pause_manager.queued_events)
        await self._send(
            platform, channel,
            f"Status: **Paused** | {queued} queued event(s)",
        )
    else:
        await self._send(platform, channel, "Status: **Active**")
```

**Step 4: Integrate pause into Scheduler**

In `shannon/core/scheduler.py`, add `pause_manager` support.

Add to `__init__()`:
```python
def __init__(
    self, config, bus, data_dir,
    pause_manager=None,
):
    ...
    self._pause_manager = pause_manager
```

In `_heartbeat_loop()`, check pause:
```python
async def _heartbeat_loop(self) -> None:
    while self._running:
        if self._pause_manager and self._pause_manager.is_paused:
            await asyncio.sleep(self._config.heartbeat_interval)
            continue
        try:
            self._heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            self._heartbeat_path.write_text(str(time.time()))
        except OSError:
            log.exception("heartbeat_write_failed")
        await asyncio.sleep(self._config.heartbeat_interval)
```

In `_check_and_fire_jobs()`, check pause:
```python
async def _check_and_fire_jobs(self) -> None:
    if self._pause_manager and self._pause_manager.is_paused:
        log.info("cron_skipped_paused")
        return
    # ... rest unchanged
```

**Step 5: Wire PauseManager into Shannon main**

In `shannon/main.py`, add:
```python
from shannon.core.pause import PauseManager
```

In `Shannon.__init__()`:
```python
self.pause_manager = PauseManager()
```

Pass to scheduler:
```python
self.scheduler = Scheduler(
    settings.scheduler, self.bus, settings.get_data_dir(),
    pause_manager=self.pause_manager,
)
```

Pass to command handler:
```python
command_handler = CommandHandler(
    self.context, self.scheduler, self.auth, self._send,
    memory_store=self.memory,
    pause_manager=self.pause_manager,
)
```

**Step 6: Run tests**

Run: `pytest tests/ -v`
Expected: All pass. Some existing test fixtures may need updating since Scheduler/CommandHandler now take optional new params — existing tests should still work since defaults are None.

**Step 7: Commit**

```
feat: add pause/resume/status commands and integrate with scheduler
```

---

## Task 15: Integration testing and final test suite run

**Files:**
- All test files

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All pass.

**Step 2: Fix any failures**

Address any import issues, fixture mismatches, or integration problems found.

**Step 3: Final commit**

```
test: fix integration issues across all four features
```

---

## Summary of files created/modified

### New files:
- `shannon/webhooks/__init__.py`
- `shannon/webhooks/models.py`
- `shannon/webhooks/handlers.py`
- `shannon/webhooks/server.py`
- `shannon/memory/__init__.py`
- `shannon/memory/store.py`
- `shannon/tools/memory_tools.py`
- `shannon/planner/__init__.py`
- `shannon/planner/models.py`
- `shannon/planner/engine.py`
- `shannon/tools/plan_tool.py`
- `shannon/core/pause.py`
- `tests/test_webhook_event.py`
- `tests/test_webhooks.py`
- `tests/test_memory.py`
- `tests/test_memory_tools.py`
- `tests/test_planner.py`
- `tests/test_plan_tool.py`
- `tests/test_pause.py`

### Modified files:
- `pyproject.toml` — add aiohttp dep
- `shannon/core/bus.py` — add WEBHOOK_RECEIVED event type
- `shannon/config.py` — add WebhooksConfig
- `shannon/core/commands.py` — add /memory, /pause, /resume, /status
- `shannon/core/system_prompt.py` — add memory_context param
- `shannon/core/pipeline.py` — pass memory context to system prompt
- `shannon/core/scheduler.py` — pause-awareness
- `shannon/main.py` — wire all new components
- `shannon/tools/__init__.py` — export new tools
- `tests/test_commands.py` — add memory/pause command tests
