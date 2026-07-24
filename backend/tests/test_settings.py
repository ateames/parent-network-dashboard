"""Local settings thresholds and expected-activity schedules."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import settings
from app.db import get_session
from app.identity.resolver import ClientObservation, resolve_observation
from app.main import app
from app.models.health import AuditLog
from app.models.people import Person
from app.models.enums import PersonRole


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
async def test_thresholds_default_and_patch_audited(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    _ = db_session

    got = await api_client.get("/api/settings/thresholds")
    assert got.status_code == 200
    body = got.json()
    assert body["correlation_confidence_threshold"] == settings.correlation_confidence_threshold
    assert body["baseline_z_threshold"] == 2.0

    patched = await api_client.patch(
        "/api/settings/thresholds",
        json={
            "correlation_confidence_threshold": 0.85,
            "baseline_z_threshold": 2.5,
            "pihole_poll_interval_seconds": 120,
        },
    )
    assert patched.status_code == 200
    assert patched.json()["correlation_confidence_threshold"] == 0.85
    assert patched.json()["baseline_z_threshold"] == 2.5
    assert patched.json()["pihole_poll_interval_seconds"] == 120

    again = await api_client.get("/api/settings")
    assert again.status_code == 200
    assert again.json()["thresholds"]["correlation_confidence_threshold"] == 0.85

    audits = list(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "thresholds.update")
            )
        ).scalars()
    )
    assert len(audits) == 1
    assert audits[0].actor == settings.admin_username
    assert audits[0].entity_type == "app_thresholds"
    assert audits[0].after is not None
    assert audits[0].after["correlation_confidence_threshold"] == 0.85


@pytest.mark.asyncio
async def test_schedule_crud_audited(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    person = Person(name="Sam", role=PersonRole.CHILD, logic_version="person.v1")
    db_session.add(person)
    await db_session.commit()

    created = await api_client.post(
        "/api/settings/schedules",
        json={
            "person_id": str(person.id),
            "label": "School nights",
            "expected_hours_utc": [7, 8, 9, 16, 17, 18, 19, 20],
            "days_of_week": [0, 1, 2, 3, 4],
            "active": True,
        },
    )
    assert created.status_code == 201
    schedule = created.json()
    schedule_id = UUID(schedule["id"])
    assert schedule["person_id"] == str(person.id)
    assert schedule["expected_hours_utc"] == [7, 8, 9, 16, 17, 18, 19, 20]

    listed = await api_client.get("/api/settings/schedules")
    assert listed.status_code == 200
    assert len(listed.json()["schedules"]) == 1

    patched = await api_client.patch(
        f"/api/settings/schedules/{schedule_id}",
        json={"active": False, "expected_hours_utc": [8, 9, 10]},
    )
    assert patched.status_code == 200
    assert patched.json()["active"] is False
    assert patched.json()["expected_hours_utc"] == [8, 9, 10]

    deleted = await api_client.delete(f"/api/settings/schedules/{schedule_id}")
    assert deleted.status_code == 204

    actions = {
        row.action
        for row in (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "expected_activity_schedule"
                )
            )
        ).scalars()
    }
    assert actions == {"schedule.create", "schedule.update", "schedule.delete"}


@pytest.mark.asyncio
async def test_schedule_requires_exactly_one_subject(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    person = Person(name="Pat", role=PersonRole.CHILD, logic_version="person.v1")
    db_session.add(person)
    device = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=datetime.now(UTC),
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:99",
            unifi_client_id="client-99",
            hostname="tablet",
            ip="192.168.1.99",
        ),
    )
    await db_session.commit()

    both = await api_client.post(
        "/api/settings/schedules",
        json={
            "person_id": str(person.id),
            "device_id": str(device.id),
            "expected_hours_utc": [9, 10],
        },
    )
    assert both.status_code == 422

    neither = await api_client.post(
        "/api/settings/schedules",
        json={"expected_hours_utc": [9, 10]},
    )
    assert neither.status_code == 422
