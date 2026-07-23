"""Parent finding feedback, audit trail, and suppression lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import settings
from app.db import get_session
from app.findings.engine import (
    DeviceContext,
    evaluate_and_persist,
    rule_unknown_device_online,
    upsert_finding,
)
from app.findings.feedback import (
    domain_pattern_from_evidence,
    status_for_classification,
    suppression_matching_key,
)
from app.identity.resolver import ClientObservation, resolve_observation
from app.main import app
from app.models.enums import FindingFeedbackClassification, FindingStatus
from app.models.findings import Finding, FindingFeedback, FindingSuppression
from app.models.health import AuditLog
from app.models.identity import Device


def _session_override(migrated_engine: AsyncEngine):
    factory = async_sessionmaker(
        bind=migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override():
        async with factory() as session:
            yield session

    return _override


async def _seed_unknown_device_finding(
    session: AsyncSession,
    *,
    now: datetime,
    mac: str = "aa:bb:cc:dd:ee:55",
) -> Finding:
    device = await resolve_observation(
        session,
        ClientObservation(
            observed_at=now,
            source="unifi_api",
            mac=mac,
            hostname="mystery-phone",
            ip="192.168.1.55",
        ),
    )
    device.is_unknown = True
    device.last_seen = now
    await session.flush()
    drafts = rule_unknown_device_online(
        [
            DeviceContext(
                device_id=device.id,
                display_name="mystery-phone",
                is_unknown=True,
                last_seen=now,
                person_id=None,
                person_name=None,
                is_online=True,
            )
        ],
        now=now,
    )
    row, _created = await upsert_finding(session, drafts[0])
    await session.commit()
    return row


def test_status_mapping_and_domain_pattern() -> None:
    assert (
        status_for_classification(FindingFeedbackClassification.ACKNOWLEDGE)
        == FindingStatus.ACKNOWLEDGED
    )
    assert (
        status_for_classification(FindingFeedbackClassification.IGNORE_ONCE)
        == FindingStatus.DISMISSED
    )
    assert (
        status_for_classification(FindingFeedbackClassification.SUPPRESS_SIMILAR)
        == FindingStatus.DISMISSED
    )
    assert (
        status_for_classification(FindingFeedbackClassification.RESOLVE)
        == FindingStatus.RESOLVED
    )
    assert domain_pattern_from_evidence({}) == "*"
    assert domain_pattern_from_evidence({"domains": ["Ads.Example.com."]}) == (
        "ads.example.com"
    )
    assert domain_pattern_from_evidence(
        {"domains": ["a.example.com", "b.example.com"]}
    ) == "*.example.com"
    key, pattern = suppression_matching_key(
        rule_id="unknown_device_online",
        device_id=uuid4(),
        person_id=None,
        evidence={},
    )
    assert pattern == "*"
    assert "unknown_device_online|device:" in key


@pytest.mark.asyncio
async def test_feedback_updates_status_and_audit(
    db_session: AsyncSession,
    migrated_engine: AsyncEngine,
) -> None:
    now = datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    finding = await _seed_unknown_device_finding(db_session, now=now)

    app.dependency_overrides[get_session] = _session_override(migrated_engine)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/findings/{finding.id}/feedback",
                json={"classification": "acknowledge"},
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["classification"] == "acknowledge"
            assert body["actor"] == settings.admin_username
            assert body["finding"]["status"] == "acknowledged"
            assert body["finding"]["id"] == str(finding.id)
            assert body["suppression_id"] is None

            listed = await client.get(
                "/api/findings",
                params={"status": "acknowledged"},
            )
            assert listed.status_code == 200
            assert any(i["id"] == str(finding.id) for i in listed.json()["items"])
    finally:
        app.dependency_overrides.pop(get_session, None)

    feedbacks = list(
        (
            await db_session.execute(
                select(FindingFeedback).where(FindingFeedback.finding_id == finding.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(feedbacks) == 1
    assert feedbacks[0].classification == FindingFeedbackClassification.ACKNOWLEDGE
    assert feedbacks[0].actor == settings.admin_username

    audits = list(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "finding.feedback")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].actor == settings.admin_username
    assert audits[0].entity_type == "finding"
    assert audits[0].entity_id == finding.id
    assert audits[0].before is not None
    assert audits[0].before["status"] == "open"
    assert audits[0].after is not None
    assert audits[0].after["status"] == "acknowledged"
    assert audits[0].after["classification"] == "acknowledge"


@pytest.mark.asyncio
async def test_ignore_once_dismisses_only_that_finding(
    db_session: AsyncSession,
    migrated_engine: AsyncEngine,
) -> None:
    now = datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    finding = await _seed_unknown_device_finding(db_session, now=now)
    finding_id = finding.id

    app.dependency_overrides[get_session] = _session_override(migrated_engine)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/findings/{finding_id}/feedback",
                json={"classification": "ignore_once"},
            )
            assert resp.status_code == 201
            assert resp.json()["finding"]["status"] == "dismissed"
            assert resp.json()["suppression_id"] is None

            got = await client.get(f"/api/findings/{finding_id}")
            assert got.status_code == 200
            assert got.json()["status"] == "dismissed"

            dismiss_only = await client.get(
                "/api/findings",
                params={"status": "dismissed"},
            )
            assert any(i["id"] == str(finding_id) for i in dismiss_only.json()["items"])

            suppressions = await client.get("/api/suppressions")
            assert suppressions.status_code == 200
            assert suppressions.json()["count"] == 0
    finally:
        app.dependency_overrides.pop(get_session, None)

    # Separate session avoids identity-map staleness from the seed session.
    factory = async_sessionmaker(
        bind=migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with factory() as verify:
        feedback = (
            await verify.execute(
                select(FindingFeedback).where(
                    FindingFeedback.finding_id == finding_id
                )
            )
        ).scalars().one()
        assert feedback.classification == FindingFeedbackClassification.IGNORE_ONCE
        assert (await verify.execute(select(FindingSuppression))).scalars().first() is None


@pytest.mark.asyncio
async def test_suppress_similar_stops_reappear_and_delete_restores(
    db_session: AsyncSession,
    migrated_engine: AsyncEngine,
) -> None:
    now = datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    finding = await _seed_unknown_device_finding(db_session, now=now)
    device_id = finding.device_id
    assert device_id is not None

    app.dependency_overrides[get_session] = _session_override(migrated_engine)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/findings/{finding.id}/feedback",
                json={"classification": "suppress_similar"},
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["finding"]["status"] == "dismissed"
            assert body["suppression_id"] is not None
            suppression_id = body["suppression_id"]

            listed = await client.get("/api/suppressions")
            assert listed.status_code == 200
            assert listed.json()["count"] == 1
            item = listed.json()["items"][0]
            assert item["id"] == suppression_id
            assert item["rule_id"] == "unknown_device_online"
            assert item["device_id"] == str(device_id)
            assert item["domain_pattern"] == "*"
            assert "unknown_device_online|device:" in item["matching_key"]

            suppress_audits = list(
                (
                    await db_session.execute(
                        select(AuditLog).where(AuditLog.action == "finding.suppress")
                    )
                )
                .scalars()
                .all()
            )
            assert len(suppress_audits) == 1

            # New hourly window → new fingerprint; suppression must skip it.
            later = now + timedelta(hours=2)
            dev_row = (
                await db_session.execute(select(Device).where(Device.id == device_id))
            ).scalars().one()
            dev_row.last_seen = later
            dev_row.is_unknown = True
            await db_session.commit()

            drafts = await evaluate_and_persist(
                db_session,
                now=later,
                persist=True,
            )
            await db_session.commit()
            assert not any(
                d.rule_id == "unknown_device_online" and d.device_id == device_id
                for d in drafts
            )
            open_unknown = list(
                (
                    await db_session.execute(
                        select(Finding).where(
                            Finding.rule_id == "unknown_device_online",
                            Finding.device_id == device_id,
                            Finding.status == FindingStatus.OPEN,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert open_unknown == []

            deleted = await client.delete(f"/api/suppressions/{suppression_id}")
            assert deleted.status_code == 204

            empty = await client.get("/api/suppressions")
            assert empty.status_code == 200
            assert empty.json()["count"] == 0

            unsuppress_audits = list(
                (
                    await db_session.execute(
                        select(AuditLog).where(AuditLog.action == "finding.unsuppress")
                    )
                )
                .scalars()
                .all()
            )
            assert len(unsuppress_audits) == 1

            # After deleting suppression, equivalent finding reappears.
            even_later = later + timedelta(hours=2)
            dev_row.last_seen = even_later
            await db_session.commit()
            drafts = await evaluate_and_persist(
                db_session,
                now=even_later,
                persist=True,
            )
            await db_session.commit()
            assert any(
                d.rule_id == "unknown_device_online" and d.device_id == device_id
                for d in drafts
            )
            reappeared = list(
                (
                    await db_session.execute(
                        select(Finding).where(
                            Finding.rule_id == "unknown_device_online",
                            Finding.device_id == device_id,
                            Finding.status == FindingStatus.OPEN,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(reappeared) >= 1
            assert reappeared[0].id != finding.id
    finally:
        app.dependency_overrides.pop(get_session, None)
