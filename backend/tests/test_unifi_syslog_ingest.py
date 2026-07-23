"""Offline UniFi syslog ingest via fixture replay (no live controller)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.health.source_health import get_source_health, record_failure, record_success
from app.ingest.unifi_syslog import (
    LOGIC_VERSION,
    parse_syslog_line,
    replay_fixture,
    syslog_health_settings,
)
from app.models.enums import IngestBatchStatus, IngestSource, SourceHealthStatus
from app.models.raw import IngestBatch, RawUnifiSyslog

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CANDIDATES = (
    Path("/fixtures/unifi_syslog_sample.log"),
    REPO_ROOT / "fixtures" / "unifi_syslog_sample.log",
)


def _fixture_path() -> Path:
    for path in FIXTURE_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "unifi_syslog_sample.log not found; expected under /fixtures or repo fixtures/"
    )


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
def ingest_settings() -> Settings:
    return Settings(
        source_health_stale_seconds=300,
        source_health_max_failures=3,
        unifi_syslog_stale_seconds=120,
    )


def test_parse_cef_wifi_connected_structured_fields() -> None:
    line = (
        "<134>Jul 23 12:00:01 UDM CEF:0|Ubiquiti|UniFi Network|9.3.33|400|"
        "WiFi Client Connected|2|UNIFIcategory=Monitoring UNIFIsubCategory=WiFi "
        "UNIFIclientMac=aa:bb:cc:dd:ee:01 UNIFIclientIp=192.168.1.50 "
        "UNIFIclientHostname=ipad-child UNIFIwifiName=HomeWifi "
        "msg=ipad-child connected to HomeWifi"
    )
    result = parse_syslog_line(line)
    assert result.parsed is not None
    assert result.parsed["logic_version"] == LOGIC_VERSION
    assert result.parsed["format"] == "cef"
    assert result.parsed["event_name"] == "WiFi Client Connected"
    assert result.parsed["mac"] == "aa:bb:cc:dd:ee:01"
    assert result.parsed["client_ip"] == "192.168.1.50"
    assert result.parsed["ssid"] == "HomeWifi"
    assert result.parsed["hostname"] == "ipad-child"
    assert result.parsed["category"] == "Monitoring"


def test_parse_firewall_and_event_lines() -> None:
    fw = parse_syslog_line(
        "<14>Jul 23 12:03:00 USG kernel: [WAN_LOCAL-D-DEFAULT-A] "
        'DESCR="Drop by default policy" SRC=198.51.100.9 DST=203.0.113.1 PROTO=TCP'
    )
    assert fw.parsed is not None
    assert fw.parsed["format"] == "firewall"
    assert fw.parsed["event_name"] == "WAN_LOCAL-D-DEFAULT-A"
    assert fw.parsed["client_ip"] == "198.51.100.9"

    evt = parse_syslog_line(
        "Jul 23 12:04:00 UAP-LR EVT_WU_Connected "
        "User[AA:BB:CC:DD:EE:03] associated with AP[11:22:33:44:55:66] SSID[KidsWifi]"
    )
    assert evt.parsed is not None
    assert evt.parsed["format"] == "event"
    assert evt.parsed["event_name"] == "EVT_WU_Connected"
    assert evt.parsed["mac"] == "aa:bb:cc:dd:ee:03"
    assert evt.parsed["ssid"] == "KidsWifi"


def test_unknown_line_stays_unparsed() -> None:
    result = parse_syslog_line(
        "garbage line that is not a unifi security or event format"
    )
    assert result.parsed is None
    assert "garbage line" in result.raw_line


@pytest.mark.asyncio
async def test_replay_fixture_parses_stores_and_counts_unparsed(
    db_session: AsyncSession,
    ingest_settings: Settings,
) -> None:
    result = await replay_fixture(
        _fixture_path(),
        cfg=ingest_settings,
        session=db_session,
    )

    assert result.batch.status == IngestBatchStatus.SUCCEEDED
    assert result.batch.source == IngestSource.UNIFI_SYSLOG
    assert result.line_count == 6
    assert result.parsed_count == 5
    assert result.unparsed_count == 1
    assert result.batch.record_count == 6

    rows = list(
        (
            await db_session.execute(
                select(RawUnifiSyslog).where(
                    RawUnifiSyslog.ingest_batch_id == result.batch.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 6
    assert all(r.raw_line for r in rows)

    parsed_rows = [r for r in rows if r.parsed is not None]
    unparsed_rows = [r for r in rows if r.parsed is None]
    assert len(parsed_rows) == 5
    assert len(unparsed_rows) == 1
    assert "garbage line" in unparsed_rows[0].raw_line

    cef = next(r for r in parsed_rows if r.parsed and r.parsed.get("format") == "cef")
    assert cef.parsed is not None
    assert cef.parsed["logic_version"] == LOGIC_VERSION

    stored_batch = await db_session.get(IngestBatch, result.batch.id)
    assert stored_batch is not None
    assert stored_batch.status == IngestBatchStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_health_flips_to_ok_on_receipt(
    db_session: AsyncSession,
    ingest_settings: Settings,
) -> None:
    health_cfg = syslog_health_settings(ingest_settings)
    seed_at = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)
    await record_success(
        db_session,
        IngestSource.UNIFI_SYSLOG,
        now=seed_at,
        cfg=health_cfg,
        detail="prior success",
    )
    for i in range(3):
        await record_failure(
            db_session,
            IngestSource.UNIFI_SYSLOG,
            now=seed_at + timedelta(seconds=i + 1),
            cfg=health_cfg,
        )
    await db_session.commit()

    before = await get_source_health(
        db_session,
        IngestSource.UNIFI_SYSLOG,
        now=seed_at + timedelta(seconds=10),
        cfg=health_cfg,
        refresh=False,
    )
    assert before.status == SourceHealthStatus.DOWN

    await replay_fixture(_fixture_path(), cfg=ingest_settings, session=db_session)

    after = await get_source_health(
        db_session,
        IngestSource.UNIFI_SYSLOG,
        cfg=health_cfg,
        refresh=False,
    )
    assert after.status == SourceHealthStatus.OK
    assert after.last_success_at is not None
    assert after.consecutive_failures == 0
    assert "unparsed" in after.detail.lower()


@pytest.mark.asyncio
async def test_health_degraded_when_no_lines_in_window(
    db_session: AsyncSession,
    ingest_settings: Settings,
) -> None:
    health_cfg = syslog_health_settings(ingest_settings)
    success_at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    await record_success(
        db_session,
        IngestSource.UNIFI_SYSLOG,
        now=success_at,
        cfg=health_cfg,
        detail="seed",
    )
    await db_session.commit()

    later = success_at + timedelta(
        seconds=ingest_settings.unifi_syslog_stale_seconds + 1
    )
    report = await get_source_health(
        db_session,
        IngestSource.UNIFI_SYSLOG,
        now=later,
        cfg=health_cfg,
        refresh=True,
    )
    assert report.status == SourceHealthStatus.DEGRADED
    assert report.staleness_seconds is not None
    assert report.staleness_seconds > ingest_settings.unifi_syslog_stale_seconds
