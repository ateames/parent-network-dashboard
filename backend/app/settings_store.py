"""Load / persist local thresholds and expected-activity schedules."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.models.settings import (
    THRESHOLDS_ROW_ID,
    AppThresholds,
    ExpectedActivitySchedule,
)


def defaults_from_env(cfg: Settings | None = None) -> dict[str, Any]:
    """Threshold defaults from process env (used when no DB row exists)."""
    c = cfg or settings
    return {
        "correlation_confidence_threshold": c.correlation_confidence_threshold,
        "source_health_stale_seconds": c.source_health_stale_seconds,
        "source_health_max_failures": c.source_health_max_failures,
        "pihole_poll_interval_seconds": c.pihole_poll_interval_seconds,
        "unifi_poll_interval_seconds": c.unifi_poll_interval_seconds,
        "baseline_z_threshold": 2.0,
    }


def thresholds_to_dict(row: AppThresholds | None, cfg: Settings | None = None) -> dict[str, Any]:
    base = defaults_from_env(cfg)
    if row is None:
        return {**base, "updated_at": None}
    return {
        "correlation_confidence_threshold": row.correlation_confidence_threshold,
        "source_health_stale_seconds": row.source_health_stale_seconds,
        "source_health_max_failures": row.source_health_max_failures,
        "pihole_poll_interval_seconds": row.pihole_poll_interval_seconds,
        "unifi_poll_interval_seconds": row.unifi_poll_interval_seconds,
        "baseline_z_threshold": row.baseline_z_threshold,
        "updated_at": row.updated_at,
    }


async def get_thresholds_row(session: AsyncSession) -> AppThresholds | None:
    return await session.get(AppThresholds, THRESHOLDS_ROW_ID)


async def load_thresholds(
    session: AsyncSession,
    *,
    cfg: Settings | None = None,
) -> dict[str, Any]:
    row = await get_thresholds_row(session)
    return thresholds_to_dict(row, cfg)


async def ensure_thresholds_row(
    session: AsyncSession,
    *,
    cfg: Settings | None = None,
) -> AppThresholds:
    row = await get_thresholds_row(session)
    if row is not None:
        return row
    defaults = defaults_from_env(cfg)
    row = AppThresholds(id=THRESHOLDS_ROW_ID, **defaults)
    session.add(row)
    await session.flush()
    return row


async def patch_thresholds(
    session: AsyncSession,
    patch: dict[str, Any],
    *,
    cfg: Settings | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply partial threshold updates. Returns (before, after) dicts."""
    row = await ensure_thresholds_row(session, cfg=cfg)
    before = thresholds_to_dict(row, cfg)
    for key, value in patch.items():
        if value is None:
            continue
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    await session.flush()
    after = thresholds_to_dict(row, cfg)
    return before, after


async def list_schedules(
    session: AsyncSession,
    *,
    active_only: bool = False,
) -> list[ExpectedActivitySchedule]:
    stmt = select(ExpectedActivitySchedule).order_by(
        ExpectedActivitySchedule.updated_at.desc()
    )
    if active_only:
        stmt = stmt.where(ExpectedActivitySchedule.active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_schedule(
    session: AsyncSession,
    schedule_id: UUID,
) -> ExpectedActivitySchedule | None:
    return await session.get(ExpectedActivitySchedule, schedule_id)


def schedule_to_dict(row: ExpectedActivitySchedule) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "person_id": str(row.person_id) if row.person_id else None,
        "device_id": str(row.device_id) if row.device_id else None,
        "label": row.label,
        "expected_hours_utc": list(row.expected_hours_utc or []),
        "days_of_week": list(row.days_of_week) if row.days_of_week is not None else None,
        "active": row.active,
    }


async def resolve_expected_hours(
    session: AsyncSession,
    *,
    person_id: UUID | None,
    device_id: UUID | None,
    at: datetime | None = None,
) -> list[int] | None:
    """Return parent-defined expected hours if an active schedule matches.

    Prefers person schedule over device schedule. Optional days_of_week filter
    uses UTC weekday (Monday=0 … Sunday=6).
    """
    when = at or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    weekday = when.astimezone(UTC).weekday()

    schedules = await list_schedules(session, active_only=True)
    person_match: ExpectedActivitySchedule | None = None
    device_match: ExpectedActivitySchedule | None = None
    for row in schedules:
        days = row.days_of_week
        if days is not None and weekday not in {int(d) for d in days}:
            continue
        if person_id is not None and row.person_id == person_id:
            person_match = row
        elif device_id is not None and row.device_id == device_id:
            device_match = row

    chosen = person_match or device_match
    if chosen is None:
        return None
    return [int(h) for h in chosen.expected_hours_utc if 0 <= int(h) <= 23]
