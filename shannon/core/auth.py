"""Permission and authorization system with rate limiting and sudo escalation."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from enum import IntEnum

from shannon.config import AuthConfig
from shannon.utils.logging import get_logger

log = get_logger(__name__)


class PermissionLevel(IntEnum):
    PUBLIC = 0
    TRUSTED = 1
    OPERATOR = 2
    ADMIN = 3


class AuthManager:
    def __init__(self, config: AuthConfig) -> None:
        self._config = config
        # Map (platform, user_id) -> PermissionLevel
        self._user_map: dict[tuple[str, str], PermissionLevel] = {}
        self._build_user_map()

        # Rate limiting: (platform, user_id) -> list of timestamps
        self._rate_log: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._rate_limit = config.rate_limit_per_minute

        # Sudo escalations: (platform, user_id) -> (elevated_level, expiry_time)
        self._sudo_grants: dict[tuple[str, str], tuple[PermissionLevel, float]] = {}
        self._sudo_timeout = config.sudo_timeout_seconds

        # Pending sudo requests: request_id -> (platform, user_id, requested_level, action)
        self._pending_sudo: dict[str, tuple[str, str, PermissionLevel, str]] = {}
        self._sudo_counter = 0

    def _build_user_map(self) -> None:
        for uid in self._config.admin_users:
            self._parse_and_store(uid, PermissionLevel.ADMIN)
        for uid in self._config.operator_users:
            self._parse_and_store(uid, PermissionLevel.OPERATOR)
        for uid in self._config.trusted_users:
            self._parse_and_store(uid, PermissionLevel.TRUSTED)

    def _parse_and_store(self, uid: str, level: PermissionLevel) -> None:
        """Parse 'platform:user_id' or bare 'user_id' (applies to all platforms)."""
        if ":" in uid:
            platform, user_id = uid.split(":", 1)
            self._user_map[(platform, user_id)] = level
        else:
            for platform in ("discord", "signal"):
                self._user_map[(platform, uid)] = level

    def get_level(self, platform: str, user_id: str) -> PermissionLevel:
        key = (platform, user_id)

        # Check for active sudo grant
        if key in self._sudo_grants:
            level, expiry = self._sudo_grants[key]
            if time.time() < expiry:
                return level
            else:
                del self._sudo_grants[key]
                log.info("sudo_expired", platform=platform, user_id=user_id)

        level = self._user_map.get(key)
        if level is not None:
            return level
        return PermissionLevel(self._config.default_level)

    def check_permission(
        self, platform: str, user_id: str, required: PermissionLevel
    ) -> bool:
        return self.get_level(platform, user_id) >= required

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def check_rate_limit(self, platform: str, user_id: str) -> bool:
        """Check if user is within rate limit. Returns True if allowed."""
        key = (platform, user_id)
        now = time.time()
        window_start = now - 60.0

        # Prune old entries
        self._rate_log[key] = [t for t in self._rate_log[key] if t > window_start]

        if len(self._rate_log[key]) >= self._rate_limit:
            log.warning("rate_limit_exceeded", platform=platform, user_id=user_id)
            return False

        self._rate_log[key].append(now)
        return True

    # ------------------------------------------------------------------
    # Sudo escalation
    # ------------------------------------------------------------------

    async def request_sudo(
        self, platform: str, user_id: str, action: str,
        requested_level: PermissionLevel = PermissionLevel.OPERATOR,
    ) -> str:
        """Request temporary permission elevation. Returns a request_id for admin approval."""
        self._sudo_counter += 1
        request_id = f"sudo-{self._sudo_counter}"
        self._pending_sudo[request_id] = (platform, user_id, requested_level, action)

        log.info(
            "sudo_requested",
            request_id=request_id,
            platform=platform,
            user_id=user_id,
            requested_level=requested_level.name,
            action=action,
        )
        return request_id

    def approve_sudo(self, request_id: str, admin_platform: str, admin_id: str) -> bool:
        """Admin approves a sudo request. Returns True if approved."""
        # Verify the approver is admin
        if not self.check_permission(admin_platform, admin_id, PermissionLevel.ADMIN):
            log.warning("sudo_approve_denied", admin_id=admin_id, reason="not_admin")
            return False

        request = self._pending_sudo.pop(request_id, None)
        if request is None:
            return False

        platform, user_id, requested_level, action = request
        expiry = time.time() + self._sudo_timeout
        self._sudo_grants[(platform, user_id)] = (requested_level, expiry)

        log.info(
            "sudo_approved",
            request_id=request_id,
            platform=platform,
            user_id=user_id,
            level=requested_level.name,
            expires_in=self._sudo_timeout,
        )
        return True

    def deny_sudo(self, request_id: str) -> bool:
        """Admin denies a sudo request."""
        request = self._pending_sudo.pop(request_id, None)
        if request is None:
            return False
        log.info("sudo_denied", request_id=request_id)
        return True

    def list_pending_sudo(self) -> list[dict[str, str]]:
        """List all pending sudo requests."""
        return [
            {
                "request_id": rid,
                "platform": data[0],
                "user_id": data[1],
                "requested_level": data[2].name,
                "action": data[3],
            }
            for rid, data in self._pending_sudo.items()
        ]

    def revoke_sudo(self, platform: str, user_id: str) -> bool:
        """Revoke an active sudo grant."""
        key = (platform, user_id)
        if key in self._sudo_grants:
            del self._sudo_grants[key]
            log.info("sudo_revoked", platform=platform, user_id=user_id)
            return True
        return False
