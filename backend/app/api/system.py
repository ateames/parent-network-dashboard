"""System health HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.health.system_health import get_system_health
from app.schemas.system_health import (
    ComponentStatusOut,
    LastBatchOut,
    SourceErrorCountOut,
    SystemHealthOut,
    WorkerHealthOut,
)

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health", response_model=SystemHealthOut)
async def system_health(
    session: AsyncSession = Depends(get_session),
) -> SystemHealthOut:
    report = await get_system_health(session)
    await session.commit()
    return SystemHealthOut(
        status=report.status,
        checked_at=report.checked_at,
        api=ComponentStatusOut(
            status=report.api.status, detail=report.api.detail
        ),
        database=ComponentStatusOut(
            status=report.database.status, detail=report.database.detail
        ),
        worker=WorkerHealthOut(
            status=report.worker.status,
            last_seen_at=report.worker.last_seen_at,
            staleness_seconds=report.worker.staleness_seconds,
            detail=report.worker.detail,
        ),
        last_batches=[
            LastBatchOut(
                source=b.source,
                batch_id=str(b.batch_id) if b.batch_id is not None else None,
                status=b.status,
                started_at=b.started_at,
                finished_at=b.finished_at,
                record_count=b.record_count,
                error=b.error,
            )
            for b in report.last_batches
        ],
        error_counts=[
            SourceErrorCountOut(
                source=c.source,
                failed_batches_24h=c.failed_batches_24h,
                source_status=c.source_status,
            )
            for c in report.error_counts
        ],
    )
