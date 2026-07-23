"""Household people CRUD and manual device assignment."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import settings
from app.db import get_session
from app.identity.resolver import ClientObservation, resolve_observation
from app.main import app
from app.models.health import AuditLog
from app.models.people import PersonDevice


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


async def _seed_device(db_session: AsyncSession, mac: str = "aa:bb:cc:dd:ee:50"):
    return await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=datetime.now(UTC),
            source="unifi_api",
            mac=mac,
            unifi_client_id=f"client-{mac[-2:]}",
            hostname="phone",
            ip="192.168.1.80",
        ),
    )


@pytest.mark.asyncio
async def test_people_crud(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    _ = db_session

    created = await api_client.post(
        "/api/people",
        json={"name": "Alex", "role": "child", "notes": "teen"},
    )
    assert created.status_code == 201
    person = created.json()
    assert person["name"] == "Alex"
    assert person["role"] == "child"
    assert person["notes"] == "teen"
    assert person["logic_version"] == "person.v1"
    assert person["devices"] == []
    person_id = person["id"]

    listed = await api_client.get("/api/people")
    assert listed.status_code == 200
    assert len(listed.json()["people"]) == 1

    detail = await api_client.get(f"/api/people/{person_id}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Alex"

    patched = await api_client.patch(
        f"/api/people/{person_id}",
        json={"name": "Alexandra", "role": "other"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Alexandra"
    assert patched.json()["role"] == "other"

    deleted = await api_client.delete(f"/api/people/{person_id}")
    assert deleted.status_code == 204

    missing = await api_client.get(f"/api/people/{person_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_assign_unassign_device_writes_audit_and_device_detail(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    device = await _seed_device(db_session)
    await db_session.commit()

    created = await api_client.post(
        "/api/people",
        json={"name": "Alex", "role": "child"},
    )
    assert created.status_code == 201
    person_id = created.json()["id"]

    assigned = await api_client.post(
        f"/api/people/{person_id}/devices",
        json={"device_id": str(device.id)},
    )
    assert assigned.status_code == 201
    link = assigned.json()
    assert link["person_id"] == person_id
    assert link["device_id"] == str(device.id)
    assert link["active"] is True
    assert link["assigned_by"] == settings.admin_username

    person_detail = await api_client.get(f"/api/people/{person_id}")
    assert person_detail.status_code == 200
    assert len(person_detail.json()["devices"]) == 1
    assert person_detail.json()["devices"][0]["id"] == str(device.id)

    device_detail = await api_client.get(f"/api/devices/{device.id}")
    assert device_detail.status_code == 200
    assert device_detail.json()["assigned_person"]["id"] == person_id
    assert device_detail.json()["assigned_person"]["name"] == "Alex"

    audits = list(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "device.assign")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].actor == settings.admin_username
    assert audits[0].entity_type == "person_device"
    assert audits[0].after is not None
    assert audits[0].after["device_id"] == str(device.id)
    assert audits[0].after["person_id"] == person_id

    unassigned = await api_client.delete(
        f"/api/people/{person_id}/devices/{device.id}"
    )
    assert unassigned.status_code == 204

    device_detail = await api_client.get(f"/api/devices/{device.id}")
    assert device_detail.status_code == 200
    assert device_detail.json()["assigned_person"] is None

    person_detail = await api_client.get(f"/api/people/{person_id}")
    assert person_detail.json()["devices"] == []

    unassign_audits = list(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "device.unassign")
            )
        )
        .scalars()
        .all()
    )
    assert len(unassign_audits) == 1
    assert unassign_audits[0].before is not None
    assert unassign_audits[0].before["active"] is True
    assert unassign_audits[0].after is not None
    assert unassign_audits[0].after["active"] is False

    links = list(
        (
            await db_session.execute(
                select(PersonDevice).where(PersonDevice.device_id == device.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(links) == 1
    assert links[0].active is False


@pytest.mark.asyncio
async def test_reassignment_deactivates_prior_link_and_audits(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    device = await _seed_device(db_session, mac="aa:bb:cc:dd:ee:51")
    await db_session.commit()

    first = await api_client.post(
        "/api/people",
        json={"name": "Alex", "role": "child"},
    )
    second = await api_client.post(
        "/api/people",
        json={"name": "Jordan", "role": "parent"},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    first_id = first.json()["id"]
    second_id = second.json()["id"]

    assign_first = await api_client.post(
        f"/api/people/{first_id}/devices",
        json={"device_id": str(device.id)},
    )
    assert assign_first.status_code == 201

    assign_second = await api_client.post(
        f"/api/people/{second_id}/devices",
        json={"device_id": str(device.id)},
    )
    assert assign_second.status_code == 201
    assert assign_second.json()["person_id"] == second_id

    links = list(
        (
            await db_session.execute(
                select(PersonDevice).where(PersonDevice.device_id == device.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(links) == 2
    by_person = {link.person_id: link for link in links}
    assert by_person[UUID(first_id)].active is False
    assert by_person[UUID(second_id)].active is True
    assert sum(1 for link in links if link.active) == 1

    device_detail = await api_client.get(f"/api/devices/{device.id}")
    assert device_detail.json()["assigned_person"]["id"] == second_id
    assert device_detail.json()["assigned_person"]["name"] == "Jordan"

    first_person = await api_client.get(f"/api/people/{first_id}")
    second_person = await api_client.get(f"/api/people/{second_id}")
    assert first_person.json()["devices"] == []
    assert len(second_person.json()["devices"]) == 1

    unassign_audits = list(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "device.unassign")
            )
        )
        .scalars()
        .all()
    )
    assert len(unassign_audits) == 1
    assert unassign_audits[0].after is not None
    assert unassign_audits[0].after["reason"] == "reassigned"

    assign_audits = list(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "device.assign")
            )
        )
        .scalars()
        .all()
    )
    assert len(assign_audits) == 2


@pytest.mark.asyncio
async def test_assign_missing_person_or_device_returns_404(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    device = await _seed_device(db_session, mac="aa:bb:cc:dd:ee:52")
    await db_session.commit()

    created = await api_client.post(
        "/api/people",
        json={"name": "Alex", "role": "child"},
    )
    person_id = created.json()["id"]

    missing_device = await api_client.post(
        f"/api/people/{person_id}/devices",
        json={"device_id": str(uuid4())},
    )
    assert missing_device.status_code == 404

    missing_person = await api_client.post(
        f"/api/people/{uuid4()}/devices",
        json={"device_id": str(device.id)},
    )
    assert missing_person.status_code == 404

    missing_unassign = await api_client.delete(
        f"/api/people/{person_id}/devices/{device.id}"
    )
    assert missing_unassign.status_code == 404
