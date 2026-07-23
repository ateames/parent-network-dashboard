"""Worker process — heartbeat + scheduled Pi-hole / UniFi ingestion + syslog."""

from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.ingest.pihole import run_poll_once as run_pihole_poll_once
from app.ingest.unifi import run_poll_once as run_unifi_poll_once
from app.ingest.unifi_syslog import run_syslog_listener, syslog_health_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

HEARTBEAT_INTERVAL_SECONDS = 30


async def connect_db() -> None:
    """Verify PostgreSQL connectivity on startup."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("database connection ok")


async def heartbeat_loop() -> None:
    while True:
        logger.info("worker alive")
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


async def pihole_poll_loop() -> None:
    """Poll Pi-hole on a configurable interval; advance `since` after success."""
    since: float | None = None
    interval = max(5, settings.pihole_poll_interval_seconds)
    logger.info("pihole poll interval=%ss", interval)
    while True:
        try:
            batch = await run_pihole_poll_once(since=since)
            logger.info(
                "pihole ingest batch=%s records=%s status=%s",
                batch.id,
                batch.record_count,
                batch.status.value,
            )
            # Next poll asks for queries after this run started (unix seconds).
            since = batch.started_at.timestamp()
        except Exception:
            logger.exception("pihole ingest failed")
        await asyncio.sleep(interval)


async def unifi_poll_loop() -> None:
    """Poll UniFi on a configurable interval (read-only clients + events)."""
    interval = max(5, settings.unifi_poll_interval_seconds)
    logger.info("unifi poll interval=%ss", interval)
    while True:
        try:
            batch = await run_unifi_poll_once()
            logger.info(
                "unifi ingest batch=%s records=%s status=%s",
                batch.id,
                batch.record_count,
                batch.status.value,
            )
        except Exception:
            logger.exception("unifi ingest failed")
        await asyncio.sleep(interval)


async def run() -> None:
    try:
        await connect_db()
        tasks = [
            heartbeat_loop(),
            pihole_poll_loop(),
            unifi_poll_loop(),
        ]
        if settings.unifi_syslog_enabled:
            tasks.append(run_syslog_listener())
            tasks.append(syslog_health_loop())
        else:
            logger.info("unifi syslog listener disabled via UNIFI_SYSLOG_ENABLED")
        await asyncio.gather(*tasks)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
