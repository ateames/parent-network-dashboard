"""Activity aggregation math — offline fixtures, no live Pi-hole/UniFi."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.activity.aggregate import (
    AGGREGATE_LOGIC_VERSION,
    DnsActivityRecord,
    UnifiTrafficRecord,
    aggregate_activity,
    aggregate_dns_records,
    aggregate_unifi_traffic,
    build_activity_summary,
    parse_window,
)
from app.correlate.engine import LOGIC_VERSION as CORRELATION_LOGIC_VERSION
from app.db import get_session
from app.identity.resolver import ClientObservation, resolve_observation
from app.main import app
from app.models.dns import DnsActivity, DnsQuery
from app.models.enums import (
    CorrelationStatus,
    DnsQueryStatus,
    IngestBatchStatus,
    IngestSource,
    PersonRole,
)
from app.models.people import Person, PersonDevice
from app.models.raw import IngestBatch, RawPiholeEvent, RawUnifiClient

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
PIHOLE_FIXTURE = FIXTURES / "pihole_sample.json"
UNIFI_CLIENTS_FIXTURE = FIXTURES / "unifi_clients_sample.json"


def test_parse_window_hours_and_days() -> None:
    assert parse_window("1h") == timedelta(hours=1)
    assert parse_window("24h") == timedelta(hours=24)
    assert parse_window("7d") == timedelta(days=7)
    with pytest.raises(ValueError):
        parse_window("week")


def test_aggregate_dns_math_on_fixture_shaped_records() -> None:
    """Fixture domains/statuses → volume, block %, unique + new domains, hours."""
    payload = json.loads(PIHOLE_FIXTURE.read_text())
    device_a = uuid4()
    device_b = uuid4()
    # Map fixture queries: first two from .50 (ipad), third from .20 (laptop).
    status_map = {
        "FORWARDED": DnsQueryStatus.ALLOWED,
        "GRAVITY": DnsQueryStatus.BLOCKED,
        "CACHE": DnsQueryStatus.CACHED,
    }
    records: list[DnsActivityRecord] = []
    for row in payload["queries"]:
        client_ip = row["client"]["ip"]
        device_id = device_a if client_ip.endswith(".50") else device_b
        records.append(
            DnsActivityRecord(
                queried_at=datetime.fromtimestamp(row["time"], tz=UTC),
                domain=row["domain"],
                status=status_map[row["status"]],
                device_id=device_id,
            )
        )

    # Window tightly around fixture query times (epoch seconds in sample JSON).
    times = [r.queried_at for r in records]
    window_start = min(times) - timedelta(seconds=1)
    window_end = max(times) + timedelta(seconds=1)
    # Prior: example.com already seen for device_a → not "new".
    device_a_records = [r for r in records if r.device_id == device_a]
    assert len(device_a_records) == 2
    dns = aggregate_dns_records(
        device_a_records,
        window_start=window_start,
        window_end=window_end,
        prior_domains={"example.com"},
    )

    assert dns["dns_query_volume"] == 2
    assert dns["blocked_query_count"] == 1
    assert dns["blocked_query_pct"] == 50.0
    assert dns["unique_domain_count"] == 2
    assert dns["new_domain_count"] == 1
    assert dns["new_domains"] == ["ads.tracker.example"]
    assert dns["active_hour_count"] == 1
    assert dns["active_hours_utc"] == (device_a_records[0].queried_at.hour,)


def test_aggregate_unifi_upload_download_and_duration_from_fixture() -> None:
    payload = json.loads(UNIFI_CLIENTS_FIXTURE.read_text())
    device_ipad = uuid4()
    device_laptop = uuid4()
    mac_to_device = {
        "aa:bb:cc:dd:ee:01": device_ipad,
        "aa:bb:cc:dd:ee:02": device_laptop,
    }
    # Use an explicit uptime so duration math is independent of first/last_seen.
    observed = datetime.fromtimestamp(payload["data"][0]["last_seen"], tz=UTC)
    records: list[UnifiTrafficRecord] = []
    for row in payload["data"]:
        mac = row["mac"].lower()
        mac = ":".join(
            mac.replace("-", "").replace(":", "")[i : i + 2] for i in range(0, 12, 2)
        )
        device_id = mac_to_device.get(mac)
        if device_id is None:
            continue
        # UniFi: rx=upload, tx=download from device perspective.
        records.append(
            UnifiTrafficRecord(
                device_id=device_id,
                observed_at=observed,
                upload_bytes=int(row["rx_bytes"]),
                download_bytes=int(row["tx_bytes"]),
                connection_duration_seconds=3600.0,
                source_fields={"mac": mac, "uptime": 3600},
            )
        )

    unifi = aggregate_unifi_traffic(records, device_ids={device_ipad})
    assert unifi["upload_bytes"] == 5242880
    assert unifi["download_bytes"] == 1048576
    assert unifi["connection_duration_seconds"] == 3600.0

    person = aggregate_unifi_traffic(records, device_ids={device_ipad, device_laptop})
    assert person["upload_bytes"] == 5242880 + 10485760
    assert person["download_bytes"] == 1048576 + 2097152
    assert person["connection_duration_seconds"] == 7200.0


def test_build_activity_summary_combines_dns_and_unifi() -> None:
    device_id = uuid4()
    t0 = datetime(2024, 7, 23, 15, 0, tzinfo=UTC)
    summary = build_activity_summary(
        subject_type="device",
        subject_id=device_id,
        window_start=t0,
        window_end=t0 + timedelta(hours=1),
        dns_records=[
            DnsActivityRecord(
                queried_at=t0 + timedelta(minutes=5),
                domain="a.example",
                status=DnsQueryStatus.ALLOWED,
                device_id=device_id,
            ),
            DnsActivityRecord(
                queried_at=t0 + timedelta(minutes=10),
                domain="b.example",
                status=DnsQueryStatus.BLOCKED,
                device_id=device_id,
            ),
        ],
        prior_domains=(),
        unifi_records=[
            UnifiTrafficRecord(
                device_id=device_id,
                observed_at=t0 + timedelta(minutes=30),
                upload_bytes=100,
                download_bytes=200,
                connection_duration_seconds=60.0,
            )
        ],
        device_ids={device_id},
    )
    assert summary.dns_query_volume == 2
    assert summary.blocked_query_pct == 50.0
    assert summary.unique_domain_count == 2
    assert summary.new_domain_count == 2
    assert summary.upload_bytes == 100
    assert summary.download_bytes == 200
    assert summary.connection_duration_seconds == 60.0
    assert summary.logic_version == AGGREGATE_LOGIC_VERSION
    assert "disclaimer" in summary.inputs


async def _seed_attributed_query(
    session: AsyncSession,
    *,
    device_id,
    queried_at: datetime,
    domain: str,
    status: DnsQueryStatus = DnsQueryStatus.ALLOWED,
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


@pytest.mark.asyncio
async def test_aggregate_activity_db_and_api(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    # Relative to wall clock so the API (which uses datetime.now) sees the rows.
    now = datetime.now(UTC)
    device = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=now,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:01",
            unifi_client_id="64a1b2c3d4e5f67890123401",
            hostname="ipad-child",
            ip="192.168.1.50",
        ),
    )
    # Prior domain outside window.
    await _seed_attributed_query(
        db_session,
        device_id=device.id,
        queried_at=now - timedelta(days=2),
        domain="example.com",
    )
    await _seed_attributed_query(
        db_session,
        device_id=device.id,
        queried_at=now - timedelta(seconds=30),
        domain="example.com",
    )
    await _seed_attributed_query(
        db_session,
        device_id=device.id,
        queried_at=now - timedelta(seconds=20),
        domain="ads.tracker.example",
        status=DnsQueryStatus.BLOCKED,
    )

    batch = IngestBatch(
        source=IngestSource.UNIFI_API,
        started_at=now,
        status=IngestBatchStatus.SUCCEEDED,
        record_count=1,
        finished_at=now,
    )
    db_session.add(batch)
    await db_session.flush()
    clients = json.loads(UNIFI_CLIENTS_FIXTURE.read_text())["data"]
    ipad = dict(clients[0])
    # Keep fixture byte counters; stretch last_seen into the live window.
    ipad["last_seen"] = int(now.timestamp())
    ipad["first_seen"] = int((now - timedelta(hours=2)).timestamp())
    db_session.add(
        RawUnifiClient(
            ingested_at=now - timedelta(seconds=10),
            payload=ipad,
            ingest_batch_id=batch.id,
        )
    )
    await db_session.commit()

    summary = await aggregate_activity(
        db_session,
        window="1h",
        device_id=device.id,
        now=now,
    )
    assert summary.dns_query_volume == 2
    assert summary.blocked_query_pct == 50.0
    assert summary.unique_domain_count == 2
    assert summary.new_domain_count == 1  # ads.tracker.example only
    assert summary.upload_bytes == 5242880
    assert summary.download_bytes == 1048576
    assert summary.connection_duration_seconds is not None

    resp = await api_client.get(
        "/api/activity",
        params={"device": str(device.id), "window": "1h"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dns_query_volume"] == 2
    assert body["blocked_query_pct"] == 50.0
    assert body["new_domain_count"] == 1
    assert body["upload_bytes"] == 5242880
    assert body["logic_version"] == AGGREGATE_LOGIC_VERSION


@pytest.mark.asyncio
async def test_aggregate_activity_by_person(
    db_session: AsyncSession,
) -> None:
    now = datetime(2024, 7, 23, 18, 0, tzinfo=UTC)
    d1 = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=now,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:11",
            ip="192.168.1.51",
        ),
    )
    d2 = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=now,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:12",
            ip="192.168.1.52",
        ),
    )
    person = Person(
        logic_version="person.v1",
        name="Sam",
        role=PersonRole.CHILD,
    )
    db_session.add(person)
    await db_session.flush()
    for device in (d1, d2):
        db_session.add(
            PersonDevice(
                logic_version="person.v1",
                person_id=person.id,
                device_id=device.id,
                assigned_by="test",
                active=True,
            )
        )
    await _seed_attributed_query(
        db_session,
        device_id=d1.id,
        queried_at=now - timedelta(minutes=5),
        domain="one.example",
    )
    await _seed_attributed_query(
        db_session,
        device_id=d2.id,
        queried_at=now - timedelta(minutes=4),
        domain="two.example",
    )
    await db_session.commit()

    summary = await aggregate_activity(
        db_session,
        window="1h",
        person_id=person.id,
        now=now,
    )
    assert summary.subject_type == "person"
    assert summary.dns_query_volume == 2
    assert summary.unique_domain_count == 2
