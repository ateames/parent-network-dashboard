"""Unit tests for source-health status derivation and reporting helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.health.source_health import (
    evaluate_status,
    get_source_health,
    list_source_health,
    record_attempt,
    record_failure,
    record_success,
    staleness_seconds,
)
from app.models.enums import IngestSource, SourceHealthStatus


def test_never_succeeded_is_down() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    status, detail = evaluate_status(
        last_success_at=None,
        consecutive_failures=0,
        now=now,
        stale_after=timedelta(seconds=300),
        max_failures=3,
    )
    assert status == SourceHealthStatus.DOWN
    assert "never" in detail.lower()


def test_recent_success_is_ok() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    status, detail = evaluate_status(
        last_success_at=now - timedelta(seconds=30),
        consecutive_failures=0,
        now=now,
        stale_after=timedelta(seconds=300),
        max_failures=3,
    )
    assert status == SourceHealthStatus.OK
    assert detail == "Healthy"


def test_stale_success_is_degraded() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    status, detail = evaluate_status(
        last_success_at=now - timedelta(seconds=601),
        consecutive_failures=0,
        now=now,
        stale_after=timedelta(seconds=300),
        max_failures=3,
    )
    assert status == SourceHealthStatus.DEGRADED
    assert "stale" in detail.lower()


def test_repeated_failures_is_down() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    status, detail = evaluate_status(
        last_success_at=now - timedelta(seconds=10),
        consecutive_failures=3,
        now=now,
        stale_after=timedelta(seconds=300),
        max_failures=3,
    )
    assert status == SourceHealthStatus.DOWN
    assert "failure" in detail.lower()


def test_staleness_seconds_none_when_never_succeeded() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    assert staleness_seconds(None, now) is None


def test_staleness_seconds_from_last_success() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    assert staleness_seconds(now - timedelta(seconds=42), now) == 42


@pytest.fixture
async def db_session(migrated_engine: AsyncEngine) -> AsyncSession:
    factory = async_sessionmaker(
        bind=migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def health_settings() -> Settings:
    return Settings(
        source_health_stale_seconds=300,
        source_health_max_failures=3,
    )


@pytest.mark.asyncio
async def test_record_success_then_list(
    db_session: AsyncSession,
    health_settings: Settings,
) -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    await record_success(
        db_session,
        IngestSource.PIHOLE_API,
        now=now,
        cfg=health_settings,
    )
    await db_session.commit()

    reports = await list_source_health(
        db_session,
        now=now,
        cfg=health_settings,
        refresh=False,
    )
    by_source = {r.source: r for r in reports}
    assert set(by_source) == set(IngestSource)

    pihole = by_source[IngestSource.PIHOLE_API]
    assert pihole.status == SourceHealthStatus.OK
    assert pihole.last_success_at == now
    assert pihole.staleness_seconds == 0

    unseen = by_source[IngestSource.UNIFI_API]
    assert unseen.status == SourceHealthStatus.DOWN
    assert unseen.last_success_at is None
    assert unseen.staleness_seconds is None


@pytest.mark.asyncio
async def test_record_failure_escalates_to_down(
    db_session: AsyncSession,
    health_settings: Settings,
) -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    await record_success(
        db_session,
        IngestSource.UNIFI_SYSLOG,
        now=now,
        cfg=health_settings,
    )
    for i in range(3):
        await record_failure(
            db_session,
            IngestSource.UNIFI_SYSLOG,
            now=now + timedelta(seconds=i + 1),
            cfg=health_settings,
        )
    await db_session.commit()

    report = await get_source_health(
        db_session,
        IngestSource.UNIFI_SYSLOG,
        now=now + timedelta(seconds=10),
        cfg=health_settings,
        refresh=False,
    )
    assert report.status == SourceHealthStatus.DOWN
    assert report.consecutive_failures == 3


@pytest.mark.asyncio
async def test_record_attempt_marks_stale_degraded(
    db_session: AsyncSession,
    health_settings: Settings,
) -> None:
    success_at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    later = success_at + timedelta(seconds=400)
    await record_success(
        db_session,
        IngestSource.UNIFI_API,
        now=success_at,
        cfg=health_settings,
    )
    await record_attempt(
        db_session,
        IngestSource.UNIFI_API,
        now=later,
        cfg=health_settings,
    )
    await db_session.commit()

    report = await get_source_health(
        db_session,
        IngestSource.UNIFI_API,
        now=later,
        cfg=health_settings,
        refresh=False,
    )
    assert report.status == SourceHealthStatus.DEGRADED
    assert report.staleness_seconds == 400
