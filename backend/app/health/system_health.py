"""Aggregate system health: API, DB, worker liveness, last batches, errors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.health.source_health import list_source_health
from app.models.enums import IngestBatchStatus, IngestSource, SourceHealthStatus
from app.models.raw import IngestBatch
from app.models.settings import WORKER_HEARTBEAT_ROW_ID, WorkerHeartbeat

# Worker is considered down if no heartbeat within this window.
WORKER_STALE_SECONDS = 90


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    status: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    status: str
    last_seen_at: datetime | None
    staleness_seconds: int | None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class LastBatch:
    source: IngestSource
    batch_id: UUID | None
    status: IngestBatchStatus | None
    started_at: datetime | None
    finished_at: datetime | None
    record_count: int | None
    error: str | None


@dataclass(frozen=True, slots=True)
class SourceErrorCount:
    source: IngestSource
    failed_batches_24h: int
    source_status: SourceHealthStatus | None


@dataclass(frozen=True, slots=True)
class SystemHealthReport:
    status: str
    checked_at: datetime
    api: ComponentStatus
    database: ComponentStatus
    worker: WorkerHealth
    last_batches: list[LastBatch]
    error_counts: list[SourceErrorCount]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def evaluate_worker(
    last_seen_at: datetime | None,
    *,
    now: datetime,
    stale_after: timedelta,
) -> WorkerHealth:
    if last_seen_at is None:
        return WorkerHealth(
            status="down",
            last_seen_at=None,
            staleness_seconds=None,
            detail="No worker heartbeat recorded",
        )
    age = max(0, int((now - last_seen_at).total_seconds()))
    if age >= int(stale_after.total_seconds()):
        return WorkerHealth(
            status="down",
            last_seen_at=last_seen_at,
            staleness_seconds=age,
            detail=f"Last heartbeat {age}s ago (stale)",
        )
    return WorkerHealth(
        status="ok",
        last_seen_at=last_seen_at,
        staleness_seconds=age,
        detail="Worker heartbeat recent",
    )


def _worst(*statuses: str) -> str:
    order = {"ok": 0, "degraded": 1, "down": 2}
    return max(statuses, key=lambda s: order.get(s, 0))


async def touch_worker_heartbeat(
    session: AsyncSession,
    *,
    detail: str = "alive",
    now: datetime | None = None,
) -> WorkerHeartbeat:
    """Upsert the singleton worker heartbeat row."""
    at = now or _utcnow()
    row = await session.get(WorkerHeartbeat, WORKER_HEARTBEAT_ROW_ID)
    if row is None:
        row = WorkerHeartbeat(
            id=WORKER_HEARTBEAT_ROW_ID,
            last_seen_at=at,
            detail=detail,
        )
        session.add(row)
    else:
        row.last_seen_at = at
        row.detail = detail
    await session.flush()
    return row


async def _check_database(session: AsyncSession) -> ComponentStatus:
    try:
        await session.execute(text("SELECT 1"))
        return ComponentStatus(status="ok", detail="Database reachable")
    except Exception as exc:  # noqa: BLE001 — surface any connectivity failure
        return ComponentStatus(status="down", detail=f"Database unreachable: {exc}")


async def _last_batches(session: AsyncSession) -> list[LastBatch]:
    rows: list[LastBatch] = []
    for source in IngestSource:
        result = await session.execute(
            select(IngestBatch)
            .where(IngestBatch.source == source)
            .order_by(IngestBatch.started_at.desc())
            .limit(1)
        )
        batch = result.scalar_one_or_none()
        if batch is None:
            rows.append(
                LastBatch(
                    source=source,
                    batch_id=None,
                    status=None,
                    started_at=None,
                    finished_at=None,
                    record_count=None,
                    error=None,
                )
            )
            continue
        rows.append(
            LastBatch(
                source=source,
                batch_id=batch.id,
                status=batch.status,
                started_at=batch.started_at,
                finished_at=batch.finished_at,
                record_count=batch.record_count,
                error=batch.error,
            )
        )
    return rows


async def _error_counts(
    session: AsyncSession,
    *,
    now: datetime,
) -> list[SourceErrorCount]:
    since = now - timedelta(hours=24)
    source_reports = await list_source_health(session, now=now)
    status_by_source = {r.source: r.status for r in source_reports}

    counts: dict[IngestSource, int] = {s: 0 for s in IngestSource}
    result = await session.execute(
        select(IngestBatch.source, func.count())
        .where(
            IngestBatch.status == IngestBatchStatus.FAILED,
            IngestBatch.started_at >= since,
        )
        .group_by(IngestBatch.source)
    )
    for source, count in result.all():
        counts[source] = int(count)

    return [
        SourceErrorCount(
            source=source,
            failed_batches_24h=counts[source],
            source_status=status_by_source.get(source),
        )
        for source in IngestSource
    ]


async def get_system_health(
    session: AsyncSession,
    *,
    cfg: Settings | None = None,
    now: datetime | None = None,
) -> SystemHealthReport:
    _ = cfg or settings
    at = now or _utcnow()
    api = ComponentStatus(status="ok", detail="API process up")
    database = await _check_database(session)

    hb = await session.get(WorkerHeartbeat, WORKER_HEARTBEAT_ROW_ID)
    worker = evaluate_worker(
        hb.last_seen_at if hb is not None else None,
        now=at,
        stale_after=timedelta(seconds=WORKER_STALE_SECONDS),
    )

    last_batches = await _last_batches(session)
    error_counts = await _error_counts(session, now=at)

    # Degrade if any source is degraded/down or recent failures exist.
    source_statuses = [
        (c.source_status.value if c.source_status is not None else "down")
        for c in error_counts
    ]
    has_recent_failures = any(c.failed_batches_24h > 0 for c in error_counts)
    overall = _worst(api.status, database.status, worker.status, *source_statuses)
    if overall == "ok" and has_recent_failures:
        overall = "degraded"

    return SystemHealthReport(
        status=overall,
        checked_at=at,
        api=api,
        database=database,
        worker=worker,
        last_batches=last_batches,
        error_counts=error_counts,
    )
