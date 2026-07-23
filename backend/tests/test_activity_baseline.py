"""Transparent baseline stats + explainable deviation detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.activity.aggregate import ActivitySummary
from app.activity.baseline import (
    BASELINE_LOGIC_VERSION,
    compute_baseline,
    compute_metric_baseline,
    detect_deviations,
    get_latest_baseline,
)
from app.correlate.engine import LOGIC_VERSION as CORRELATION_LOGIC_VERSION
from app.db import get_session
from app.identity.resolver import ClientObservation, resolve_observation
from app.main import app
from app.models.activity import ActivityBaseline
from app.models.dns import DnsActivity, DnsQuery
from app.models.enums import (
    CorrelationStatus,
    DnsQueryStatus,
    IngestBatchStatus,
    IngestSource,
)
from app.models.raw import IngestBatch, RawPiholeEvent


def _summary(
    *,
    subject_id,
    volume: int,
    blocked_pct: float = 10.0,
    unique_domains: int = 5,
    new_domains: int = 1,
    active_hours: tuple[int, ...] = (9, 10, 11),
    window_end: datetime | None = None,
    upload: int | None = 1000,
    download: int | None = 5000,
) -> ActivitySummary:
    end = window_end or datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    start = end - timedelta(hours=24)
    return ActivitySummary(
        subject_type="device",
        subject_id=subject_id,
        window_start=start,
        window_end=end,
        dns_query_volume=volume,
        blocked_query_count=int(round(volume * blocked_pct / 100.0)),
        blocked_query_pct=blocked_pct,
        unique_domain_count=unique_domains,
        new_domain_count=new_domains,
        active_hour_count=len(active_hours),
        active_hours_utc=active_hours,
        upload_bytes=upload,
        download_bytes=download,
        connection_duration_seconds=3600.0,
        inputs={"test": True},
    )


def test_metric_baseline_mean_stddev_percentile() -> None:
    # samples: 10, 20, 30 → mean 20, sample stddev = sqrt(100)=10
    mb = compute_metric_baseline([10, 20, 30], metric="dns_query_volume")
    assert mb.mean == 20.0
    assert mb.stddev == 10.0
    assert mb.high_threshold_z == 40.0  # mean + 2*stddev
    # nearest-rank p95 of 3 samples → rank ceil(0.95*3)=3 → 30
    assert mb.percentile_value == 30.0


def test_detect_deviation_flags_far_outlier_with_reason() -> None:
    device_id = uuid4()
    samples = [
        _summary(
            subject_id=device_id,
            volume=v,
            window_end=datetime(2024, 7, d, 12, tzinfo=UTC),
        )
        for d, v in enumerate([10, 12, 11, 13, 10, 12, 11], start=1)
    ]
    baseline = compute_baseline(
        samples,
        subject_type="device",
        subject_id=device_id,
        window="24h",
    )
    assert baseline.logic_version == BASELINE_LOGIC_VERSION
    assert "dns_query_volume" in baseline.metrics
    assert baseline.inputs["sample_windows"]
    assert "No machine learning" in baseline.inputs["method"]

    # Far above mean (~11.3) with stddev ~1.1 → z >> 2
    live = _summary(
        subject_id=device_id,
        volume=100,
        window_end=datetime(2024, 7, 10, 12, tzinfo=UTC),
    )
    deviations = detect_deviations(live, baseline)
    by_metric = {d.metric: d for d in deviations}
    assert "dns_query_volume" in by_metric
    dev = by_metric["dns_query_volume"]
    assert dev.z_score is not None and dev.z_score > 2.0
    assert dev.threshold_kind == "z_score"
    assert "dns_query_volume=100" in dev.reason
    assert "standard deviations above" in dev.reason
    assert f"{dev.baseline_mean:g}" in dev.reason


def test_detect_deviation_constant_baseline_increase() -> None:
    device_id = uuid4()
    samples = [
        _summary(
            subject_id=device_id,
            volume=10,
            window_end=datetime(2024, 7, d, tzinfo=UTC),
        )
        for d in range(1, 6)
    ]
    baseline = compute_baseline(
        samples,
        subject_type="device",
        subject_id=device_id,
        window="24h",
    )
    live = _summary(subject_id=device_id, volume=50)
    deviations = detect_deviations(live, baseline)
    volume_dev = next(d for d in deviations if d.metric == "dns_query_volume")
    assert volume_dev.threshold_kind == "above_constant_mean"
    assert "constant baseline mean" in volume_dev.reason
    assert "dns_query_volume=50" in volume_dev.reason


def test_typical_active_hours_and_dow_patterns() -> None:
    device_id = uuid4()
    # Most samples active at 9 and 10; only one at 22.
    samples = [
        _summary(
            subject_id=device_id,
            volume=10,
            active_hours=(9, 10),
            window_end=datetime(2024, 7, 1, 12, tzinfo=UTC),  # Monday
        ),
        _summary(
            subject_id=device_id,
            volume=20,
            active_hours=(9, 10, 22),
            window_end=datetime(2024, 7, 2, 12, tzinfo=UTC),  # Tuesday
        ),
        _summary(
            subject_id=device_id,
            volume=30,
            active_hours=(9, 10),
            window_end=datetime(2024, 7, 3, 12, tzinfo=UTC),  # Wednesday
        ),
    ]
    baseline = compute_baseline(
        samples,
        subject_type="device",
        subject_id=device_id,
        window="24h",
    )
    assert baseline.typical_active_hours_utc == (9, 10)
    monday = baseline.day_of_week_patterns["weekdays"]["monday"]
    assert monday["mean_dns_query_volume"] == 10.0
    tuesday = baseline.day_of_week_patterns["weekdays"]["tuesday"]
    assert tuesday["mean_dns_query_volume"] == 20.0


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


async def _seed_query(
    session: AsyncSession,
    *,
    device_id,
    queried_at: datetime,
    domain: str = "example.com",
) -> None:
    batch = IngestBatch(
        source=IngestSource.PIHOLE_API,
        started_at=queried_at,
        status=IngestBatchStatus.SUCCEEDED,
        record_count=1,
        finished_at=queried_at,
    )
    session.add(batch)
    await session.flush()
    raw = RawPiholeEvent(
        source_ts=queried_at,
        payload={"domain": domain},
        ingest_batch_id=batch.id,
    )
    session.add(raw)
    await session.flush()
    query = DnsQuery(
        logic_version="dns_query.v1",
        queried_at=queried_at,
        client_identifier="phone",
        client_ip="192.168.1.80",
        domain=domain,
        query_type="A",
        status=DnsQueryStatus.ALLOWED,
        upstream=None,
        pihole_query_id=None,
        raw_pihole_event_id=raw.id,
        ingest_batch_id=batch.id,
    )
    session.add(query)
    await session.flush()
    session.add(
        DnsActivity(
            logic_version=CORRELATION_LOGIC_VERSION,
            dns_query_id=query.id,
            device_id=device_id,
            queried_at=queried_at,
            confidence=Decimal("0.9000"),
            evidence={"matches": []},
            conflicts={"items": []},
            status=CorrelationStatus.ATTRIBUTED,
            needs_review=False,
        )
    )


@pytest.mark.asyncio
async def test_baseline_api_stores_inputs_and_activity_flags_deviation(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    now = datetime.now(UTC)
    device = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=now,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:99",
            ip="192.168.1.99",
        ),
    )

    # Stable history: ~3 queries per recent hour-window sample via one query each
    # of the last several hours — then a burst in the current hour.
    for hours_ago in range(2, 10):
        await _seed_query(
            db_session,
            device_id=device.id,
            queried_at=now - timedelta(hours=hours_ago, minutes=10),
            domain=f"normal-{hours_ago}.example",
        )
    # Burst: many queries in the current window.
    for i in range(40):
        await _seed_query(
            db_session,
            device_id=device.id,
            queried_at=now - timedelta(minutes=i % 50),
            domain=f"burst-{i}.example",
        )
    await db_session.commit()

    # Persist a baseline from synthetic constant samples so deviation is clear.
    device_id = device.id
    samples = [
        ActivitySummary(
            subject_type="device",
            subject_id=device_id,
            window_start=now - timedelta(hours=24 + i),
            window_end=now - timedelta(hours=i),
            dns_query_volume=5,
            blocked_query_count=0,
            blocked_query_pct=0.0,
            unique_domain_count=5,
            new_domain_count=1,
            active_hour_count=1,
            active_hours_utc=(12,),
            upload_bytes=100,
            download_bytes=200,
            connection_duration_seconds=60.0,
            inputs={"synthetic": True, "i": i},
        )
        for i in range(7)
    ]
    baseline = compute_baseline(
        samples,
        subject_type="device",
        subject_id=device_id,
        window="1h",
        computed_at=now,
    )
    db_session.add(
        ActivityBaseline(
            logic_version=baseline.logic_version,
            subject_type=baseline.subject_type,
            subject_id=baseline.subject_id,
            window=baseline.window,
            computed_at=baseline.computed_at,
            sample_count=baseline.sample_count,
            metrics=baseline.as_metrics_dict(),
            typical_active_hours_utc=list(baseline.typical_active_hours_utc),
            day_of_week_patterns=baseline.day_of_week_patterns,
            inputs=baseline.inputs,
        )
    )
    await db_session.commit()

    stored = await get_latest_baseline(db_session, subject_id=device_id, window="1h")
    assert stored is not None
    assert stored.inputs.get("sample_windows")

    base_resp = await api_client.get(
        f"/api/baselines/{device_id}",
        params={"window": "1h"},
    )
    assert base_resp.status_code == 200
    base_body = base_resp.json()
    assert base_body["logic_version"] == BASELINE_LOGIC_VERSION
    assert base_body["metrics"]["dns_query_volume"]["mean"] == 5.0
    assert "sample_windows" in base_body["inputs"]

    act_resp = await api_client.get(
        "/api/activity",
        params={"device": str(device_id), "window": "1h"},
    )
    assert act_resp.status_code == 200
    act = act_resp.json()
    assert act["dns_query_volume"] >= 40
    assert act["deviations"]
    volume_dev = next(d for d in act["deviations"] if d["metric"] == "dns_query_volume")
    assert volume_dev["value"] == act["dns_query_volume"]
    assert "dns_query_volume=" in volume_dev["reason"]
    assert volume_dev["delta_from_mean"] > 0


@pytest.mark.asyncio
async def test_baseline_recompute_endpoint(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    now = datetime.now(UTC)
    device = await resolve_observation(
        db_session,
        ClientObservation(
            observed_at=now,
            source="unifi_api",
            mac="aa:bb:cc:dd:ee:88",
            ip="192.168.1.88",
        ),
    )
    await _seed_query(
        db_session,
        device_id=device.id,
        queried_at=now - timedelta(minutes=5),
    )
    await db_session.commit()

    resp = await api_client.get(
        f"/api/baselines/{device.id}",
        params={"window": "1h", "recompute": "true", "samples": 3},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject_id"] == str(device.id)
    assert body["window"] == "1h"
    assert body["sample_count"] >= 1
    assert "inputs" in body

    result = await db_session.execute(select(ActivityBaseline))
    assert result.scalars().first() is not None
