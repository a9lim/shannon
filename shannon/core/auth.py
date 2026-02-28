"""Permission and authorization system."""

from __future__ import annotations

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
            # Bare ID — register for common platforms
            for platform in ("discord", "signal"):
                self._user_map[(platform, uid)] = level

    def get_level(self, platform: str, user_id: str) -> PermissionLevel:
        level = self._user_map.get((platform, user_id))
        if level is not None:
            return level
        return PermissionLevel(self._config.default_level)

    def check_permission(
        self, platform: str, user_id: str, required: PermissionLevel
    ) -> bool:
        return self.get_level(platform, user_id) >= required

    async def request_sudo(
        self, platform: str, user_id: str, action: str
    ) -> bool:
        """Stub for sudo escalation flow — full implementation later."""
        log.info(
            "sudo_requested",
            platform=platform,
            user_id=user_id,
            action=action,
        )
        return False
