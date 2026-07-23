"""Durable device identity resolution (offline; no live Pi-hole/UniFi)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import get_session
from app.identity.resolver import (
    LOGIC_VERSION,
    ClientObservation,
    resolve_observation,
)
from app.main import app
from app.models.enums import IdentifierKind, PersonRole
from app.models.identity import Device, DeviceIdentifier, IpAssignment
from app.models.people import Person, PersonDevice


@pytest.fixture
async def api_client(
    migrated_engine: AsyncEngine,
    db_session: AsyncSession,
) -> AsyncClient:
    # Ensure truncate from db_session runs before API requests share the engine.
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
async def test_same_mac_different_ips_one_device_two_ip_rows(
    db_session: AsyncSession,
) -> None:
    mac = "aa:bb:cc:dd:ee:10"
    t0 = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)

    first = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t0,
            source="unifi_api",
            first_seen=t0,
            mac=mac,
            unifi_client_id="client-10",
            hostname="tablet",
            ip="192.168.1.40",
        ),
    )
    second = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t1,
            source="unifi_api",
            first_seen=t0,
            mac=mac,
            unifi_client_id="client-10",
            hostname="tablet",
            ip="192.168.1.99",
        ),
    )
    await db_session.commit()

    assert first.id == second.id
    devices = list((await db_session.execute(select(Device))).scalars().all())
    assert len(devices) == 1
    assert devices[0].is_unknown is False
    assert devices[0].logic_version == LOGIC_VERSION

    history = list(
        (
            await db_session.execute(
                select(IpAssignment)
                .where(IpAssignment.device_id == first.id)
                .order_by(IpAssignment.observed_from)
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 2
    assert history[0].ip == "192.168.1.40"
    assert history[0].observed_to == t1
    assert history[1].ip == "192.168.1.99"
    assert history[1].observed_to is None


@pytest.mark.asyncio
async def test_ip_only_observation_does_not_merge_into_existing_device(
    db_session: AsyncSession,
) -> None:
    t0 = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    known = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t0,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:20",
            unifi_client_id="client-20",
            ip="192.168.1.50",
        ),
    )
    orphan = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t0 + timedelta(minutes=5),
            source="pihole_api",
            ip="192.168.1.50",
            pihole_client="mystery-host",
        ),
    )
    await db_session.commit()

    assert orphan.id != known.id
    devices = list((await db_session.execute(select(Device))).scalars().all())
    assert len(devices) == 2

    # Shared IP must not collapse identities; each keeps its own assignment row.
    assignments = list((await db_session.execute(select(IpAssignment))).scalars().all())
    assert len(assignments) == 2
    assert {a.device_id for a in assignments} == {known.id, orphan.id}


@pytest.mark.asyncio
async def test_unknown_devices_flagged_without_strong_identifier(
    db_session: AsyncSession,
) -> None:
    t0 = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    unknown = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t0,
            source="pihole_api",
            ip="192.168.1.77",
            hostname="guest-laptop",
            pihole_client="guest-laptop",
        ),
    )
    known = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t0,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:30",
            ip="192.168.1.78",
        ),
    )
    await db_session.commit()

    assert unknown.is_unknown is True
    assert known.is_unknown is False

    kinds = {
        i.kind
        for i in (
            await db_session.execute(
                select(DeviceIdentifier).where(DeviceIdentifier.device_id == unknown.id)
            )
        )
        .scalars()
        .all()
    }
    assert IdentifierKind.HOSTNAME in kinds
    assert IdentifierKind.PIHOLE_CLIENT in kinds
    assert IdentifierKind.IP in kinds
    assert IdentifierKind.MAC not in kinds


@pytest.mark.asyncio
async def test_devices_api_list_detail_and_patch(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    t0 = datetime.now(UTC)
    device = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t0,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:40",
            unifi_client_id="client-40",
            hostname="phone",
            ip="192.168.1.60",
        ),
    )
    person = Person(
        logic_version="person.v1",
        name="Alex",
        role=PersonRole.CHILD,
    )
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
    # Unassigned unknown device for filters.
    await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=t0 - timedelta(hours=2),
            source="pihole_api",
            ip="192.168.1.200",
        ),
    )
    await db_session.commit()

    listed = await api_client.get("/api/devices")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body["devices"]) == 2

    unknown_only = await api_client.get("/api/devices", params={"unknown": True})
    assert unknown_only.status_code == 200
    assert len(unknown_only.json()["devices"]) == 1
    assert unknown_only.json()["devices"][0]["is_unknown"] is True

    unassigned = await api_client.get("/api/devices", params={"unassigned": True})
    assert unassigned.status_code == 200
    assert len(unassigned.json()["devices"]) == 1

    online = await api_client.get("/api/devices", params={"online": True})
    assert online.status_code == 200
    assert any(d["id"] == str(device.id) for d in online.json()["devices"])

    detail = await api_client.get(f"/api/devices/{device.id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["id"] == str(device.id)
    assert detail_body["assigned_person"]["name"] == "Alex"
    assert detail_body["current_ip"] == "192.168.1.60"
    assert any(i["kind"] == "mac" for i in detail_body["identifiers"])
    assert len(detail_body["ip_history"]) == 1

    patched = await api_client.patch(
        f"/api/devices/{device.id}",
        json={"display_name": "Alex Phone", "notes": "school device"},
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Alex Phone"
    assert patched.json()["notes"] == "school device"

    missing = await api_client.get(f"/api/devices/{uuid4()}")
    assert missing.status_code == 404
