"""Versioned aggregation of correlated DNS + UniFi traffic into window summaries.

Derived metrics are transparent and deterministic. Language never implies that
a DNS query proves content was viewed.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.resolver import normalize_mac
from app.models.dns import DnsActivity, DnsQuery
from app.models.enums import CorrelationStatus, DnsQueryStatus, IdentifierKind
from app.models.identity import Device, DeviceIdentifier
from app.models.people import Person, PersonDevice
from app.models.raw import RawUnifiClient

AGGREGATE_LOGIC_VERSION = "activity_aggregate.v1"

SubjectType = Literal["device", "person"]

_WINDOW_RE = re.compile(r"^(\d+)([hd])$", re.IGNORECASE)

# UniFi sta counters: tx = AP→client (download), rx = client→AP (upload).
_UNIFI_DOWNLOAD_FIELD = "tx_bytes"
_UNIFI_UPLOAD_FIELD = "rx_bytes"


@dataclass(frozen=True, slots=True)
class DnsActivityRecord:
    """One attributed DNS query used for aggregation (pure / testable)."""

    queried_at: datetime
    domain: str
    status: DnsQueryStatus
    device_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class UnifiTrafficRecord:
    """One UniFi client snapshot linked to a durable device."""

    device_id: uuid.UUID
    observed_at: datetime
    upload_bytes: int | None
    download_bytes: int | None
    connection_duration_seconds: float | None
    source_fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActivitySummary:
    """Aggregated activity for one device or person over a time window."""

    subject_type: SubjectType
    subject_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    dns_query_volume: int
    blocked_query_count: int
    blocked_query_pct: float
    unique_domain_count: int
    new_domain_count: int
    active_hour_count: int
    active_hours_utc: tuple[int, ...]
    upload_bytes: int | None
    download_bytes: int | None
    connection_duration_seconds: float | None
    logic_version: str = AGGREGATE_LOGIC_VERSION
    inputs: Mapping[str, Any] = field(default_factory=dict)

    def metric_values(self) -> dict[str, float]:
        """Numeric metrics suitable for baseline comparison."""
        values: dict[str, float] = {
            "dns_query_volume": float(self.dns_query_volume),
            "blocked_query_pct": float(self.blocked_query_pct),
            "unique_domain_count": float(self.unique_domain_count),
            "new_domain_count": float(self.new_domain_count),
            "active_hour_count": float(self.active_hour_count),
        }
        if self.upload_bytes is not None:
            values["upload_bytes"] = float(self.upload_bytes)
        if self.download_bytes is not None:
            values["download_bytes"] = float(self.download_bytes)
        if self.connection_duration_seconds is not None:
            values["connection_duration_seconds"] = float(
                self.connection_duration_seconds
            )
        return values


def parse_window(window: str) -> timedelta:
    """Parse ``Nh`` / ``Nd`` window strings into a timedelta."""
    raw = window.strip().lower()
    match = _WINDOW_RE.fullmatch(raw)
    if match is None:
        raise ValueError(
            f"Invalid window {window!r}; expected forms like '1h', '24h', '7d'"
        )
    amount = int(match.group(1))
    unit = match.group(2)
    if amount < 1:
        raise ValueError(f"Window amount must be >= 1, got {amount}")
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)


def _normalize_domain(domain: str) -> str:
    return domain.strip().lower().rstrip(".")


def aggregate_dns_records(
    records: Sequence[DnsActivityRecord],
    *,
    window_start: datetime,
    window_end: datetime,
    prior_domains: Iterable[str] = (),
) -> dict[str, Any]:
    """Pure DNS aggregation over records already filtered to the subject.

    ``prior_domains`` are domains seen for the subject before ``window_start``;
    any domain in the window not in that set counts as new.
    """
    prior = {_normalize_domain(d) for d in prior_domains if d}
    in_window = [r for r in records if window_start <= r.queried_at <= window_end]
    volume = len(in_window)
    blocked = sum(1 for r in in_window if r.status == DnsQueryStatus.BLOCKED)
    domains = {_normalize_domain(r.domain) for r in in_window if r.domain}
    new_domains = {d for d in domains if d not in prior}
    active_hours = sorted({r.queried_at.astimezone(UTC).hour for r in in_window})
    # Distinct clock-hour buckets inside the window (date+hour).
    hour_buckets = {
        r.queried_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        for r in in_window
    }
    blocked_pct = (100.0 * blocked / volume) if volume else 0.0
    return {
        "dns_query_volume": volume,
        "blocked_query_count": blocked,
        "blocked_query_pct": round(blocked_pct, 4),
        "unique_domain_count": len(domains),
        "new_domain_count": len(new_domains),
        "active_hour_count": len(hour_buckets),
        "active_hours_utc": tuple(active_hours),
        "new_domains": sorted(new_domains),
        "domains": sorted(domains),
    }


def aggregate_unifi_traffic(
    records: Sequence[UnifiTrafficRecord],
    *,
    device_ids: set[uuid.UUID],
) -> dict[str, Any]:
    """Combine UniFi snapshots for the given devices.

    For each device, use the latest snapshot in the set (session counters are
    cumulative). Person totals sum latest-per-device values.
    """
    latest_by_device: dict[uuid.UUID, UnifiTrafficRecord] = {}
    for row in records:
        if row.device_id not in device_ids:
            continue
        prev = latest_by_device.get(row.device_id)
        if prev is None or row.observed_at >= prev.observed_at:
            latest_by_device[row.device_id] = row

    if not latest_by_device:
        return {
            "upload_bytes": None,
            "download_bytes": None,
            "connection_duration_seconds": None,
            "devices_with_unifi": 0,
            "per_device": {},
        }

    upload_total = 0
    download_total = 0
    duration_total = 0.0
    have_upload = False
    have_download = False
    have_duration = False
    per_device: dict[str, Any] = {}

    for device_id, row in latest_by_device.items():
        per_device[str(device_id)] = {
            "upload_bytes": row.upload_bytes,
            "download_bytes": row.download_bytes,
            "connection_duration_seconds": row.connection_duration_seconds,
            "observed_at": row.observed_at.isoformat(),
            "source_fields": dict(row.source_fields),
        }
        if row.upload_bytes is not None:
            upload_total += row.upload_bytes
            have_upload = True
        if row.download_bytes is not None:
            download_total += row.download_bytes
            have_download = True
        if row.connection_duration_seconds is not None:
            duration_total += row.connection_duration_seconds
            have_duration = True

    return {
        "upload_bytes": upload_total if have_upload else None,
        "download_bytes": download_total if have_download else None,
        "connection_duration_seconds": (
            round(duration_total, 3) if have_duration else None
        ),
        "devices_with_unifi": len(latest_by_device),
        "per_device": per_device,
    }


def build_activity_summary(
    *,
    subject_type: SubjectType,
    subject_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    dns_records: Sequence[DnsActivityRecord],
    prior_domains: Iterable[str],
    unifi_records: Sequence[UnifiTrafficRecord],
    device_ids: set[uuid.UUID],
) -> ActivitySummary:
    """Compose a full summary from pure DNS + UniFi aggregations."""
    dns = aggregate_dns_records(
        dns_records,
        window_start=window_start,
        window_end=window_end,
        prior_domains=prior_domains,
    )
    unifi = aggregate_unifi_traffic(unifi_records, device_ids=device_ids)
    inputs: dict[str, Any] = {
        "logic_version": AGGREGATE_LOGIC_VERSION,
        "device_ids": sorted(str(d) for d in device_ids),
        "dns_record_count": len(
            [r for r in dns_records if window_start <= r.queried_at <= window_end]
        ),
        "prior_domain_count": len({_normalize_domain(d) for d in prior_domains if d}),
        "new_domains": dns["new_domains"],
        "unifi": {
            "devices_with_unifi": unifi["devices_with_unifi"],
            "field_mapping": {
                "upload_bytes": _UNIFI_UPLOAD_FIELD,
                "download_bytes": _UNIFI_DOWNLOAD_FIELD,
                "note": (
                    "UniFi sta tx_bytes = AP→client (download); "
                    "rx_bytes = client→AP (upload). Latest snapshot per device."
                ),
            },
            "per_device": unifi["per_device"],
        },
        "disclaimer": (
            "DNS query volume counts lookups attributed to this subject; "
            "it does not prove that specific content was viewed."
        ),
    }
    return ActivitySummary(
        subject_type=subject_type,
        subject_id=subject_id,
        window_start=window_start,
        window_end=window_end,
        dns_query_volume=dns["dns_query_volume"],
        blocked_query_count=dns["blocked_query_count"],
        blocked_query_pct=dns["blocked_query_pct"],
        unique_domain_count=dns["unique_domain_count"],
        new_domain_count=dns["new_domain_count"],
        active_hour_count=dns["active_hour_count"],
        active_hours_utc=dns["active_hours_utc"],
        upload_bytes=unifi["upload_bytes"],
        download_bytes=unifi["download_bytes"],
        connection_duration_seconds=unifi["connection_duration_seconds"],
        logic_version=AGGREGATE_LOGIC_VERSION,
        inputs=inputs,
    )


def _connection_duration_seconds(
    payload: Mapping[str, Any],
    *,
    window_start: datetime,
    window_end: datetime,
) -> float | None:
    """Prefer UniFi ``uptime``; else overlap of first_seen/last_seen with window."""
    uptime = payload.get("uptime")
    if isinstance(uptime, int | float) and uptime >= 0:
        return float(uptime)
    if isinstance(uptime, str):
        try:
            value = float(uptime)
        except ValueError:
            value = None
        else:
            if value >= 0:
                return value

    first_raw = payload.get("first_seen")
    last_raw = payload.get("last_seen")
    first = _parse_unixish(first_raw)
    last = _parse_unixish(last_raw)
    if first is None or last is None:
        return None
    if last < first:
        first, last = last, first
    overlap_start = max(first, window_start)
    overlap_end = min(last, window_end)
    if overlap_end <= overlap_start:
        return 0.0
    return (overlap_end - overlap_start).total_seconds()


def _parse_unixish(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    if isinstance(value, str):
        try:
            return _parse_unixish(float(value))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


async def resolve_subject_device_ids(
    session: AsyncSession,
    *,
    device_id: uuid.UUID | None = None,
    person_id: uuid.UUID | None = None,
) -> tuple[SubjectType, uuid.UUID, set[uuid.UUID]]:
    """Resolve filter args to subject type/id and the device id set to aggregate."""
    if (device_id is None) == (person_id is None):
        raise ValueError("Provide exactly one of device_id or person_id")

    if device_id is not None:
        return "device", device_id, {device_id}

    result = await session.execute(
        select(PersonDevice.device_id).where(
            PersonDevice.person_id == person_id,
            PersonDevice.active.is_(True),
        )
    )
    ids = set(result.scalars().all())
    assert person_id is not None
    return "person", person_id, ids


async def _load_dns_records(
    session: AsyncSession,
    *,
    device_ids: set[uuid.UUID],
    window_start: datetime,
    window_end: datetime,
) -> list[DnsActivityRecord]:
    if not device_ids:
        return []
    result = await session.execute(
        select(DnsActivity, DnsQuery)
        .join(DnsQuery, DnsQuery.id == DnsActivity.dns_query_id)
        .where(
            DnsActivity.device_id.in_(device_ids),
            DnsActivity.status == CorrelationStatus.ATTRIBUTED,
            DnsActivity.queried_at >= window_start,
            DnsActivity.queried_at <= window_end,
        )
        .order_by(DnsActivity.queried_at, DnsActivity.id)
    )
    rows: list[DnsActivityRecord] = []
    for activity, query in result.all():
        if activity.device_id is None:
            continue
        rows.append(
            DnsActivityRecord(
                queried_at=activity.queried_at,
                domain=query.domain,
                status=query.status,
                device_id=activity.device_id,
            )
        )
    return rows


async def _load_prior_domains(
    session: AsyncSession,
    *,
    device_ids: set[uuid.UUID],
    before: datetime,
) -> set[str]:
    if not device_ids:
        return set()
    result = await session.execute(
        select(DnsQuery.domain)
        .join(DnsActivity, DnsActivity.dns_query_id == DnsQuery.id)
        .where(
            DnsActivity.device_id.in_(device_ids),
            DnsActivity.status == CorrelationStatus.ATTRIBUTED,
            DnsActivity.queried_at < before,
        )
        .distinct()
    )
    return {_normalize_domain(d) for d in result.scalars().all() if d}


async def _mac_to_device_ids(
    session: AsyncSession,
    macs: set[str],
) -> dict[str, uuid.UUID]:
    if not macs:
        return {}
    result = await session.execute(
        select(DeviceIdentifier).where(
            DeviceIdentifier.kind == IdentifierKind.MAC,
            DeviceIdentifier.value.in_(macs),
        )
    )
    return {row.value: row.device_id for row in result.scalars().all()}


async def load_unifi_records(
    session: AsyncSession,
    *,
    device_ids: set[uuid.UUID],
    window_start: datetime,
    window_end: datetime,
) -> list[UnifiTrafficRecord]:
    if not device_ids:
        return []
    result = await session.execute(
        select(RawUnifiClient).where(
            and_(
                RawUnifiClient.ingested_at >= window_start,
                RawUnifiClient.ingested_at <= window_end,
            )
        )
    )
    raw_rows = list(result.scalars().all())
    macs: set[str] = set()
    parsed: list[tuple[RawUnifiClient, str, dict[str, Any]]] = []
    for raw in raw_rows:
        payload = raw.payload or {}
        mac_raw = payload.get("mac")
        if not mac_raw:
            continue
        try:
            mac = normalize_mac(str(mac_raw))
        except ValueError:
            continue
        macs.add(mac)
        parsed.append((raw, mac, dict(payload)))

    mac_map = await _mac_to_device_ids(session, macs)
    records: list[UnifiTrafficRecord] = []
    for raw, mac, payload in parsed:
        device_id = mac_map.get(mac)
        if device_id is None or device_id not in device_ids:
            continue
        upload = payload.get(_UNIFI_UPLOAD_FIELD)
        download = payload.get(_UNIFI_DOWNLOAD_FIELD)
        upload_i = int(upload) if isinstance(upload, int | float) else None
        download_i = int(download) if isinstance(download, int | float) else None
        duration = _connection_duration_seconds(
            payload,
            window_start=window_start,
            window_end=window_end,
        )
        records.append(
            UnifiTrafficRecord(
                device_id=device_id,
                observed_at=raw.ingested_at,
                upload_bytes=upload_i,
                download_bytes=download_i,
                connection_duration_seconds=duration,
                source_fields={
                    "mac": mac,
                    "raw_unifi_client_id": str(raw.id),
                    "tx_bytes": download_i,
                    "rx_bytes": upload_i,
                    "uptime": payload.get("uptime"),
                    "first_seen": payload.get("first_seen"),
                    "last_seen": payload.get("last_seen"),
                },
            )
        )
    return records


async def aggregate_activity(
    session: AsyncSession,
    *,
    window: str,
    device_id: uuid.UUID | None = None,
    person_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> ActivitySummary:
    """Load correlated activity + UniFi snapshots and aggregate for the subject."""
    delta = parse_window(window)
    end = now or datetime.now(UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    start = end - delta

    subject_type, subject_id, device_ids = await resolve_subject_device_ids(
        session,
        device_id=device_id,
        person_id=person_id,
    )
    dns_records = await _load_dns_records(
        session,
        device_ids=device_ids,
        window_start=start,
        window_end=end,
    )
    prior_domains = await _load_prior_domains(
        session,
        device_ids=device_ids,
        before=start,
    )
    unifi_records = await load_unifi_records(
        session,
        device_ids=device_ids,
        window_start=start,
        window_end=end,
    )
    return build_activity_summary(
        subject_type=subject_type,
        subject_id=subject_id,
        window_start=start,
        window_end=end,
        dns_records=dns_records,
        prior_domains=prior_domains,
        unifi_records=unifi_records,
        device_ids=device_ids,
    )


async def subject_exists(
    session: AsyncSession,
    subject_id: uuid.UUID,
) -> tuple[SubjectType, uuid.UUID] | None:
    """Return ``(subject_type, id)`` if ``subject_id`` is a device or person.

    Devices are checked first so a collision is impossible in practice (UUIDs
    are unique across tables) but the lookup order stays deterministic.
    """
    device = await session.get(Device, subject_id)
    if device is not None:
        return "device", subject_id
    person = await session.get(Person, subject_id)
    if person is not None:
        return "person", subject_id
    return None
