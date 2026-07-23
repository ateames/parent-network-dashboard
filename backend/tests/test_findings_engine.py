"""Deterministic findings rules — craft fixtures fire; normal data stays silent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.activity.aggregate import ActivitySummary
from app.activity.baseline import compute_baseline, detect_deviations
from app.db import get_session
from app.findings.engine import (
    LOGIC_VERSION,
    ConnectionTransition,
    DeviceContext,
    DnsLookupEvent,
    DnsSubjectStats,
    SecuritySyslogEvent,
    evaluate_and_persist,
    evaluate_rules,
    rule_activity_outside_expected_hours,
    rule_blocked_query_burst,
    rule_connection_flapping,
    rule_dns_volume_increase,
    rule_new_domain_burst,
    rule_unifi_security_event,
    rule_unknown_device_online,
    upsert_finding,
)
from app.findings.phrasing import (
    assert_honest_dns_language,
    contains_viewing_claim,
    phrase_dns_lookup,
    subject_label,
)
from app.identity.resolver import ClientObservation, resolve_observation
from app.main import app
from app.models.enums import (
    DnsQueryStatus,
    FindingConfidence,
    FindingSeverity,
    FindingStatus,
    IngestBatchStatus,
    IngestSource,
    PersonRole,
)
from app.models.findings import Finding
from app.models.people import Person, PersonDevice
from app.models.raw import IngestBatch, RawUnifiSyslog


def _assert_finding_shape(draft) -> None:
    assert draft.evidence
    assert "rule_id" in draft.evidence
    assert draft.confidence in (
        FindingConfidence.LOW,
        FindingConfidence.MEDIUM,
        FindingConfidence.HIGH,
    )
    assert draft.severity in (
        FindingSeverity.INFO,
        FindingSeverity.LOW,
        FindingSeverity.MEDIUM,
        FindingSeverity.HIGH,
    )
    for text in (
        draft.title,
        draft.summary,
        draft.why_flagged,
        draft.recommended_action,
    ):
        assert not contains_viewing_claim(text)


def test_phrasing_never_claims_viewed_or_watched() -> None:
    ok = phrase_dns_lookup("ads.example", subject="Alex", blocked=True)
    assert "DNS lookup" in ok
    assert "viewed" not in ok.lower()
    assert "watched" not in ok.lower()
    assert_honest_dns_language(ok)

    with pytest.raises(ValueError, match="viewed"):
        assert_honest_dns_language("Alex viewed youtube.com")

    with pytest.raises(ValueError, match="watched"):
        assert_honest_dns_language("Child watched a stream")

    assert subject_label() == "unattributed"
    assert subject_label(person_name="Alex") == "Alex"


def test_unknown_device_online_fires_and_silent_when_known() -> None:
    now = datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    unknown = DeviceContext(
        device_id=uuid4(),
        display_name="mystery-phone",
        is_unknown=True,
        last_seen=now - timedelta(seconds=30),
        person_id=None,
        person_name=None,
        is_online=True,
    )
    known = DeviceContext(
        device_id=uuid4(),
        display_name="ipad",
        is_unknown=False,
        last_seen=now - timedelta(seconds=30),
        person_id=uuid4(),
        person_name="Alex",
        is_online=True,
    )
    offline_unknown = DeviceContext(
        device_id=uuid4(),
        display_name="old-tablet",
        is_unknown=True,
        last_seen=now - timedelta(hours=2),
        person_id=None,
        person_name=None,
        is_online=False,
    )

    fired = rule_unknown_device_online([unknown, known, offline_unknown], now=now)
    assert len(fired) == 1
    assert fired[0].rule_id == "unknown_device_online"
    _assert_finding_shape(fired[0])
    assert fired[0].device_id == unknown.device_id
    assert "is_unknown=true" in fired[0].why_flagged

    silent = rule_unknown_device_online([known, offline_unknown], now=now)
    assert silent == []


def test_blocked_query_burst_fires_and_silent_on_normal() -> None:
    device_id = uuid4()
    t0 = datetime(2024, 7, 23, 15, 0, tzinfo=UTC)
    burst = [
        DnsLookupEvent(
            queried_at=t0 + timedelta(seconds=i * 30),
            domain=f"ads{i}.tracker.example",
            status=DnsQueryStatus.BLOCKED,
            device_id=device_id,
            person_id=None,
            person_name=None,
            device_name="ipad",
        )
        for i in range(6)
    ]
    normal = [
        DnsLookupEvent(
            queried_at=t0 + timedelta(minutes=i),
            domain="example.com",
            status=DnsQueryStatus.ALLOWED,
            device_id=device_id,
            person_id=None,
            person_name=None,
            device_name="ipad",
        )
        for i in range(10)
    ] + [
        DnsLookupEvent(
            queried_at=t0 + timedelta(minutes=i),
            domain="ads.example",
            status=DnsQueryStatus.BLOCKED,
            device_id=device_id,
            person_id=None,
            person_name=None,
            device_name="ipad",
        )
        for i in range(2)
    ]

    fired = rule_blocked_query_burst(burst, now=t0 + timedelta(hours=1))
    assert len(fired) == 1
    _assert_finding_shape(fired[0])
    assert fired[0].evidence["blocked_count"] == 6
    assert "blocked DNS lookups" in fired[0].summary
    assert "viewed" not in fired[0].summary.lower()

    silent = rule_blocked_query_burst(normal, now=t0 + timedelta(hours=1))
    assert silent == []


def test_dns_volume_increase_fires_and_silent_near_baseline() -> None:
    device_id = uuid4()
    samples = [
        ActivitySummary(
            subject_type="device",
            subject_id=device_id,
            window_start=datetime(2024, 7, d, 0, tzinfo=UTC),
            window_end=datetime(2024, 7, d, 23, tzinfo=UTC),
            dns_query_volume=v,
            blocked_query_count=1,
            blocked_query_pct=5.0,
            unique_domain_count=5,
            new_domain_count=1,
            active_hour_count=3,
            active_hours_utc=(9, 10, 11),
            upload_bytes=None,
            download_bytes=None,
            connection_duration_seconds=None,
        )
        for d, v in enumerate([10, 12, 11, 13, 10, 12, 11], start=1)
    ]
    baseline = compute_baseline(
        samples,
        subject_type="device",
        subject_id=device_id,
        window="24h",
    )
    window_end = datetime(2024, 7, 23, 12, tzinfo=UTC)
    spike = DnsSubjectStats(
        device_id=device_id,
        person_id=None,
        person_name=None,
        device_name="ipad",
        window_start=window_end - timedelta(hours=24),
        window_end=window_end,
        volume=80,
        blocked_count=2,
        new_domain_count=1,
        new_domains=(),
        active_hours_utc=(10,),
        lookups=(),
    )
    live = ActivitySummary(
        subject_type="device",
        subject_id=device_id,
        window_start=spike.window_start,
        window_end=spike.window_end,
        dns_query_volume=80,
        blocked_query_count=2,
        blocked_query_pct=2.5,
        unique_domain_count=5,
        new_domain_count=1,
        active_hour_count=1,
        active_hours_utc=(10,),
        upload_bytes=None,
        download_bytes=None,
        connection_duration_seconds=None,
    )
    deviation = next(
        d
        for d in detect_deviations(live, baseline)
        if d.metric == "dns_query_volume"
    )
    fired = rule_dns_volume_increase(spike, baseline=baseline, deviation=deviation)
    assert fired is not None
    _assert_finding_shape(fired)
    assert fired.evidence["dns_query_volume"] == 80

    normal = DnsSubjectStats(
        device_id=device_id,
        person_id=None,
        person_name=None,
        device_name="ipad",
        window_start=spike.window_start,
        window_end=spike.window_end,
        volume=12,
        blocked_count=1,
        new_domain_count=1,
        new_domains=(),
        active_hours_utc=(10,),
        lookups=(),
    )
    assert rule_dns_volume_increase(normal, baseline=baseline, deviation=None) is None


def test_activity_outside_expected_hours_fires_and_silent_inside() -> None:
    device_id = uuid4()
    t0 = datetime(2024, 7, 23, 3, 0, tzinfo=UTC)  # 03:00 UTC — atypical
    outside_lookups = tuple(
        DnsLookupEvent(
            queried_at=t0 + timedelta(minutes=i),
            domain=f"host{i}.example",
            status=DnsQueryStatus.ALLOWED,
            device_id=device_id,
            person_id=None,
            person_name=None,
            device_name="ipad",
        )
        for i in range(4)
    )
    stats = DnsSubjectStats(
        device_id=device_id,
        person_id=None,
        person_name=None,
        device_name="ipad",
        window_start=t0 - timedelta(hours=1),
        window_end=t0 + timedelta(hours=1),
        volume=4,
        blocked_count=0,
        new_domain_count=4,
        new_domains=tuple(f"host{i}.example" for i in range(4)),
        active_hours_utc=(3,),
        lookups=outside_lookups,
    )
    fired = rule_activity_outside_expected_hours(
        stats,
        typical_hours_utc=(9, 10, 11, 12, 13, 14, 15, 16, 17, 18),
    )
    assert fired is not None
    _assert_finding_shape(fired)
    assert fired.evidence["outside_hours_utc"] == [3]

    day = datetime(2024, 7, 23, 10, 0, tzinfo=UTC)
    inside = DnsSubjectStats(
        device_id=device_id,
        person_id=None,
        person_name=None,
        device_name="ipad",
        window_start=day - timedelta(hours=1),
        window_end=day + timedelta(hours=1),
        volume=3,
        blocked_count=0,
        new_domain_count=1,
        new_domains=("example.com",),
        active_hours_utc=(10,),
        lookups=tuple(
            DnsLookupEvent(
                queried_at=day + timedelta(minutes=i),
                domain="example.com",
                status=DnsQueryStatus.ALLOWED,
                device_id=device_id,
                person_id=None,
                person_name=None,
                device_name="ipad",
            )
            for i in range(3)
        ),
    )
    assert (
        rule_activity_outside_expected_hours(
            inside,
            typical_hours_utc=(9, 10, 11),
        )
        is None
    )


def test_new_domain_burst_fires_and_silent_on_few_new() -> None:
    device_id = uuid4()
    window_end = datetime(2024, 7, 23, 12, tzinfo=UTC)
    burst = DnsSubjectStats(
        device_id=device_id,
        person_id=None,
        person_name=None,
        device_name="ipad",
        window_start=window_end - timedelta(hours=24),
        window_end=window_end,
        volume=20,
        blocked_count=0,
        new_domain_count=10,
        new_domains=tuple(f"new{i}.example" for i in range(10)),
        active_hours_utc=(12,),
        lookups=(),
    )
    fired = rule_new_domain_burst(burst, baseline=None)
    assert fired is not None
    _assert_finding_shape(fired)
    assert "newly seen domains" in fired.summary
    assert "viewed" not in fired.summary.lower()

    quiet = DnsSubjectStats(
        device_id=device_id,
        person_id=None,
        person_name=None,
        device_name="ipad",
        window_start=burst.window_start,
        window_end=burst.window_end,
        volume=5,
        blocked_count=0,
        new_domain_count=2,
        new_domains=("a.example", "b.example"),
        active_hours_utc=(12,),
        lookups=(),
    )
    assert rule_new_domain_burst(quiet, baseline=None) is None


def test_connection_flapping_fires_and_silent_on_stable() -> None:
    device_id = uuid4()
    t0 = datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    flap: list[ConnectionTransition] = []
    for i in range(4):
        flap.append(
            ConnectionTransition(
                at=t0 + timedelta(minutes=i * 2),
                kind="connect",
                mac="aa:bb:cc:dd:ee:01",
                device_id=device_id,
                person_id=None,
                person_name=None,
                device_name="ipad",
                event_name="EVT_WU_Connected",
                source="unifi_event",
            )
        )
        flap.append(
            ConnectionTransition(
                at=t0 + timedelta(minutes=i * 2 + 1),
                kind="disconnect",
                mac="aa:bb:cc:dd:ee:01",
                device_id=device_id,
                person_id=None,
                person_name=None,
                device_name="ipad",
                event_name="EVT_WU_Disconnected",
                source="unifi_event",
            )
        )
    fired = rule_connection_flapping(flap)
    assert len(fired) == 1
    _assert_finding_shape(fired[0])
    assert fired[0].evidence["transition_count"] >= 6

    stable = [
        ConnectionTransition(
            at=t0,
            kind="connect",
            mac="aa:bb:cc:dd:ee:02",
            device_id=uuid4(),
            person_id=None,
            person_name=None,
            device_name="laptop",
            event_name="EVT_WU_Connected",
            source="unifi_event",
        ),
        ConnectionTransition(
            at=t0 + timedelta(hours=3),
            kind="disconnect",
            mac="aa:bb:cc:dd:ee:02",
            device_id=uuid4(),
            person_id=None,
            person_name=None,
            device_name="laptop",
            event_name="EVT_WU_Disconnected",
            source="unifi_event",
        ),
    ]
    assert rule_connection_flapping(stable) == []


def test_unifi_security_event_fires_and_silent_on_monitoring() -> None:
    at = datetime(2024, 7, 23, 12, 2, tzinfo=UTC)
    security = SecuritySyslogEvent(
        at=at,
        event_name="Threat Detected and Blocked",
        category="Security",
        sub_category="Threat",
        msg="Threat Detected and Blocked",
        mac="aa:bb:cc:dd:ee:01",
        client_ip="192.168.1.50",
        device_id=None,
        person_id=None,
        person_name=None,
        device_name=None,
        raw_syslog_id=uuid4(),
        severity_raw=7,
    )
    monitoring = SecuritySyslogEvent(
        at=at,
        event_name="WiFi Client Connected",
        category="Monitoring",
        sub_category="WiFi",
        msg="connected",
        mac="aa:bb:cc:dd:ee:01",
        client_ip="192.168.1.50",
        device_id=None,
        person_id=None,
        person_name=None,
        device_name=None,
        raw_syslog_id=uuid4(),
    )
    fired = rule_unifi_security_event([security, monitoring])
    assert len(fired) == 1
    _assert_finding_shape(fired[0])
    assert fired[0].severity == FindingSeverity.HIGH
    assert fired[0].evidence["category"] == "Security"
    assert rule_unifi_security_event([monitoring]) == []


def test_evaluate_rules_requires_evidence_and_honest_language() -> None:
    now = datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    drafts = evaluate_rules(
        devices=[
            DeviceContext(
                device_id=uuid4(),
                display_name="ghost",
                is_unknown=True,
                last_seen=now,
                person_id=None,
                person_name=None,
                is_online=True,
            )
        ],
        security_events=[
            SecuritySyslogEvent(
                at=now,
                event_name="Threat",
                category="Security",
                sub_category="Threat",
                msg="blocked",
                mac=None,
                client_ip="198.51.100.9",
                device_id=None,
                person_id=None,
                person_name=None,
                device_name=None,
                raw_syslog_id=uuid4(),
            )
        ],
        now=now,
    )
    assert len(drafts) == 2
    for draft in drafts:
        _assert_finding_shape(draft)
        assert draft.logic_version == LOGIC_VERSION


@pytest.mark.asyncio
async def test_persist_and_list_filter_findings_api(
    db_session: AsyncSession,
    migrated_engine: AsyncEngine,
) -> None:
    now = datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    device = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=now,
            mac="aa:bb:cc:dd:ee:99",
            ip="192.168.1.99",
            hostname="mystery-phone",
            source="test",
        ),
    )
    device.is_unknown = True
    device.last_seen = now
    person = Person(logic_version="person.v1", name="Alex", role=PersonRole.CHILD)
    db_session.add(person)
    await db_session.flush()
    db_session.add(
        PersonDevice(
            logic_version="person.v1",
            person_id=person.id,
            device_id=device.id,
            assigned_by="test",
            active=True,
        )
    )
    batch = IngestBatch(
        source=IngestSource.UNIFI_SYSLOG,
        status=IngestBatchStatus.SUCCEEDED,
        record_count=1,
    )
    db_session.add(batch)
    await db_session.flush()
    db_session.add(
        RawUnifiSyslog(
            ingested_at=now,
            raw_line="threat",
            parsed={
                "category": "Security",
                "sub_category": "Threat",
                "event_name": "Threat Detected and Blocked",
                "msg": "Threat Detected and Blocked",
                "mac": "aa:bb:cc:dd:ee:99",
                "client_ip": "192.168.1.99",
                "severity": 7,
            },
            ingest_batch_id=batch.id,
        )
    )
    await db_session.commit()

    drafts = await evaluate_and_persist(
        db_session,
        now=now,
        persist=True,
    )
    await db_session.commit()
    assert any(d.rule_id == "unknown_device_online" for d in drafts)
    assert any(d.rule_id == "unifi_security_event" for d in drafts)

    rows = list((await db_session.execute(select(Finding))).scalars().all())
    assert rows
    for row in rows:
        assert row.evidence
        assert row.confidence is not None
        for text in (row.title, row.summary, row.why_flagged, row.recommended_action):
            assert not contains_viewing_claim(text)

    factory = async_sessionmaker(
        bind=migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            all_resp = await client.get("/api/findings")
            assert all_resp.status_code == 200
            body = all_resp.json()
            assert body["count"] >= 2
            finding_id = body["items"][0]["id"]

            high = await client.get("/api/findings", params={"severity": "high"})
            assert high.status_code == 200
            assert all(i["severity"] == "high" for i in high.json()["items"])

            by_device = await client.get(
                "/api/findings",
                params={"device": str(device.id)},
            )
            assert by_device.status_code == 200
            assert by_device.json()["count"] >= 1

            by_person = await client.get(
                "/api/findings",
                params={"person": str(person.id)},
            )
            assert by_person.status_code == 200

            open_only = await client.get(
                "/api/findings",
                params={"status": "open"},
            )
            assert open_only.status_code == 200
            assert all(i["status"] == "open" for i in open_only.json()["items"])

            one = await client.get(f"/api/findings/{finding_id}")
            assert one.status_code == 200
            assert one.json()["id"] == finding_id
            assert one.json()["evidence"]

            missing = await client.get(f"/api/findings/{uuid4()}")
            assert missing.status_code == 404
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_finding_draft_rejects_viewed_language() -> None:
    from app.findings.engine import FindingDraft

    with pytest.raises(ValueError, match="viewed"):
        FindingDraft(
            rule_id="test",
            severity=FindingSeverity.INFO,
            confidence=FindingConfidence.LOW,
            title="Bad",
            summary="Child viewed example.com",
            why_flagged="test",
            recommended_action="none",
            subject_label="unattributed",
            missing_info=(),
            evidence={"rule_id": "test"},
            device_id=None,
            person_id=None,
            fingerprint="x",
            occurred_at=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_upsert_does_not_reopen_dismissed(db_session: AsyncSession) -> None:
    now = datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    device = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=now,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:77",
            hostname="ghost",
            ip="192.168.1.77",
        ),
    )
    device.is_unknown = True
    device.last_seen = now
    await db_session.flush()
    drafts = rule_unknown_device_online(
        [
            DeviceContext(
                device_id=device.id,
                display_name="ghost",
                is_unknown=True,
                last_seen=now,
                person_id=None,
                person_name=None,
                is_online=True,
            )
        ],
        now=now,
    )
    row, created = await upsert_finding(db_session, drafts[0])
    assert created is True
    row.status = FindingStatus.DISMISSED
    await db_session.commit()

    again, created_again = await upsert_finding(db_session, drafts[0])
    assert created_again is False
    assert again.id == row.id
    assert again.status == FindingStatus.DISMISSED
