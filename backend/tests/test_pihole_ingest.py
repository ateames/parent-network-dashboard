"""Offline Pi-hole ingest via fixture replay (no live Pi-hole)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.health.source_health import get_source_health
from app.ingest.pihole import (
    LOGIC_VERSION,
    map_pihole_status,
    normalize_query,
    replay_fixture,
)
from app.models.dns import DnsQuery
from app.models.enums import (
    DnsQueryStatus,
    IngestBatchStatus,
    IngestSource,
    SourceHealthStatus,
)
from app.models.raw import IngestBatch, RawPiholeEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CANDIDATES = (
    Path("/fixtures/pihole_sample.json"),
    REPO_ROOT / "fixtures" / "pihole_sample.json",
)


def _fixture_path() -> Path:
    for path in FIXTURE_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "pihole_sample.json not found; expected under /fixtures or repo fixtures/"
    )


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
def ingest_settings() -> Settings:
    return Settings(
        source_health_stale_seconds=300,
        source_health_max_failures=3,
    )


def test_map_pihole_status_buckets() -> None:
    assert map_pihole_status("FORWARDED") == DnsQueryStatus.ALLOWED
    assert map_pihole_status("GRAVITY") == DnsQueryStatus.BLOCKED
    assert map_pihole_status("CACHE") == DnsQueryStatus.CACHED
    assert map_pihole_status("CACHE_STALE") == DnsQueryStatus.CACHED


def test_normalize_prefers_client_name() -> None:
    row = normalize_query(
        {
            "id": 1,
            "time": 1721740800,
            "type": "A",
            "status": "FORWARDED",
            "domain": "example.com",
            "upstream": "1.1.1.1#53",
            "client": {"ip": "192.168.1.50", "name": "ipad-child"},
        }
    )
    assert row.client_identifier == "ipad-child"
    assert row.client_ip == "192.168.1.50"
    assert row.status == DnsQueryStatus.ALLOWED


@pytest.mark.asyncio
async def test_replay_fixture_creates_raw_normalized_and_health(
    db_session: AsyncSession,
    ingest_settings: Settings,
) -> None:
    fixture = _fixture_path()
    batch = await replay_fixture(fixture, cfg=ingest_settings, session=db_session)

    assert batch.status == IngestBatchStatus.SUCCEEDED
    assert batch.record_count == 3
    assert batch.source == IngestSource.PIHOLE_API
    assert batch.finished_at is not None
    assert batch.error is None

    stored_batch = await db_session.get(IngestBatch, batch.id)
    assert stored_batch is not None
    assert stored_batch.status == IngestBatchStatus.SUCCEEDED

    raw_result = await db_session.execute(
        select(RawPiholeEvent).where(RawPiholeEvent.ingest_batch_id == batch.id)
    )
    raw_rows = list(raw_result.scalars().all())
    assert len(raw_rows) == 3
    assert all(isinstance(r.payload, dict) for r in raw_rows)
    assert {r.payload["id"] for r in raw_rows} == {1001, 1002, 1003}

    dns_result = await db_session.execute(
        select(DnsQuery).where(DnsQuery.ingest_batch_id == batch.id)
    )
    dns_rows = list(dns_result.scalars().all())
    assert len(dns_rows) == 3
    assert all(r.logic_version == LOGIC_VERSION for r in dns_rows)

    by_domain = {r.domain: r for r in dns_rows}
    allowed = by_domain["example.com"]
    assert allowed.status == DnsQueryStatus.ALLOWED
    assert allowed.client_identifier == "ipad-child"
    assert allowed.client_ip == "192.168.1.50"
    assert allowed.query_type == "A"
    assert allowed.upstream == "8.8.8.8#53"
    assert allowed.pihole_query_id == "1001"

    blocked = by_domain["ads.tracker.example"]
    assert blocked.status == DnsQueryStatus.BLOCKED
    assert blocked.client_identifier == "ipad-child"

    cached = by_domain["cdn.example.net"]
    assert cached.status == DnsQueryStatus.CACHED
    # Name was null — fall back to IP so we can attribute by client + time later.
    assert cached.client_identifier == "192.168.1.20"
    assert cached.client_ip == "192.168.1.20"
    assert cached.upstream is None

    raw_ids = {r.id for r in raw_rows}
    assert {r.raw_pihole_event_id for r in dns_rows} == raw_ids

    health = await get_source_health(
        db_session,
        IngestSource.PIHOLE_API,
        cfg=ingest_settings,
        refresh=False,
    )
    assert health.status == SourceHealthStatus.OK
    assert health.last_success_at is not None
    assert health.consecutive_failures == 0
