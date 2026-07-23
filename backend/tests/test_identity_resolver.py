"""Device identity resolver — durable matching, never IP-alone merges."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.identity.resolver import (
    LOGIC_VERSION,
    ClientObservation,
    resolve_observation,
)
from app.models.enums import IdentifierKind
from app.models.identity import Device, DeviceIdentifier, IpAssignment


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


@pytest.mark.asyncio
async def test_same_mac_different_ips_one_device_two_ip_history(
    db_session: AsyncSession,
) -> None:
    mac = "aa:bb:cc:dd:ee:10"
    first = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=datetime(2024, 7, 23, 12, 0, tzinfo=UTC),
            source="unifi_api",
            first_seen=datetime(2024, 1, 1, tzinfo=UTC),
            mac=mac,
            unifi_client_id="client-10",
            hostname="tablet",
            ip="192.168.1.10",
        ),
    )
    second = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=datetime(2024, 7, 23, 13, 0, tzinfo=UTC),
            source="unifi_api",
            first_seen=datetime(2024, 1, 1, tzinfo=UTC),
            mac=mac,
            unifi_client_id="client-10",
            hostname="tablet",
            ip="192.168.1.99",
        ),
    )
    assert first.id == second.id
    device = await db_session.get(Device, first.id)
    assert device is not None
    assert device.is_unknown is False
    assert device.logic_version == LOGIC_VERSION

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
    assert history[0].ip == "192.168.1.10"
    assert history[0].observed_to is not None
    assert history[1].ip == "192.168.1.99"
    assert history[1].observed_to is None


@pytest.mark.asyncio
async def test_ip_only_observation_does_not_merge_into_existing_device(
    db_session: AsyncSession,
) -> None:
    known = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=datetime(2024, 7, 23, 12, 0, tzinfo=UTC),
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:20",
            unifi_client_id="client-20",
            hostname="laptop",
            ip="192.168.1.20",
        ),
    )
    orphan = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=datetime(2024, 7, 23, 12, 5, tzinfo=UTC),
            source="pihole_api",
            ip="192.168.1.20",
        ),
    )
    assert orphan.id != known.id

    mac_rows = list(
        (
            await db_session.execute(
                select(DeviceIdentifier).where(
                    DeviceIdentifier.kind == IdentifierKind.MAC,
                    DeviceIdentifier.value == "aa:bb:cc:dd:ee:20",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(mac_rows) == 1
    assert mac_rows[0].device_id == known.id


@pytest.mark.asyncio
async def test_unknown_devices_flagged_without_strong_identifier(
    db_session: AsyncSession,
) -> None:
    named = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=datetime(2024, 7, 23, 12, 0, tzinfo=UTC),
            source="pihole_api",
            pihole_client="chromecast",
            ip="192.168.1.40",
        ),
    )
    ip_only = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=datetime(2024, 7, 23, 12, 1, tzinfo=UTC),
            source="pihole_api",
            ip="192.168.1.41",
        ),
    )
    known = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=datetime(2024, 7, 23, 12, 2, tzinfo=UTC),
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:30",
            ip="192.168.1.30",
        ),
    )
    assert named.is_unknown is True
    assert ip_only.is_unknown is True
    assert known.is_unknown is False

    kinds = {
        row.kind
        for row in (
            await db_session.execute(
                select(DeviceIdentifier).where(DeviceIdentifier.device_id == named.id)
            )
        )
        .scalars()
        .all()
    }
    assert IdentifierKind.PIHOLE_CLIENT in kinds
    assert IdentifierKind.MAC not in kinds
    assert IdentifierKind.UNIFI_CLIENT_ID not in kinds
