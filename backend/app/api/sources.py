"""Source health HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.health.source_health import (
    SourceHealthReport,
    get_source_health,
    list_source_health,
)
from app.models.enums import IngestSource
from app.schemas.source_health import SourceHealthListOut, SourceHealthOut

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _to_out(report: SourceHealthReport) -> SourceHealthOut:
    return SourceHealthOut(
        source=report.source,
        status=report.status,
        last_success_at=report.last_success_at,
        last_attempt_at=report.last_attempt_at,
        staleness_seconds=report.staleness_seconds,
        detail=report.detail,
    )


@router.get("/health", response_model=SourceHealthListOut)
async def sources_health(
    session: AsyncSession = Depends(get_session),
) -> SourceHealthListOut:
    reports = await list_source_health(session)
    await session.commit()
    return SourceHealthListOut(sources=[_to_out(r) for r in reports])


@router.get("/health/{source}", response_model=SourceHealthOut)
async def source_health(
    source: IngestSource,
    session: AsyncSession = Depends(get_session),
) -> SourceHealthOut:
    report = await get_source_health(session, source)
    await session.commit()
    return _to_out(report)
