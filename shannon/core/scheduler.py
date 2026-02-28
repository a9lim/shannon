"""Heartbeat and cron-based task scheduler."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from croniter import croniter

from shannon.config import SchedulerConfig
from shannon.core.bus import EventBus, SchedulerTrigger
from shannon.utils.logging import get_logger

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    cron_expr TEXT NOT NULL,
    action TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run TEXT,
    created_at TEXT NOT NULL
);
"""


@dataclass
class Job:
    id: int
    name: str
    cron_expr: str
    action: str
    enabled: bool
    last_run: datetime | None
    created_at: datetime


class Scheduler:
    def __init__(
        self,
        config: SchedulerConfig,
        bus: EventBus,
        data_dir: Path,
    ) -> None:
        self._config = config
        self._bus = bus
        self._data_dir = data_dir
        self._db: aiosqlite.Connection | None = None
        self._heartbeat_path = (
            Path(config.heartbeat_file) if config.heartbeat_file
            else data_dir / "heartbeat"
        )
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._data_dir / "scheduler.db"))
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

        # Check for stale heartbeat
        await self._check_stale_heartbeat()

        self._running = True
        self._tasks.append(asyncio.create_task(self._heartbeat_loop(), name="heartbeat"))
        self._tasks.append(asyncio.create_task(self._cron_loop(), name="cron"))
        log.info("scheduler_started")

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._db:
            await self._db.close()
            self._db = None

    async def _check_stale_heartbeat(self) -> None:
        if not self._heartbeat_path.exists():
            return
        try:
            last_beat = float(self._heartbeat_path.read_text().strip())
            age = time.time() - last_beat
            if age > self._config.heartbeat_interval * 3:
                log.warning("stale_heartbeat_detected", age_seconds=age)
        except (ValueError, OSError):
            pass

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                self._heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
                self._heartbeat_path.write_text(str(time.time()))
            except OSError:
                log.exception("heartbeat_write_failed")
            await asyncio.sleep(self._config.heartbeat_interval)

    async def _cron_loop(self) -> None:
        while self._running:
            try:
                await self._check_and_fire_jobs()
            except Exception:
                log.exception("cron_loop_error")
            await asyncio.sleep(30)

    async def _check_and_fire_jobs(self) -> None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, name, cron_expr, action, last_run FROM jobs WHERE enabled = 1"
        )
        rows = await cursor.fetchall()
        now = datetime.now(timezone.utc)

        for row in rows:
            job_id, name, cron_expr, action, last_run_str = row
            last_run = (
                datetime.fromisoformat(last_run_str) if last_run_str else None
            )

            cron = croniter(cron_expr, last_run or now)
            next_time = cron.get_next(datetime)

            if next_time <= now:
                log.info("cron_job_firing", job=name)
                await self._bus.publish(
                    SchedulerTrigger(data={
                        "job_id": job_id,
                        "job_name": name,
                        "cron_expr": cron_expr,
                        "action": action,
                    })
                )
                await self._db.execute(
                    "UPDATE jobs SET last_run = ? WHERE id = ?",
                    (now.isoformat(), job_id),
                )
                await self._db.commit()

    async def add_job(self, name: str, cron_expr: str, action: str) -> Job:
        assert self._db is not None
        # Validate cron expression
        if not croniter.is_valid(cron_expr):
            raise ValueError(f"Invalid cron expression: {cron_expr}")

        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "INSERT INTO jobs (name, cron_expr, action, created_at) VALUES (?, ?, ?, ?)",
            (name, cron_expr, action, now),
        )
        await self._db.commit()
        return Job(
            id=cursor.lastrowid or 0,
            name=name,
            cron_expr=cron_expr,
            action=action,
            enabled=True,
            last_run=None,
            created_at=datetime.fromisoformat(now),
        )

    async def remove_job(self, name: str) -> bool:
        assert self._db is not None
        cursor = await self._db.execute("DELETE FROM jobs WHERE name = ?", (name,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def list_jobs(self) -> list[Job]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, name, cron_expr, action, enabled, last_run, created_at FROM jobs"
        )
        rows = await cursor.fetchall()
        return [
            Job(
                id=row[0],
                name=row[1],
                cron_expr=row[2],
                action=row[3],
                enabled=bool(row[4]),
                last_run=datetime.fromisoformat(row[5]) if row[5] else None,
                created_at=datetime.fromisoformat(row[6]),
            )
            for row in rows
        ]
