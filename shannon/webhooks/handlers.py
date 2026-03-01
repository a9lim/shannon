"""Webhook signature validation and event normalization."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from shannon.webhooks.models import WebhookEvent


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------

def validate_github_signature(body: bytes, signature: str, secret: str) -> bool:
    """Validate GitHub webhook HMAC-SHA256 signature.

    Returns False if no secret is configured (rejects unauthenticated requests).
    """
    if not secret:
        return False
    if not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def validate_sentry_signature(body: bytes, signature: str, secret: str) -> bool:
    """Validate Sentry webhook HMAC-SHA256 signature.

    Returns False if no secret is configured (rejects unauthenticated requests).
    """
    if not secret:
        return False
    if not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def validate_generic_secret(provided: str, configured: str) -> bool:
    """Validate a generic shared secret via constant-time comparison.

    Returns False if no secret is configured (rejects unauthenticated requests).
    """
    if not configured:
        return False
    if not provided:
        return False
    return hmac.compare_digest(provided, configured)


# ---------------------------------------------------------------------------
# Event normalization
# ---------------------------------------------------------------------------

def normalize_github_event(
    event_type: str, payload: dict[str, Any], channel: str
) -> WebhookEvent:
    """Normalize a GitHub webhook payload into a WebhookEvent."""
    repo = payload.get("repository", {}).get("full_name", "unknown")

    if event_type == "push":
        commits = payload.get("commits", [])
        count = len(commits)
        branch = payload.get("ref", "").removeprefix("refs/heads/")
        pusher = payload.get("pusher", {}).get("name", "unknown")
        summary = f"{pusher} pushed {count} commit(s) to {repo}/{branch}"

    elif event_type == "pull_request":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        number = pr.get("number", "?")
        title = pr.get("title", "")
        user = pr.get("user", {}).get("login", "unknown")
        summary = f"{user} {action} PR #{number} on {repo}: {title}"

    elif event_type == "issues":
        action = payload.get("action", "")
        issue = payload.get("issue", {})
        number = issue.get("number", "?")
        title = issue.get("title", "")
        user = issue.get("user", {}).get("login", "unknown")
        summary = f"{user} {action} issue #{number} on {repo}: {title}"

    elif event_type == "workflow_run":
        action = payload.get("action", "")
        run = payload.get("workflow_run", {})
        name = run.get("name", "")
        conclusion = run.get("conclusion", "")
        summary = f"Workflow '{name}' {action} on {repo} — {conclusion}"

    else:
        summary = f"GitHub {event_type} event on {repo}"

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
    """Normalize a Sentry webhook payload into a WebhookEvent."""
    data = payload.get("data", {})
    event = data.get("event", data)
    title = event.get("title", payload.get("message", "Sentry alert"))
    project = payload.get("project_name", payload.get("project", "unknown"))
    level = event.get("level", "error")
    summary = f"[{level}] {project}: {title}"

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
    """Normalize a generic webhook payload into a WebhookEvent."""
    summary = payload.get("summary", payload.get("message", "Webhook received"))

    return WebhookEvent(
        source="generic",
        event_type=payload.get("event_type", "generic"),
        summary=str(summary),
        payload=payload,
        channel_target=channel,
    )
