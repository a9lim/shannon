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
        await asyncio.sleep(0.3)
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
