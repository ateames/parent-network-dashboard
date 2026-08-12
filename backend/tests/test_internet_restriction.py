"""Device internet restriction API + expiry worker coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import get_session
from app.identity.resolver import ClientObservation, resolve_observation
from app.ingest.unifi import UnifiClientError, UnifiControlUnsupportedError
from app.main import app
from app.models.enums import RestrictionStatus
from app.models.restrictions import DeviceRestriction
from app.restrictions import lift_expired_restrictions


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


async def _seed_device(db_session: AsyncSession, mac: str = "aa:bb:cc:dd:ee:60"):
    return await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=datetime.now(UTC),
            source="unifi_api",
            mac=mac,
            unifi_client_id=f"client-{mac[-2:]}",
            hostname="tablet",
            ip="192.168.1.90",
        ),
    )


def _mock_unifi_client(**methods: Any) -> Any:
    client = AsyncMock()
    client.block_client = methods.get("block_client", AsyncMock())
    client.unblock_client = methods.get("unblock_client", AsyncMock())
    client.aclose = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_create_timed_and_indefinite_restriction(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    device = await _seed_device(db_session)
    await db_session.commit()

    mock = _mock_unifi_client()
    with patch("app.restrictions.UnifiClient", return_value=mock):
        timed = await api_client.post(
            f"/api/devices/{device.id}/internet-restriction",
            json={"minutes": 30},
        )
    assert timed.status_code == 201
    body = timed.json()
    assert body["internet_restriction"]["status"] == "active"
    assert body["internet_restriction"]["minutes"] == 30
    assert body["internet_restriction"]["expires_at"] is not None
    assert body["internet_restriction"]["mac"] == "aa:bb:cc:dd:ee:60"
    mock.block_client.assert_awaited()

    listed = await api_client.get("/api/devices")
    assert listed.status_code == 200
    match = next(d for d in listed.json()["devices"] if d["id"] == str(device.id))
    assert match["internet_restriction"]["status"] == "active"

    mock2 = _mock_unifi_client()
    with patch("app.restrictions.UnifiClient", return_value=mock2):
        indefinite = await api_client.post(
            f"/api/devices/{device.id}/internet-restriction",
            json={},
        )
    assert indefinite.status_code == 201
    assert indefinite.json()["internet_restriction"]["minutes"] is None
    assert indefinite.json()["internet_restriction"]["expires_at"] is None


@pytest.mark.asyncio
async def test_delete_reenable_internet(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    device = await _seed_device(db_session, mac="aa:bb:cc:dd:ee:61")
    await db_session.commit()

    mock = _mock_unifi_client()
    with patch("app.restrictions.UnifiClient", return_value=mock):
        created = await api_client.post(
            f"/api/devices/{device.id}/internet-restriction",
            json={"minutes": 10},
        )
        assert created.status_code == 201
        deleted = await api_client.delete(
            f"/api/devices/{device.id}/internet-restriction",
        )
    assert deleted.status_code == 200
    assert deleted.json()["internet_restriction"] is None
    mock.unblock_client.assert_awaited()


@pytest.mark.asyncio
async def test_session_auth_required_returns_409(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    device = await _seed_device(db_session, mac="aa:bb:cc:dd:ee:62")
    await db_session.commit()

    mock = _mock_unifi_client(
        block_client=AsyncMock(
            side_effect=UnifiControlUnsupportedError("needs session")
        )
    )
    with patch("app.restrictions.UnifiClient", return_value=mock):
        response = await api_client.post(
            f"/api/devices/{device.id}/internet-restriction",
            json={"minutes": 5},
        )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "session_auth_required"
    # Fail closed: no active row persisted.
    result = await db_session.execute(
        select(DeviceRestriction).where(DeviceRestriction.device_id == device.id)
    )
    assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_block_failure_does_not_persist(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    device = await _seed_device(db_session, mac="aa:bb:cc:dd:ee:63")
    await db_session.commit()

    mock = _mock_unifi_client(
        block_client=AsyncMock(side_effect=UnifiClientError("controller down"))
    )
    with patch("app.restrictions.UnifiClient", return_value=mock):
        response = await api_client.post(
            f"/api/devices/{device.id}/internet-restriction",
            json={"minutes": 5},
        )
    assert response.status_code == 502
    result = await db_session.execute(
        select(DeviceRestriction).where(DeviceRestriction.device_id == device.id)
    )
    assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_lift_expired_restrictions_unblocks(
    db_session: AsyncSession,
) -> None:
    device = await _seed_device(db_session, mac="aa:bb:cc:dd:ee:64")
    past = datetime.now(UTC) - timedelta(minutes=1)
    row = DeviceRestriction(
        device_id=device.id,
        mac="aa:bb:cc:dd:ee:64",
        status=RestrictionStatus.ACTIVE,
        minutes=5,
        expires_at=past,
        created_at=past - timedelta(minutes=5),
    )
    db_session.add(row)
    await db_session.commit()

    mock = _mock_unifi_client()
    with patch("app.restrictions.UnifiClient", return_value=mock):
        lifted = await lift_expired_restrictions(db_session)
        await db_session.commit()

    assert lifted == 1
    mock.unblock_client.assert_awaited_once()
    await db_session.refresh(row)
    assert row.status == RestrictionStatus.LIFTED
    assert row.lifted_at is not None


@pytest.mark.asyncio
async def test_lift_expired_keeps_active_on_unblock_failure(
    db_session: AsyncSession,
) -> None:
    device = await _seed_device(db_session, mac="aa:bb:cc:dd:ee:65")
    past = datetime.now(UTC) - timedelta(minutes=1)
    row = DeviceRestriction(
        device_id=device.id,
        mac="aa:bb:cc:dd:ee:65",
        status=RestrictionStatus.ACTIVE,
        minutes=5,
        expires_at=past,
        created_at=past - timedelta(minutes=5),
    )
    db_session.add(row)
    await db_session.commit()

    mock = _mock_unifi_client(
        unblock_client=AsyncMock(side_effect=UnifiClientError("still failing"))
    )
    with patch("app.restrictions.UnifiClient", return_value=mock):
        lifted = await lift_expired_restrictions(db_session)
        await db_session.commit()

    assert lifted == 0
    await db_session.refresh(row)
    assert row.status == RestrictionStatus.ACTIVE
    assert row.error is not None
    assert "still failing" in row.error
