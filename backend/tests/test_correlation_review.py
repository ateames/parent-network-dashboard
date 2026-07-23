"""Correlation review queue and manual resolution API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import settings
from app.correlate.engine import correlate_window
from app.db import get_session
from app.identity.resolver import ClientObservation, resolve_observation
from app.main import app
from app.models.dns import DnsActivity, DnsQuery
from app.models.enums import (
    CorrelationStatus,
    DnsQueryStatus,
    IdentifierKind,
    IngestBatchStatus,
    IngestSource,
)
from app.models.health import AuditLog
from app.models.identity import DeviceIdentifier
from app.models.raw import IngestBatch, RawPiholeEvent


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


async def _seed_dns_query(
    session: AsyncSession,
    *,
    queried_at: datetime,
    client_identifier: str,
    client_ip: str | None,
    domain: str = "example.com",
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
        payload={
            "domain": domain,
            "client": {"ip": client_ip, "name": client_identifier},
        },
        ingest_batch_id=batch.id,
    )
    session.add(raw)
    await session.flush()
    query = DnsQuery(
        logic_version="dns_query.v1",
        queried_at=queried_at,
        client_identifier=client_identifier,
        client_ip=client_ip,
        domain=domain,
        query_type="A",
        status=DnsQueryStatus.ALLOWED,
        upstream=None,
        pihole_query_id=None,
        raw_pihole_event_id=raw.id,
        ingest_batch_id=batch.id,
    )
    session.add(query)
    await session.flush()
    return query


async def _seed_ambiguous_activity(
    session: AsyncSession,
) -> tuple[DnsActivity, object, object]:
    """Two candidate devices → ambiguous correlation needing review."""
    t0 = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    device_a = await resolve_observation(
        session,
        ClientObservation(
            observed_at=t0,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:70",
            unifi_client_id="client-70",
            hostname="laptop-a",
            ip="192.168.1.70",
        ),
    )
    device_b = await resolve_observation(
        session,
        ClientObservation(
            observed_at=t0,
            source="pihole_api",
            mac="aa:bb:cc:dd:ee:71",
            unifi_client_id="client-71",
            hostname="shared-name",
            pihole_client="shared-name",
            ip="192.168.1.199",
        ),
    )
    query = await _seed_dns_query(
        session,
        queried_at=t0 + timedelta(minutes=1),
        client_identifier="shared-name",
        client_ip="192.168.1.70",
        domain="review.example",
    )
    rows = await correlate_window(session, [query], threshold=Decimal("0.70"))
    await session.commit()
    assert len(rows) == 1
    assert rows[0].status == CorrelationStatus.AMBIGUOUS
    assert rows[0].needs_review is True
    return rows[0], device_a, device_b


@pytest.mark.asyncio
async def test_ambiguous_item_appears_in_review_queue(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    activity, device_a, device_b = await _seed_ambiguous_activity(db_session)

    response = await api_client.get("/api/correlation/review")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1

    item = payload["items"][0]
    assert item["id"] == str(activity.id)
    assert item["status"] == "ambiguous"
    assert item["needs_review"] is True
    assert item["domain"] == "review.example"
    assert item["client_identifier"] == "shared-name"
    assert item["queried_at"]
    assert item["confidence"] is not None
    assert item["evidence"]["matches"]
    assert item["conflicts"]["items"]

    candidate_ids = {c["id"] for c in item["candidate_devices"]}
    assert candidate_ids == {str(device_a.id), str(device_b.id)}
    names = {c["display_name"] for c in item["candidate_devices"]}
    assert "laptop-a" in names
    assert "shared-name" in names


@pytest.mark.asyncio
async def test_resolve_attributes_device_updates_status_and_audit(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    activity, device_a, _device_b = await _seed_ambiguous_activity(db_session)
    query = (
        await db_session.execute(
            select(DnsQuery).where(DnsQuery.id == activity.dns_query_id)
        )
    ).scalar_one()
    raw_before = (
        await db_session.execute(
            select(RawPiholeEvent).where(
                RawPiholeEvent.id == query.raw_pihole_event_id
            )
        )
    ).scalar_one()
    raw_payload_before = dict(raw_before.payload)

    resolved = await api_client.post(
        f"/api/correlation/review/{activity.id}/resolve",
        json={
            "device_id": str(device_a.id),
            "strengthen_identifier": True,
        },
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["status"] == "attributed"
    assert body["needs_review"] is False
    assert body["device_id"] == str(device_a.id)
    assert Decimal(body["confidence"]) == Decimal("1.0000")
    assert body["evidence"]["manual_resolution"]["decision"] == "attribute"
    assert body["evidence"]["manual_resolution"]["strengthen_identifier"] is True

    await db_session.refresh(activity)
    assert activity.status == CorrelationStatus.ATTRIBUTED
    assert activity.device_id == device_a.id
    assert activity.needs_review is False

    audits = list(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "correlation.resolve")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].actor == settings.admin_username
    assert audits[0].entity_type == "dns_activity"
    assert audits[0].entity_id == activity.id
    assert audits[0].before is not None
    assert audits[0].before["status"] == "ambiguous"
    assert audits[0].before["needs_review"] is True
    assert audits[0].after is not None
    assert audits[0].after["status"] == "attributed"
    assert audits[0].after["needs_review"] is False
    assert audits[0].after["device_id"] == str(device_a.id)

    # Strengthened future matching via device_identifier — raw payload untouched.
    identifiers = list(
        (
            await db_session.execute(
                select(DeviceIdentifier).where(
                    DeviceIdentifier.device_id == device_a.id,
                    DeviceIdentifier.kind == IdentifierKind.PIHOLE_CLIENT,
                    DeviceIdentifier.value == "shared-name",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(identifiers) == 1
    assert identifiers[0].confidence == Decimal("0.9000")

    raw_after = (
        await db_session.execute(
            select(RawPiholeEvent).where(RawPiholeEvent.id == raw_before.id)
        )
    ).scalar_one()
    assert raw_after.payload == raw_payload_before

    queue = await api_client.get("/api/correlation/review")
    assert queue.status_code == 200
    assert queue.json()["items"] == []


@pytest.mark.asyncio
async def test_leave_unattributed_is_valid_terminal_choice(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    activity, _device_a, _device_b = await _seed_ambiguous_activity(db_session)

    resolved = await api_client.post(
        f"/api/correlation/review/{activity.id}/resolve",
        json={"leave_unattributed": True},
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["status"] == "unattributed"
    assert body["needs_review"] is False
    assert body["device_id"] is None
    assert body["evidence"]["manual_resolution"]["decision"] == "leave_unattributed"

    await db_session.refresh(activity)
    assert activity.status == CorrelationStatus.UNATTRIBUTED
    assert activity.device_id is None
    assert activity.needs_review is False
    assert activity.evidence["manual_resolution"]["decision"] == "leave_unattributed"

    audits = list(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "correlation.resolve")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].after is not None
    assert audits[0].after["status"] == "unattributed"
    assert audits[0].after["needs_review"] is False
    assert audits[0].after["device_id"] is None

    queue = await api_client.get("/api/correlation/review")
    assert queue.status_code == 200
    assert queue.json()["items"] == []

    # Re-correlation must not overwrite the parent decision.
    query = (
        await db_session.execute(
            select(DnsQuery).where(DnsQuery.id == activity.dns_query_id)
        )
    ).scalar_one()
    await correlate_window(db_session, [query], threshold=Decimal("0.70"))
    await db_session.commit()
    await db_session.refresh(activity)
    assert activity.needs_review is False
    assert activity.status == CorrelationStatus.UNATTRIBUTED
    assert activity.evidence["manual_resolution"]["decision"] == "leave_unattributed"
