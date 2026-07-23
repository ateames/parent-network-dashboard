"""Time-aware DNS → device correlation (offline; no live Pi-hole/UniFi)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.correlate.engine import (
    LOGIC_VERSION,
    ConflictRecord,
    EvidenceMatch,
    combine_confidence,
    correlate_window,
    decide_attribution,
)
from app.identity.resolver import ClientObservation, resolve_observation
from app.models.dns import DnsActivity, DnsQuery
from app.models.enums import (
    CorrelationStatus,
    DnsQueryStatus,
    IngestBatchStatus,
    IngestSource,
)
from app.models.identity import IpAssignment
from app.models.raw import IngestBatch, RawPiholeEvent


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


def test_combine_confidence_boosts_agreeing_signals() -> None:
    device = uuid4()
    ip = EvidenceMatch(
        kind="ip_assignment",
        device_id=device,
        weight=Decimal("0.8000"),
    )
    client = EvidenceMatch(
        kind="pihole_client",
        device_id=device,
        weight=Decimal("0.6000"),
    )
    score = combine_confidence([ip, client])
    assert score >= Decimal("0.9000")
    assert score <= Decimal("0.9900")


def test_decide_never_picks_among_two_devices() -> None:
    a = uuid4()
    b = uuid4()
    qid = uuid4()
    at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    decision = decide_attribution(
        dns_query_id=qid,
        queried_at=at,
        matches=[
            EvidenceMatch(
                kind="ip_assignment",
                device_id=a,
                weight=Decimal("0.8000"),
            ),
            EvidenceMatch(
                kind="pihole_client",
                device_id=b,
                weight=Decimal("0.6000"),
            ),
        ],
        conflicts=[],
        threshold=Decimal("0.7000"),
    )
    assert decision.device_id is None
    assert decision.status == CorrelationStatus.AMBIGUOUS
    assert decision.needs_review is True
    assert any(c.reason == "multiple_candidate_devices" for c in decision.conflicts)


def test_decide_below_threshold_stays_unattributed() -> None:
    device = uuid4()
    qid = uuid4()
    at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    decision = decide_attribution(
        dns_query_id=qid,
        queried_at=at,
        matches=[
            EvidenceMatch(
                kind="hostname",
                device_id=device,
                weight=Decimal("0.5500"),
            )
        ],
        conflicts=[],
        threshold=Decimal("0.7000"),
    )
    assert decision.device_id is None
    assert decision.status == CorrelationStatus.UNATTRIBUTED
    assert decision.needs_review is True
    assert decision.confidence == Decimal("0.5500")


def test_decide_with_prior_conflict_is_ambiguous() -> None:
    device = uuid4()
    qid = uuid4()
    at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    decision = decide_attribution(
        dns_query_id=qid,
        queried_at=at,
        matches=[
            EvidenceMatch(
                kind="ip_assignment",
                device_id=device,
                weight=Decimal("0.8000"),
            )
        ],
        conflicts=[
            ConflictRecord(
                reason="ip_reassigned_in_window",
                detail={"ip": "192.168.1.50"},
            )
        ],
        threshold=Decimal("0.7000"),
    )
    assert decision.device_id is None
    assert decision.status == CorrelationStatus.AMBIGUOUS


@pytest.mark.asyncio
async def test_clean_case_attributes_with_high_confidence(
    db_session: AsyncSession,
) -> None:
    t0 = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    device = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t0,
            source="unifi_api",
            first_seen=t0 - timedelta(days=1),
            mac="aa:bb:cc:dd:ee:50",
            unifi_client_id="client-50",
            hostname="ipad-child",
            pihole_client="ipad-child",
            ip="192.168.1.50",
        ),
    )
    query = await _seed_dns_query(
        db_session,
        queried_at=t0 + timedelta(minutes=5),
        client_identifier="ipad-child",
        client_ip="192.168.1.50",
    )
    await db_session.commit()

    rows = await correlate_window(db_session, [query], threshold=Decimal("0.70"))
    await db_session.commit()

    assert len(rows) == 1
    row = rows[0]
    assert row.logic_version == LOGIC_VERSION
    assert row.device_id == device.id
    assert row.status == CorrelationStatus.ATTRIBUTED
    assert row.needs_review is False
    assert row.confidence >= Decimal("0.9000")
    assert row.evidence["matches"]
    assert row.conflicts["items"] == []

    stored = list((await db_session.execute(select(DnsActivity))).scalars().all())
    assert len(stored) == 1
    assert stored[0].device_id == device.id


@pytest.mark.asyncio
async def test_ip_reassigned_in_window_is_ambiguous_not_wrong_device(
    db_session: AsyncSession,
) -> None:
    t0 = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    t_reassign = t0 + timedelta(minutes=30)
    t1 = t0 + timedelta(hours=1)

    device_a = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t0,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:60",
            unifi_client_id="client-60",
            hostname="phone-a",
            ip="192.168.1.60",
        ),
    )
    # Same IP moves to device B mid-window.
    await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t_reassign,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:61",
            unifi_client_id="client-61",
            hostname="phone-b",
            ip="192.168.1.60",
        ),
    )
    # Close device A's open IP assignment at reassignment time (resolver only
    # closes assignments on the same device).
    a_open = (
        await db_session.execute(
            select(IpAssignment).where(
                IpAssignment.device_id == device_a.id,
                IpAssignment.observed_to.is_(None),
            )
        )
    ).scalars().first()
    assert a_open is not None
    a_open.observed_to = t_reassign

    query_before = await _seed_dns_query(
        db_session,
        queried_at=t0 + timedelta(minutes=5),
        client_identifier="192.168.1.60",
        client_ip="192.168.1.60",
        domain="before.example",
    )
    query_after = await _seed_dns_query(
        db_session,
        queried_at=t1,
        client_identifier="192.168.1.60",
        client_ip="192.168.1.60",
        domain="after.example",
    )
    await db_session.commit()

    rows = await correlate_window(
        db_session,
        [query_before, query_after],
        threshold=Decimal("0.70"),
    )
    await db_session.commit()

    assert len(rows) == 2
    for row in rows:
        assert row.device_id is None
        assert row.status == CorrelationStatus.AMBIGUOUS
        assert row.needs_review is True
        reasons = {c["reason"] for c in row.conflicts["items"]}
        assert "ip_reassigned_in_window" in reasons


@pytest.mark.asyncio
async def test_two_candidate_devices_attributes_neither(
    db_session: AsyncSession,
) -> None:
    t0 = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

    # Device A owns the IP at query time (UniFi).
    device_a = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t0,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:70",
            unifi_client_id="client-70",
            hostname="laptop-a",
            ip="192.168.1.70",
        ),
    )
    # Device B separately claims the same pihole_client name (no shared MAC).
    device_b = await resolve_observation(
        db_session,
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
        db_session,
        queried_at=t0 + timedelta(minutes=1),
        client_identifier="shared-name",
        client_ip="192.168.1.70",
    )
    await db_session.commit()

    rows = await correlate_window(db_session, [query], threshold=Decimal("0.70"))
    await db_session.commit()

    assert len(rows) == 1
    row = rows[0]
    assert row.device_id is None
    assert row.status == CorrelationStatus.AMBIGUOUS
    assert row.needs_review is True
    conflict = next(
        c for c in row.conflicts["items"] if c["reason"] == "multiple_candidate_devices"
    )
    assert set(conflict["device_ids"]) == {str(device_a.id), str(device_b.id)}
    match_devices = {m["device_id"] for m in row.evidence["matches"]}
    assert match_devices == {str(device_a.id), str(device_b.id)}
