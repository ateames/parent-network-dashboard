"""Poll persisted stream events into the API process bus (worker → SSE)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from app.db import AsyncSessionLocal
from app.events.bus import get_event_bus
from app.events.store import list_events_since

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 1.0


async def fanout_new_events_once(
    *,
    after_created_at: datetime | None,
    after_id: UUID | None,
) -> tuple[datetime | None, UUID | None, int]:
    """Load new DB rows and publish unseen ones to the local bus."""
    bus = get_event_bus()
    async with AsyncSessionLocal() as session:
        events = await list_events_since(
            session,
            after_created_at=after_created_at,
            after_id=after_id,
        )
    if not events:
        return after_created_at, after_id, 0

    published = 0
    watermark_at = after_created_at
    watermark_id = after_id
    for event in events:
        if bus.publish(event):
            published += 1
        watermark_at = event.created_at
        watermark_id = event.id
    return watermark_at, watermark_id, published


async def stream_event_poll_loop(
    *,
    interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Background task: bridge worker-persisted events into the API bus."""
    stop = stop_event or asyncio.Event()
    after_at: datetime | None = None
    after_id: UUID | None = None
    logger.info("stream event poller started interval=%ss", interval_seconds)
    while not stop.is_set():
        try:
            after_at, after_id, count = await fanout_new_events_once(
                after_created_at=after_at,
                after_id=after_id,
            )
            if count:
                logger.debug("stream event poller published=%s", count)
        except Exception:
            logger.exception("stream event poller failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
    logger.info("stream event poller stopped")
