"""Worker process — heartbeat + scheduled Pi-hole / UniFi ingestion + syslog."""

from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import text

from app.config import Settings, settings
from app.connection_store import resolve_ingest_settings_from_db
from app.db import AsyncSessionLocal, engine
from app.findings.engine import evaluate_and_persist
from app.health.system_health import touch_worker_heartbeat
from app.ingest.pihole import run_poll_once as run_pihole_poll_once
from app.ingest.unifi import run_poll_once as run_unifi_poll_once
from app.ingest.unifi_syslog import run_syslog_listener, syslog_health_loop
from app.settings_store import load_thresholds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

HEARTBEAT_INTERVAL_SECONDS = 30
FINDINGS_INTERVAL_SECONDS = 60


async def connect_db() -> None:
    """Verify PostgreSQL connectivity on startup."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("database connection ok")


async def _poll_intervals() -> tuple[int, int]:
    """Read poll intervals from DB thresholds (env defaults when unset)."""
    async with AsyncSessionLocal() as session:
        thresholds = await load_thresholds(session)
        await session.commit()
    pihole = max(5, int(thresholds["pihole_poll_interval_seconds"]))
    unifi = max(5, int(thresholds["unifi_poll_interval_seconds"]))
    return pihole, unifi


async def _ingest_settings() -> Settings:
    """Reload Pi-hole / UniFi connection settings each poll (DB overlays env)."""
    async with AsyncSessionLocal() as session:
        cfg = await resolve_ingest_settings_from_db(session)
        await session.commit()
    return cfg


async def heartbeat_loop() -> None:
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await touch_worker_heartbeat(session, detail="alive")
                await session.commit()
            logger.info("worker alive")
        except Exception:
            logger.exception("worker heartbeat failed")
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


async def pihole_poll_loop() -> None:
    """Poll Pi-hole on a configurable interval; advance `since` after success."""
    since: float | None = None
    while True:
        interval, _ = await _poll_intervals()
        try:
            cfg = await _ingest_settings()
            batch = await run_pihole_poll_once(cfg=cfg, since=since)
            logger.info(
                "pihole ingest batch=%s records=%s status=%s interval=%ss",
                batch.id,
                batch.record_count,
                batch.status.value,
                interval,
            )
            # Next poll asks for queries after this run started (unix seconds).
            since = batch.started_at.timestamp()
        except Exception:
            logger.exception("pihole ingest failed")
        await asyncio.sleep(interval)


async def unifi_poll_loop() -> None:
    """Poll UniFi on a configurable interval (read-only clients + events)."""
    while True:
        _, interval = await _poll_intervals()
        try:
            cfg = await _ingest_settings()
            batch = await run_unifi_poll_once(cfg=cfg)
            logger.info(
                "unifi ingest batch=%s records=%s status=%s interval=%ss",
                batch.id,
                batch.record_count,
                batch.status.value,
                interval,
            )
        except Exception:
            logger.exception("unifi ingest failed")
        await asyncio.sleep(interval)


async def findings_loop() -> None:
    """Evaluate meaningful findings and publish stream events."""
    interval = FINDINGS_INTERVAL_SECONDS
    logger.info("findings eval interval=%ss", interval)
    while True:
        try:
            async with AsyncSessionLocal() as session:
                drafts = await evaluate_and_persist(session)
                await session.commit()
            logger.info("findings evaluated count=%s", len(drafts))
        except Exception:
            logger.exception("findings evaluation failed")
        await asyncio.sleep(interval)


async def run() -> None:
    try:
        await connect_db()
        tasks = [
            heartbeat_loop(),
            pihole_poll_loop(),
            unifi_poll_loop(),
            findings_loop(),
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
