"""Webhook HTTP server using aiohttp."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from shannon.config import WebhookEndpointConfig, WebhooksConfig
from shannon.core.bus import EventBus, EventType, WebhookReceived
from shannon.utils.logging import get_logger
from shannon.webhooks.handlers import (
    normalize_generic_event,
    normalize_github_event,
    normalize_sentry_event,
    validate_generic_secret,
    validate_github_signature,
    validate_sentry_signature,
)
from shannon.webhooks.models import WebhookEvent

log = get_logger(__name__)


class WebhookServer:
    """Receives incoming webhooks and publishes events to the bus."""

    def __init__(self, config: WebhooksConfig, bus: EventBus) -> None:
        self._config = config
        self._bus = bus
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        for endpoint in self._config.endpoints:
            if not endpoint.secret:
                log.warning(
                    "webhook_endpoint_no_secret",
                    endpoint=endpoint.name or endpoint.path,
                    msg="Endpoint has no secret configured — all requests will be rejected. Set a secret in config.",
                )
        app = self._build_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._config.bind, self._config.port)
        await site.start()
        log.info(
            "webhook_server_started",
            bind=self._config.bind,
            port=self._config.port,
        )

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        log.info("webhook_server_stopped")

    # ------------------------------------------------------------------
    # App construction
    # ------------------------------------------------------------------

    def _build_app(self) -> web.Application:
        app = web.Application()
        for endpoint in self._config.endpoints:
            path = endpoint.path if endpoint.path.startswith("/") else f"/{endpoint.path}"
            app.router.add_post(path, self._handle_webhook)
        return app

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        # Find matching endpoint config
        endpoint = self._find_endpoint(request.path)
        if endpoint is None:
            return web.Response(status=404, text="Not found")

        # Read body
        body = await request.read()

        # Parse JSON
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            return web.Response(status=400, text="Invalid JSON")

        # Validate signature
        if not self._validate(endpoint, request, body):
            return web.Response(status=401, text="Invalid signature")

        # Normalize event
        event = self._normalize(endpoint, request, payload)

        # Publish to bus
        await self._bus.publish(
            WebhookReceived(
                data={
                    "source": event.source,
                    "event_type": event.event_type,
                    "summary": event.summary,
                    "payload": event.payload,
                    "channel_target": event.channel_target,
                }
            )
        )

        log.info(
            "webhook_received",
            source=event.source,
            event_type=event.event_type,
            channel=event.channel_target,
        )

        return web.Response(status=200, text="OK")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_endpoint(self, path: str) -> WebhookEndpointConfig | None:
        for endpoint in self._config.endpoints:
            ep_path = endpoint.path if endpoint.path.startswith("/") else f"/{endpoint.path}"
            if ep_path == path:
                return endpoint
        return None

    def _validate(
        self, endpoint: WebhookEndpointConfig, request: web.Request, body: bytes
    ) -> bool:
        name = endpoint.name.lower()

        if "github" in name:
            signature = request.headers.get("X-Hub-Signature-256", "")
            return validate_github_signature(body, signature, endpoint.secret)

        if "sentry" in name:
            signature = request.headers.get("Sentry-Hook-Signature", "")
            return validate_sentry_signature(body, signature, endpoint.secret)

        # Generic: check Authorization or X-Webhook-Secret header
        provided = request.headers.get(
            "X-Webhook-Secret",
            request.headers.get("Authorization", ""),
        )
        return validate_generic_secret(provided, endpoint.secret)

    def _normalize(
        self,
        endpoint: WebhookEndpointConfig,
        request: web.Request,
        payload: dict[str, Any],
    ) -> WebhookEvent:
        name = endpoint.name.lower()
        channel = endpoint.channel

        if "github" in name:
            event_type = request.headers.get("X-GitHub-Event", "unknown")
            return normalize_github_event(event_type, payload, channel)

        if "sentry" in name:
            return normalize_sentry_event(payload, channel)

        return normalize_generic_event(payload, channel)
