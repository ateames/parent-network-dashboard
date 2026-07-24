"""System health aggregation and worker heartbeat."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import get_session
from app.health.system_health import (
    WORKER_STALE_SECONDS,
    evaluate_worker,
    get_system_health,
    touch_worker_heartbeat,
)
from app.main import app
from app.models.enums import IngestBatchStatus, IngestSource
from app.models.raw import IngestBatch


@pytest.fixture
async def api_client(
    migrated_engine: AsyncEngine,
    db_session: AsyncSession,
) -> AsyncClient:
    _ = db_session
    factory = async_sessionmaker(
        bind=migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def test_evaluate_worker_ok_and_stale() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    ok = evaluate_worker(
        now - timedelta(seconds=10),
        now=now,
        stale_after=timedelta(seconds=WORKER_STALE_SECONDS),
    )
    assert ok.status == "ok"
    assert ok.staleness_seconds == 10

    stale = evaluate_worker(
        now - timedelta(seconds=WORKER_STALE_SECONDS + 5),
        now=now,
        stale_after=timedelta(seconds=WORKER_STALE_SECONDS),
    )
    assert stale.status == "down"

    missing = evaluate_worker(
        None,
        now=now,
        stale_after=timedelta(seconds=WORKER_STALE_SECONDS),
    )
    assert missing.status == "down"


@pytest.mark.asyncio
async def test_touch_heartbeat_and_system_health(db_session: AsyncSession) -> None:
    now = datetime(2026, 7, 23, 15, 0, tzinfo=UTC)
    await touch_worker_heartbeat(db_session, detail="test", now=now)

    batch = IngestBatch(
        id=uuid4(),
        source=IngestSource.PIHOLE_API,
        started_at=now - timedelta(minutes=2),
        finished_at=now - timedelta(minutes=1),
        status=IngestBatchStatus.SUCCEEDED,
        record_count=3,
        error=None,
    )
    db_session.add(batch)
    await db_session.flush()

    report = await get_system_health(db_session, now=now)
    assert report.api.status == "ok"
    assert report.database.status == "ok"
    assert report.worker.status == "ok"
    assert report.worker.last_seen_at == now

    pihole_batch = next(
        b for b in report.last_batches if b.source == IngestSource.PIHOLE_API
    )
    assert pihole_batch.batch_id == batch.id
    assert pihole_batch.status == IngestBatchStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_system_health_http_endpoint(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    await touch_worker_heartbeat(db_session, now=datetime.now(UTC))
    await db_session.commit()

    response = await api_client.get("/api/system/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["api"]["status"] == "ok"
    assert payload["database"]["status"] == "ok"
    assert payload["worker"]["status"] == "ok"
    assert "last_batches" in payload
    assert "error_counts" in payload
