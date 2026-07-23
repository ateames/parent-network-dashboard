"""Offline UniFi ingest via fixture replay (no live controller)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.health.source_health import get_source_health
from app.ingest.unifi import (
    LOGIC_VERSION,
    NormalizedClient,
    normalize_client,
    normalize_mac,
    replay_fixture,
    upsert_device_from_client,
)
from app.models.enums import (
    IdentifierKind,
    IngestBatchStatus,
    IngestSource,
    SourceHealthStatus,
)
from app.models.identity import Device, DeviceIdentifier, IpAssignment
from app.models.raw import IngestBatch, RawUnifiClient, RawUnifiEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR_CANDIDATES = (
    Path("/fixtures"),
    REPO_ROOT / "fixtures",
)


def _fixture_dir() -> Path:
    for path in FIXTURE_DIR_CANDIDATES:
        clients = path / "unifi_clients_sample.json"
        events = path / "unifi_events_sample.json"
        if clients.is_file() and events.is_file():
            return path
    raise FileNotFoundError(
        "unifi fixtures not found; expected under /fixtures or repo fixtures/"
    )


@pytest.fixture
def ingest_settings() -> Settings:
    return Settings(
        source_health_stale_seconds=300,
        source_health_max_failures=3,
    )


def test_normalize_mac_canonical() -> None:
    assert normalize_mac("AA-BB-CC-DD-EE-01") == "aa:bb:cc:dd:ee:01"
    assert normalize_mac("aabbccddee01") == "aa:bb:cc:dd:ee:01"


def test_normalize_client_keys_on_mac_not_ip() -> None:
    row = normalize_client(
        {
            "_id": "abc123",
            "mac": "AA:BB:CC:DD:EE:01",
            "hostname": "ipad-child",
            "ip": "192.168.1.50",
            "first_seen": 1700000000,
            "last_seen": 1721740800,
            "tx_bytes": 100,
            "rx_bytes": 200,
            "essid": "HomeWifi",
            "ap_mac": "11:22:33:44:55:66",
        }
    )
    assert row.mac == "aa:bb:cc:dd:ee:01"
    assert row.unifi_client_id == "abc123"
    assert row.hostname == "ipad-child"
    assert row.ip == "192.168.1.50"
    assert row.tx_bytes == 100
    assert row.rx_bytes == 200
    assert row.uplink is not None
    assert "ssid=HomeWifi" in row.uplink


@pytest.mark.asyncio
async def test_replay_fixture_creates_raw_normalized_ip_and_health(
    db_session: AsyncSession,
    ingest_settings: Settings,
) -> None:
    fixture_dir = _fixture_dir()
    batch = await replay_fixture(fixture_dir, cfg=ingest_settings, session=db_session)

    assert batch.status == IngestBatchStatus.SUCCEEDED
    assert batch.record_count == 5  # 3 clients + 2 events
    assert batch.source == IngestSource.UNIFI_API
    assert batch.finished_at is not None
    assert batch.error is None

    stored_batch = await db_session.get(IngestBatch, batch.id)
    assert stored_batch is not None
    assert stored_batch.status == IngestBatchStatus.SUCCEEDED

    raw_clients = list(
        (
            await db_session.execute(
                select(RawUnifiClient).where(
                    RawUnifiClient.ingest_batch_id == batch.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(raw_clients) == 3
    assert all(isinstance(r.payload, dict) for r in raw_clients)

    raw_events = list(
        (
            await db_session.execute(
                select(RawUnifiEvent).where(RawUnifiEvent.ingest_batch_id == batch.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(raw_events) == 2
    assert {r.payload["_id"] for r in raw_events} == {"evt1001", "evt1002"}

    devices = list((await db_session.execute(select(Device))).scalars().all())
    assert len(devices) == 3
    assert all(d.logic_version == LOGIC_VERSION for d in devices)

    identifiers = list(
        (await db_session.execute(select(DeviceIdentifier))).scalars().all()
    )
    kinds = {i.kind for i in identifiers}
    assert IdentifierKind.MAC in kinds
    assert IdentifierKind.UNIFI_CLIENT_ID in kinds
    assert IdentifierKind.HOSTNAME in kinds
    # IP may be stored as weak evidence, but never used to merge identities.
    assert IdentifierKind.IP in kinds
    assert all(d.is_unknown is False for d in devices)

    mac_values = {i.value for i in identifiers if i.kind == IdentifierKind.MAC}
    assert mac_values == {
        "aa:bb:cc:dd:ee:01",
        "aa:bb:cc:dd:ee:02",
        "aa:bb:cc:dd:ee:03",
    }

    # Same IP on two MACs → two devices (identity is MAC, not IP).
    mac_to_device = {
        i.value: i.device_id
        for i in identifiers
        if i.kind == IdentifierKind.MAC
    }
    assert mac_to_device["aa:bb:cc:dd:ee:01"] != mac_to_device["aa:bb:cc:dd:ee:03"]

    assignments = list(
        (await db_session.execute(select(IpAssignment))).scalars().all()
    )
    assert len(assignments) == 3
    assert all(a.source == "unifi_api" for a in assignments)
    assert all(a.logic_version == LOGIC_VERSION for a in assignments)
    assert all(a.observed_to is None for a in assignments)
    ips_by_device = {a.device_id: a.ip for a in assignments}
    assert ips_by_device[mac_to_device["aa:bb:cc:dd:ee:01"]] == "192.168.1.50"
    assert ips_by_device[mac_to_device["aa:bb:cc:dd:ee:02"]] == "192.168.1.20"
    assert ips_by_device[mac_to_device["aa:bb:cc:dd:ee:03"]] == "192.168.1.50"

    health = await get_source_health(
        db_session,
        IngestSource.UNIFI_API,
        cfg=ingest_settings,
        refresh=False,
    )
    assert health.status == SourceHealthStatus.OK
    assert health.last_success_at is not None
    assert health.consecutive_failures == 0


@pytest.mark.asyncio
async def test_ip_change_records_assignment_history_same_device(
    db_session: AsyncSession,
    ingest_settings: Settings,
) -> None:
    await replay_fixture(_fixture_dir(), cfg=ingest_settings, session=db_session)

    mac = "aa:bb:cc:dd:ee:01"
    device = await upsert_device_from_client(
        db_session,
        NormalizedClient(
            mac=mac,
            unifi_client_id="64a1b2c3d4e5f67890123401",
            hostname="ipad-child",
            ip="192.168.1.99",
            uplink="ssid=HomeWifi",
            first_seen=datetime.fromtimestamp(1700000000, tz=UTC),
            last_seen=datetime.fromtimestamp(1721740900, tz=UTC),
            tx_bytes=1,
            rx_bytes=2,
            payload={"mac": mac, "ip": "192.168.1.99"},
        ),
    )
    await db_session.commit()

    mac_rows = list(
        (
            await db_session.execute(
                select(DeviceIdentifier).where(
                    DeviceIdentifier.kind == IdentifierKind.MAC,
                    DeviceIdentifier.value == mac,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(mac_rows) == 1
    assert mac_rows[0].device_id == device.id

    history = list(
        (
            await db_session.execute(
                select(IpAssignment)
                .where(IpAssignment.device_id == device.id)
                .order_by(IpAssignment.observed_from)
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 2
    assert history[0].ip == "192.168.1.50"
    assert history[0].observed_to is not None
    assert history[1].ip == "192.168.1.99"
    assert history[1].observed_to is None
