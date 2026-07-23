"""Per-source ingest health: record attempts/successes and derive status.

Ingesters call `record_attempt` / `record_success` / `record_failure`; the API
reads via `list_source_health` / `get_source_health`. Status rules:

- never succeeded -> down
- consecutive_failures >= max_failures -> down
- last success older than stale threshold -> degraded
- otherwise -> ok
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.models.enums import IngestSource, SourceHealthStatus
from app.models.health import SourceHealth


@dataclass(frozen=True, slots=True)
class SourceHealthReport:
    """API-facing snapshot for one ingest source."""

    source: IngestSource
    status: SourceHealthStatus
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    staleness_seconds: int | None
    detail: str
    consecutive_failures: int


def evaluate_status(
    *,
    last_success_at: datetime | None,
    consecutive_failures: int,
    now: datetime,
    stale_after: timedelta,
    max_failures: int,
) -> tuple[SourceHealthStatus, str]:
    """Pure status derivation — unit-test without a database."""
    if last_success_at is None:
        return SourceHealthStatus.DOWN, "Never succeeded"

    if consecutive_failures >= max_failures:
        return (
            SourceHealthStatus.DOWN,
            f"{consecutive_failures} consecutive failure(s)",
        )

    age = now - last_success_at
    if age >= stale_after:
        return (
            SourceHealthStatus.DEGRADED,
            f"Last success {int(age.total_seconds())}s ago (stale)",
        )

    if consecutive_failures > 0:
        return (
            SourceHealthStatus.DEGRADED,
            f"{consecutive_failures} consecutive failure(s)",
        )

    return SourceHealthStatus.OK, "Healthy"


def staleness_seconds(
    last_success_at: datetime | None,
    now: datetime,
) -> int | None:
    if last_success_at is None:
        return None
    return max(0, int((now - last_success_at).total_seconds()))


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _thresholds(cfg: Settings) -> tuple[timedelta, int]:
    return (
        timedelta(seconds=cfg.source_health_stale_seconds),
        cfg.source_health_max_failures,
    )


def _apply_status(
    row: SourceHealth,
    *,
    now: datetime,
    cfg: Settings,
    detail_override: str | None = None,
    preserve_detail: bool = False,
) -> None:
    stale_after, max_failures = _thresholds(cfg)
    status, auto_detail = evaluate_status(
        last_success_at=row.last_success_at,
        consecutive_failures=row.consecutive_failures,
        now=now,
        stale_after=stale_after,
        max_failures=max_failures,
    )
    row.status = status
    if detail_override is not None:
        row.detail = detail_override
    elif not preserve_detail:
        row.detail = auto_detail
    row.checked_at = now


async def _get_row(
    session: AsyncSession,
    source: IngestSource,
) -> SourceHealth | None:
    result = await session.execute(
        select(SourceHealth).where(SourceHealth.source == source)
    )
    return result.scalar_one_or_none()


async def _get_or_create(
    session: AsyncSession,
    source: IngestSource,
    *,
    now: datetime,
) -> SourceHealth:
    row = await _get_row(session, source)
    if row is not None:
        return row
    row = SourceHealth(
        source=source,
        last_success_at=None,
        last_attempt_at=now,
        status=SourceHealthStatus.DOWN,
        detail="Never succeeded",
        consecutive_failures=0,
        checked_at=now,
    )
    session.add(row)
    return row


def _to_report(row: SourceHealth, *, now: datetime) -> SourceHealthReport:
    return SourceHealthReport(
        source=row.source,
        status=row.status,
        last_success_at=row.last_success_at,
        last_attempt_at=row.last_attempt_at,
        staleness_seconds=staleness_seconds(row.last_success_at, now),
        detail=row.detail,
        consecutive_failures=row.consecutive_failures,
    )


def _synthetic_unseen(source: IngestSource) -> SourceHealthReport:
    return SourceHealthReport(
        source=source,
        status=SourceHealthStatus.DOWN,
        last_success_at=None,
        last_attempt_at=None,
        staleness_seconds=None,
        detail="Never succeeded",
        consecutive_failures=0,
    )


async def _emit_source_down_if_needed(
    session: AsyncSession,
    row: SourceHealth,
    previous_status: SourceHealthStatus,
    *,
    now: datetime,
) -> None:
    """Publish a live event when a previously-working source goes down."""
    if row.status != SourceHealthStatus.DOWN:
        return
    if previous_status not in (
        SourceHealthStatus.OK,
        SourceHealthStatus.DEGRADED,
    ):
        return
    from app.events.publish import publish_source_data_loss

    await publish_source_data_loss(
        session,
        source=row.source.value,
        detail=row.detail,
        occurred_at=now,
    )


async def record_attempt(
    session: AsyncSession,
    source: IngestSource,
    *,
    detail: str | None = None,
    now: datetime | None = None,
    cfg: Settings | None = None,
) -> SourceHealth:
    """Mark that an ingest cycle started (or was attempted)."""
    now = now or _utcnow()
    cfg = cfg or settings
    row = await _get_or_create(session, source, now=now)
    previous = row.status
    row.last_attempt_at = now
    _apply_status(row, now=now, cfg=cfg, detail_override=detail)
    await session.flush()
    await _emit_source_down_if_needed(session, row, previous, now=now)
    return row


async def record_success(
    session: AsyncSession,
    source: IngestSource,
    *,
    detail: str | None = None,
    now: datetime | None = None,
    cfg: Settings | None = None,
) -> SourceHealth:
    """Mark a successful ingest for ``source`` (resets failure streak)."""
    now = now or _utcnow()
    cfg = cfg or settings
    row = await _get_or_create(session, source, now=now)
    row.last_attempt_at = now
    row.last_success_at = now
    row.consecutive_failures = 0
    _apply_status(row, now=now, cfg=cfg, detail_override=detail)
    await session.flush()
    return row


async def record_failure(
    session: AsyncSession,
    source: IngestSource,
    *,
    detail: str | None = None,
    now: datetime | None = None,
    cfg: Settings | None = None,
) -> SourceHealth:
    """Mark a failed ingest attempt (increments consecutive failures)."""
    now = now or _utcnow()
    cfg = cfg or settings
    row = await _get_or_create(session, source, now=now)
    previous = row.status
    row.last_attempt_at = now
    row.consecutive_failures += 1
    _apply_status(row, now=now, cfg=cfg, detail_override=detail)
    await session.flush()
    await _emit_source_down_if_needed(session, row, previous, now=now)
    return row


async def get_source_health(
    session: AsyncSession,
    source: IngestSource,
    *,
    now: datetime | None = None,
    cfg: Settings | None = None,
    refresh: bool = True,
) -> SourceHealthReport:
    """Return current health for one source (synthetic down if never seen)."""
    now = now or _utcnow()
    cfg = cfg or settings
    row = await _get_row(session, source)
    if row is None:
        return _synthetic_unseen(source)
    if refresh:
        _apply_status(row, now=now, cfg=cfg, preserve_detail=True)
        await session.flush()
    return _to_report(row, now=now)


async def list_source_health(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    cfg: Settings | None = None,
    refresh: bool = True,
) -> list[SourceHealthReport]:
    """Return health for every known ingest source."""
    now = now or _utcnow()
    cfg = cfg or settings
    result = await session.execute(select(SourceHealth))
    rows = {row.source: row for row in result.scalars().all()}

    reports: list[SourceHealthReport] = []
    for source in IngestSource:
        row = rows.get(source)
        if row is None:
            reports.append(_synthetic_unseen(source))
            continue
        if refresh:
            _apply_status(row, now=now, cfg=cfg, preserve_detail=True)
        reports.append(_to_report(row, now=now))
    if refresh:
        await session.flush()
    return reports
