"""Dashboard summary shape and incomplete-data safety when sources are down."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.correlate.engine import LOGIC_VERSION as CORRELATION_LOGIC_VERSION
from app.dashboard.summary import (
    DASHBOARD_LOGIC_VERSION,
    derive_household_status,
    incomplete_sources_from_health,
)
from app.db import get_session
from app.health.source_health import SourceHealthReport, record_failure, record_success
from app.identity.resolver import ClientObservation, resolve_observation
from app.main import app
from app.models.dns import DnsActivity, DnsQuery
from app.models.enums import (
    CorrelationStatus,
    DnsQueryStatus,
    IngestBatchStatus,
    IngestSource,
    PersonRole,
    SourceHealthStatus,
)
from app.models.people import Person, PersonDevice
from app.models.raw import IngestBatch, RawPiholeEvent

REQUIRED_TOP_KEYS = frozenset(
    {
        "status",
        "status_reason",
        "data_incomplete",
        "incomplete_sources",
        "attention",
        "active_children",
        "active_children_incomplete",
        "online_devices",
        "unknown_unassigned",
        "recent_activity",
        "findings_by_severity",
        "trends",
        "data_health",
        "generated_at",
        "logic_version",
    }
)


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


def test_incomplete_sources_only_down() -> None:
    reports = [
        SourceHealthReport(
            source=IngestSource.PIHOLE_API,
            status=SourceHealthStatus.DOWN,
            last_success_at=None,
            last_attempt_at=None,
            staleness_seconds=None,
            detail="Never succeeded",
            consecutive_failures=0,
        ),
        SourceHealthReport(
            source=IngestSource.UNIFI_API,
            status=SourceHealthStatus.OK,
            last_success_at=datetime.now(UTC),
            last_attempt_at=datetime.now(UTC),
            staleness_seconds=0,
            detail="Healthy",
            consecutive_failures=0,
        ),
        SourceHealthReport(
            source=IngestSource.UNIFI_SYSLOG,
            status=SourceHealthStatus.DEGRADED,
            last_success_at=datetime.now(UTC) - timedelta(seconds=600),
            last_attempt_at=datetime.now(UTC),
            staleness_seconds=600,
            detail="stale",
            consecutive_failures=0,
        ),
    ]
    assert incomplete_sources_from_health(reports) == [IngestSource.PIHOLE_API]


def test_derive_status_prefers_incomplete_reason() -> None:
    status, reason = derive_household_status(
        incomplete_sources=[IngestSource.UNIFI_API],
        attention_items=[],
        attention_count=0,
    )
    assert status == "attention-needed"
    assert "Data incomplete" in reason
    assert "unifi_api" in reason


async def _mark_all_sources_ok(
    session: AsyncSession,
    *,
    now: datetime,
    cfg: Settings,
) -> None:
    for source in IngestSource:
        await record_success(session, source, now=now, cfg=cfg)


async def _seed_device(
    session: AsyncSession,
    *,
    mac: str,
    observed_at: datetime,
    hostname: str = "ipad",
):
    return await resolve_observation(
        session,
        ClientObservation(
            observed_at=observed_at,
            source="unifi_api",
            mac=mac,
            unifi_client_id=f"client-{mac[-2:]}",
            hostname=hostname,
            ip="192.168.1.50",
        ),
    )


async def _seed_child_with_device(
    session: AsyncSession,
    *,
    device_id,
    name: str = "Alex",
) -> Person:
    person = Person(
        logic_version="person.v1",
        name=name,
        role=PersonRole.CHILD,
        notes=None,
    )
    session.add(person)
    await session.flush()
    session.add(
        PersonDevice(
            logic_version="person.v1",
            person_id=person.id,
            device_id=device_id,
            assigned_by="admin",
            assigned_at=datetime.now(UTC),
            active=True,
        )
    )
    await session.flush()
    return person


async def _seed_attributed_query(
    session: AsyncSession,
    *,
    device_id,
    queried_at: datetime,
    domain: str,
    status: DnsQueryStatus = DnsQueryStatus.BLOCKED,
) -> DnsQuery:
    batch = IngestBatch(
        source=IngestSource.PIHOLE_API,
        started_at=queried_at,
        status=IngestBatchStatus.SUCCEEDED,
        record_count=1,
        finished_at=queried_at,
    )
    session.add(batch)
    await session.flush()
    raw = RawPiholeEvent(
        source_ts=queried_at,
        payload={"domain": domain},
        ingest_batch_id=batch.id,
    )
    session.add(raw)
    await session.flush()
    query = DnsQuery(
        logic_version="dns_query.v1",
        queried_at=queried_at,
        client_identifier="ipad-child",
        client_ip="192.168.1.50",
        domain=domain,
        query_type="A",
        status=status,
        upstream=None,
        pihole_query_id=None,
        raw_pihole_event_id=raw.id,
        ingest_batch_id=batch.id,
    )
    session.add(query)
    await session.flush()
    session.add(
        DnsActivity(
            logic_version=CORRELATION_LOGIC_VERSION,
            dns_query_id=query.id,
            device_id=device_id,
            queried_at=queried_at,
            confidence=Decimal("0.9000"),
            evidence={"matches": []},
            conflicts={"items": []},
            status=CorrelationStatus.ATTRIBUTED,
            needs_review=False,
        )
    )
    await session.flush()
    return query


@pytest.mark.asyncio
async def test_dashboard_summary_shape_when_healthy(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    now = datetime.now(UTC)
    cfg = Settings(
        source_health_stale_seconds=300,
        source_health_max_failures=3,
        device_online_seconds=300,
    )
    await _mark_all_sources_ok(db_session, now=now, cfg=cfg)

    device = await _seed_device(
        db_session,
        mac="aa:bb:cc:dd:ee:10",
        observed_at=now,
    )
    await _seed_child_with_device(db_session, device_id=device.id)
    await _seed_attributed_query(
        db_session,
        device_id=device.id,
        queried_at=now - timedelta(minutes=1),
        domain="ads.tracker.example",
        status=DnsQueryStatus.BLOCKED,
    )
    await db_session.commit()

    response = await api_client.get("/api/dashboard/summary")
    assert response.status_code == 200
    body = response.json()

    assert REQUIRED_TOP_KEYS <= set(body.keys())
    assert body["logic_version"] == DASHBOARD_LOGIC_VERSION
    assert body["data_incomplete"] is False
    assert body["incomplete_sources"] == []
    assert body["status"] in ("ok", "attention-needed")
    assert isinstance(body["status_reason"], str)
    assert body["status_reason"]

    assert "count" in body["attention"]
    assert "items" in body["attention"]
    assert isinstance(body["active_children"], list)
    assert body["active_children_incomplete"] is False

    assert body["online_devices"]["incomplete"] is False
    assert body["online_devices"]["count"] == 1
    assert len(body["online_devices"]["devices"]) == 1

    assert body["unknown_unassigned"]["incomplete"] is False
    assert isinstance(body["unknown_unassigned"]["count"], int)

    assert body["recent_activity"]["incomplete"] is False
    assert len(body["recent_activity"]["items"]) >= 1
    assert body["recent_activity"]["items"][0]["kind"] == "blocked_dns"

    findings = body["findings_by_severity"]
    assert findings == {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0,
    }

    assert body["trends"]["window"] == "24h"
    assert body["trends"]["incomplete"] is False
    dns_metrics = {m["metric"]: m for m in body["trends"]["dns"]}
    assert dns_metrics["dns_query_volume"]["today_value"] == 1.0
    assert dns_metrics["dns_query_volume"]["incomplete"] is False

    sources = {s["source"]: s for s in body["data_health"]["sources"]}
    assert set(sources) >= {"pihole_api", "unifi_api", "unifi_syslog"}
    for name in ("pihole_api", "unifi_api", "unifi_syslog"):
        assert sources[name]["status"] == "ok"
        assert isinstance(sources[name]["staleness_seconds"], int)


@pytest.mark.asyncio
async def test_down_source_marks_data_incomplete_not_silent_zeros(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    now = datetime.now(UTC)
    cfg = Settings(
        source_health_stale_seconds=300,
        source_health_max_failures=3,
        device_online_seconds=300,
    )
    # UniFi healthy so devices exist; Pi-hole explicitly down.
    await record_success(db_session, IngestSource.UNIFI_API, now=now, cfg=cfg)
    await record_success(db_session, IngestSource.UNIFI_SYSLOG, now=now, cfg=cfg)
    await record_success(
        db_session,
        IngestSource.PIHOLE_API,
        now=now - timedelta(seconds=10),
        cfg=cfg,
    )
    for _ in range(cfg.source_health_max_failures):
        await record_failure(
            db_session,
            IngestSource.PIHOLE_API,
            now=now,
            cfg=cfg,
            detail="connection refused",
        )

    device = await _seed_device(
        db_session,
        mac="aa:bb:cc:dd:ee:20",
        observed_at=now,
    )
    await _seed_child_with_device(db_session, device_id=device.id, name="Sam")
    await db_session.commit()

    response = await api_client.get("/api/dashboard/summary")
    assert response.status_code == 200
    body = response.json()

    assert body["data_incomplete"] is True
    assert "pihole_api" in body["incomplete_sources"]
    assert body["status"] == "attention-needed"
    assert "Data incomplete" in body["status_reason"]

    # Must not invent a quiet DNS picture when Pi-hole is down.
    assert body["recent_activity"]["incomplete"] is True
    assert body["recent_activity"]["items"] == []
    dns_metrics = {m["metric"]: m for m in body["trends"]["dns"]}
    assert dns_metrics["dns_query_volume"]["incomplete"] is True
    assert dns_metrics["dns_query_volume"]["today_value"] is None
    assert body["trends"]["incomplete"] is True
    assert any("pihole_api" in r for r in body["trends"]["incomplete_reasons"])

    # Active children need both sources; Pi-hole alone down is enough.
    assert body["active_children_incomplete"] is True

    # UniFi still healthy → online counts remain real numbers, not wiped.
    assert body["online_devices"]["incomplete"] is False
    assert body["online_devices"]["count"] == 1


@pytest.mark.asyncio
async def test_unifi_down_nulls_online_counts(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    now = datetime.now(UTC)
    cfg = Settings(
        source_health_stale_seconds=300,
        source_health_max_failures=3,
        device_online_seconds=300,
    )
    await record_success(db_session, IngestSource.PIHOLE_API, now=now, cfg=cfg)
    await record_success(db_session, IngestSource.UNIFI_SYSLOG, now=now, cfg=cfg)
    await record_success(
        db_session,
        IngestSource.UNIFI_API,
        now=now - timedelta(seconds=10),
        cfg=cfg,
    )
    for _ in range(cfg.source_health_max_failures):
        await record_failure(
            db_session,
            IngestSource.UNIFI_API,
            now=now,
            cfg=cfg,
            detail="timeout",
        )

    # Stale device still in DB — must not be reported as "0 online".
    await _seed_device(
        db_session,
        mac="aa:bb:cc:dd:ee:30",
        observed_at=now,
    )
    await db_session.commit()

    response = await api_client.get("/api/dashboard/summary")
    assert response.status_code == 200
    body = response.json()

    assert body["data_incomplete"] is True
    assert "unifi_api" in body["incomplete_sources"]
    assert body["online_devices"]["incomplete"] is True
    assert body["online_devices"]["count"] is None
    assert body["online_devices"]["devices"] == []
    assert body["unknown_unassigned"]["incomplete"] is True
    assert body["unknown_unassigned"]["count"] is None

    # Active children need both sources; UniFi alone down is enough.
    assert body["active_children_incomplete"] is True

    network = {m["metric"]: m for m in body["trends"]["network"]}
    assert network["upload_bytes"]["incomplete"] is True
    assert network["upload_bytes"]["today_value"] is None
