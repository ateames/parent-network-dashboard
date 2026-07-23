"""Device identity API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import get_session
from app.identity.resolver import ClientObservation, resolve_observation
from app.main import app
from app.models.enums import PersonRole
from app.models.people import Person, PersonDevice


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
async def api_client(db_session: AsyncSession) -> AsyncClient:
    async def _override_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_and_patch_devices(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    online_device = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=now,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:50",
            hostname="phone",
            ip="192.168.1.50",
        ),
    )
    unknown_device = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=now - timedelta(hours=2),
            source="pihole_api",
            pihole_client="mystery",
            ip="192.168.1.60",
        ),
    )
    person = Person(
        logic_version="test",
        name="Alex",
        role=PersonRole.CHILD,
    )
    db_session.add(person)
    await db_session.flush()
    db_session.add(
        PersonDevice(
            logic_version="test",
            person_id=person.id,
            device_id=online_device.id,
            assigned_by="test",
            active=True,
        )
    )
    await db_session.flush()

    listed = await api_client.get("/api/devices")
    assert listed.status_code == 200
    listed_ids = {row["id"] for row in listed.json()["devices"]}
    assert str(online_device.id) in listed_ids
    assert str(unknown_device.id) in listed_ids

    unknown_only = await api_client.get("/api/devices", params={"unknown": True})
    assert unknown_only.status_code == 200
    unknown_ids = {row["id"] for row in unknown_only.json()["devices"]}
    assert str(unknown_device.id) in unknown_ids
    assert str(online_device.id) not in unknown_ids

    unassigned = await api_client.get("/api/devices", params={"unassigned": True})
    assert unassigned.status_code == 200
    unassigned_ids = {row["id"] for row in unassigned.json()["devices"]}
    assert str(unknown_device.id) in unassigned_ids
    assert str(online_device.id) not in unassigned_ids

    online_only = await api_client.get("/api/devices", params={"online": True})
    assert online_only.status_code == 200
    online_ids = {row["id"] for row in online_only.json()["devices"]}
    assert str(online_device.id) in online_ids
    assert str(unknown_device.id) not in online_ids

    detail = await api_client.get(f"/api/devices/{online_device.id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["assigned_person"]["name"] == "Alex"
    assert any(i["kind"] == "mac" for i in detail_body["identifiers"])
    assert len(detail_body["ip_history"]) == 1

    patched = await api_client.patch(
        f"/api/devices/{online_device.id}",
        json={"display_name": "Alex Phone", "notes": "kitchen"},
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Alex Phone"
    assert patched.json()["notes"] == "kitchen"

    missing = await api_client.get(f"/api/devices/{uuid4()}")
    assert missing.status_code == 404
