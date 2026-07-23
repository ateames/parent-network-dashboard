"""Database queries for stream event backfill and cross-process fan-out."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.ordering import SEVERITY_RANK
from app.events.publish import event_from_row
from app.models.enums import FindingSeverity
from app.models.events import StreamEvent
from app.schemas.events import StreamEventOut

_SEVERITY_ORDER = case(
    (
        StreamEvent.severity == FindingSeverity.HIGH,
        SEVERITY_RANK[FindingSeverity.HIGH],
    ),
    (
        StreamEvent.severity == FindingSeverity.MEDIUM,
        SEVERITY_RANK[FindingSeverity.MEDIUM],
    ),
    (
        StreamEvent.severity == FindingSeverity.LOW,
        SEVERITY_RANK[FindingSeverity.LOW],
    ),
    else_=SEVERITY_RANK[FindingSeverity.INFO],
)


async def list_recent_events(
    session: AsyncSession,
    *,
    limit: int = 50,
) -> list[StreamEventOut]:
    """Latest N events ordered by severity (high first), then time (newest)."""
    stmt = (
        select(StreamEvent)
        .order_by(
            _SEVERITY_ORDER.desc(),
            StreamEvent.occurred_at.desc(),
            StreamEvent.id.desc(),
        )
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [event_from_row(row) for row in result.scalars().all()]


async def list_events_since(
    session: AsyncSession,
    *,
    after_created_at: datetime | None = None,
    after_id: UUID | None = None,
    limit: int = 100,
) -> list[StreamEventOut]:
    """Events created after a watermark (chronological) for API bus fan-out."""
    stmt = select(StreamEvent).order_by(
        StreamEvent.created_at.asc(),
        StreamEvent.id.asc(),
    )
    if after_created_at is not None:
        if after_id is not None:
            stmt = stmt.where(
                (StreamEvent.created_at > after_created_at)
                | (
                    (StreamEvent.created_at == after_created_at)
                    & (StreamEvent.id > after_id)
                )
            )
        else:
            stmt = stmt.where(StreamEvent.created_at > after_created_at)
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return [event_from_row(row) for row in result.scalars().all()]
