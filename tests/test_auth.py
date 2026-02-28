"""Tests for the authorization system."""

import time
import pytest
from shannon.config import AuthConfig
from shannon.core.auth import AuthManager, PermissionLevel


@pytest.fixture
def config():
    return AuthConfig(
        admin_users=["discord:admin123"],
        operator_users=["discord:op456", "op_bare"],
        trusted_users=["signal:trusted789"],
        default_level=0,
        rate_limit_per_minute=5,
        sudo_timeout_seconds=10,
    )


@pytest.fixture
def auth(config):
    return AuthManager(config)


class TestPermissions:
    def test_admin_permission(self, auth):
        assert auth.get_level("discord", "admin123") == PermissionLevel.ADMIN

    def test_operator_permission(self, auth):
        assert auth.get_level("discord", "op456") == PermissionLevel.OPERATOR

    def test_bare_id_applies_to_all_platforms(self, auth):
        assert auth.get_level("discord", "op_bare") == PermissionLevel.OPERATOR
        assert auth.get_level("signal", "op_bare") == PermissionLevel.OPERATOR

    def test_platform_scoped_user(self, auth):
        assert auth.get_level("signal", "trusted789") == PermissionLevel.TRUSTED
        # Not registered on discord
        assert auth.get_level("discord", "trusted789") == PermissionLevel.PUBLIC

    def test_unknown_user_gets_default(self, auth):
        assert auth.get_level("discord", "unknown") == PermissionLevel.PUBLIC

    def test_check_permission(self, auth):
        assert auth.check_permission("discord", "admin123", PermissionLevel.ADMIN)
        assert auth.check_permission("discord", "admin123", PermissionLevel.OPERATOR)
        assert not auth.check_permission("discord", "unknown", PermissionLevel.TRUSTED)

    def test_higher_level_implies_lower(self, auth):
        # Admin can do everything
        for level in PermissionLevel:
            assert auth.check_permission("discord", "admin123", level)


class TestRateLimiting:
    def test_under_limit_allowed(self, auth):
        for _ in range(5):
            assert auth.check_rate_limit("discord", "user1")

    def test_over_limit_blocked(self, auth):
        for _ in range(5):
            auth.check_rate_limit("discord", "user1")
        assert not auth.check_rate_limit("discord", "user1")

    def test_different_users_independent(self, auth):
        for _ in range(5):
            auth.check_rate_limit("discord", "user1")
        # user2 should still be allowed
        assert auth.check_rate_limit("discord", "user2")


class TestSudo:
    async def test_request_sudo(self, auth):
        request_id = await auth.request_sudo("discord", "user1", "run dangerous command")
        assert request_id.startswith("sudo-")

    async def test_approve_sudo(self, auth):
        request_id = await auth.request_sudo(
            "discord", "user1", "test",
            requested_level=PermissionLevel.OPERATOR,
        )
        # Non-admin cannot approve
        assert not auth.approve_sudo(request_id, "discord", "user1")

        # Admin can approve
        assert auth.approve_sudo(request_id, "discord", "admin123")

        # User now has operator level
        assert auth.get_level("discord", "user1") == PermissionLevel.OPERATOR

    async def test_deny_sudo(self, auth):
        request_id = await auth.request_sudo("discord", "user1", "test")
        assert auth.deny_sudo(request_id)
        # User still public
        assert auth.get_level("discord", "user1") == PermissionLevel.PUBLIC

    async def test_sudo_expiry(self, auth):
        # Use very short timeout
        auth._sudo_timeout = 0.1

        request_id = await auth.request_sudo(
            "discord", "user1", "test",
            requested_level=PermissionLevel.OPERATOR,
        )
        auth.approve_sudo(request_id, "discord", "admin123")
        assert auth.get_level("discord", "user1") == PermissionLevel.OPERATOR

        # Wait for expiry
        time.sleep(0.2)
        assert auth.get_level("discord", "user1") == PermissionLevel.PUBLIC

    def test_list_pending_sudo(self, auth):
        assert auth.list_pending_sudo() == []

    async def test_revoke_sudo(self, auth):
        request_id = await auth.request_sudo(
            "discord", "user1", "test",
            requested_level=PermissionLevel.OPERATOR,
        )
        auth.approve_sudo(request_id, "discord", "admin123")
        assert auth.get_level("discord", "user1") == PermissionLevel.OPERATOR

        auth.revoke_sudo("discord", "user1")
        assert auth.get_level("discord", "user1") == PermissionLevel.PUBLIC
