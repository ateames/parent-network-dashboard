"""Build the single parent-facing dashboard summary.

When ingest sources are down, sections that depend on them are marked incomplete
and numeric fields that would otherwise look like "all quiet" stay null rather
than being silently zeroed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.activity.aggregate import (
    DnsActivityRecord,
    aggregate_dns_records,
    aggregate_unifi_traffic,
    load_unifi_records,
)
from app.activity.baseline import get_latest_baseline, row_to_baseline
from app.config import Settings, settings
from app.health.source_health import SourceHealthReport, list_source_health
from app.models.dns import DnsActivity, DnsQuery
from app.models.enums import (
    CorrelationStatus,
    DnsQueryStatus,
    FindingSeverity,
    FindingStatus,
    IngestSource,
    PersonRole,
    SourceHealthStatus,
)
from app.models.findings import Finding
from app.models.identity import Device
from app.models.people import Person, PersonDevice
from app.schemas.dashboard import (
    ActiveChildOut,
    AttentionItemOut,
    AttentionOut,
    DashboardDeviceOut,
    DashboardSummaryOut,
    DataHealthOut,
    DataHealthSourceOut,
    FindingsBySeverityOut,
    OnlineDevicesOut,
    RecentActivityItemOut,
    RecentActivityOut,
    TrendMetricOut,
    TrendsOut,
    UnknownUnassignedOut,
)

DASHBOARD_LOGIC_VERSION = "dashboard_summary.v1"

DEFAULT_ATTENTION_LIMIT = 5
DEFAULT_RECENT_ACTIVITY_LIMIT = 10
TREND_WINDOW = "24h"

HouseholdStatus = Literal["ok", "attention-needed"]

# Sources that must be healthy for a complete household picture.
_CRITICAL_SOURCES: frozenset[IngestSource] = frozenset(
    {
        IngestSource.PIHOLE_API,
        IngestSource.UNIFI_API,
        IngestSource.UNIFI_SYSLOG,
    }
)


@dataclass(frozen=True, slots=True)
class _DeviceView:
    device: Device
    person_id: UUID | None
    person_name: str | None
    person_role: PersonRole | None
    is_online: bool
    is_unassigned: bool


def incomplete_sources_from_health(
    reports: Sequence[SourceHealthReport],
) -> list[IngestSource]:
    """Return sources in a down state (never inventing healthy zeros)."""
    down: list[IngestSource] = []
    for report in reports:
        if report.source not in _CRITICAL_SOURCES:
            continue
        if report.status == SourceHealthStatus.DOWN:
            down.append(report.source)
    return down


def derive_household_status(
    *,
    incomplete_sources: Sequence[IngestSource],
    attention_items: Sequence[AttentionItemOut],
    attention_count: int,
) -> tuple[HouseholdStatus, str]:
    """Return ``(status, one-line reason)`` for the household overview."""
    if incomplete_sources:
        names = ", ".join(s.value for s in incomplete_sources)
        return (
            "attention-needed",
            f"Data incomplete: {names} unavailable",
        )
    if attention_count > 0:
        top = attention_items[0].summary if attention_items else "Items need review"
        if attention_count == 1:
            return "attention-needed", top
        return (
            "attention-needed",
            f"{attention_count} items need attention — {top}",
        )
    return "ok", "Household looks normal"


def _active_person_link(device: Device) -> PersonDevice | None:
    for link in device.person_links:
        if link.active and link.person is not None:
            return link
    return None


def _to_device_out(view: _DeviceView) -> DashboardDeviceOut:
    return DashboardDeviceOut(
        id=view.device.id,
        display_name=view.device.display_name,
        is_unknown=view.device.is_unknown,
        last_seen=view.device.last_seen,
        assigned_person_id=view.person_id,
        assigned_person_name=view.person_name,
    )


def _health_out(report: SourceHealthReport) -> DataHealthSourceOut:
    return DataHealthSourceOut(
        source=report.source,
        status=report.status,
        last_success_at=report.last_success_at,
        last_attempt_at=report.last_attempt_at,
        staleness_seconds=report.staleness_seconds,
        detail=report.detail,
    )


def build_attention_items(
    *,
    health_reports: Sequence[SourceHealthReport],
    review_rows: Sequence[tuple[DnsActivity, DnsQuery]],
    unknown_unassigned: Sequence[_DeviceView],
    limit: int = DEFAULT_ATTENTION_LIMIT,
) -> list[AttentionItemOut]:
    """Build ordered attention items (caller slices to ``limit`` for the top few)."""
    items: list[AttentionItemOut] = []

    for report in health_reports:
        if report.status == SourceHealthStatus.DOWN:
            items.append(
                AttentionItemOut(
                    kind="source_down",
                    source=report.source,
                    summary=f"{report.source.value} is down — {report.detail}",
                )
            )
        elif report.status == SourceHealthStatus.DEGRADED:
            items.append(
                AttentionItemOut(
                    kind="source_degraded",
                    source=report.source,
                    summary=(
                        f"{report.source.value} is degraded — {report.detail}"
                    ),
                )
            )

    for activity, query in review_rows:
        domain = query.domain if query is not None else "unknown domain"
        items.append(
            AttentionItemOut(
                kind="correlation_review",
                id=activity.id,
                summary=f"DNS correlation needs review: {domain}",
            )
        )

    for view in unknown_unassigned:
        if view.device.is_unknown:
            kind: Literal["unknown_device", "unassigned_device"] = "unknown_device"
            label = view.device.display_name or str(view.device.id)
            summary = f"Unknown device online: {label}"
        else:
            kind = "unassigned_device"
            label = view.device.display_name or str(view.device.id)
            summary = f"Unassigned device online: {label}"
        items.append(
            AttentionItemOut(
                kind=kind,
                id=view.device.id,
                summary=summary,
            )
        )

    return items[:limit] if limit >= 0 else items


def _trend_metric(
    *,
    metric: str,
    today_value: float | None,
    baseline_mean: float | None,
    incomplete: bool,
    note: str | None = None,
) -> TrendMetricOut:
    delta: float | None = None
    if today_value is not None and baseline_mean is not None:
        delta = round(today_value - baseline_mean, 6)
    return TrendMetricOut(
        metric=metric,
        today_value=today_value,
        baseline_mean=baseline_mean,
        delta_from_baseline=delta,
        incomplete=incomplete,
        note=note,
    )


async def _load_device_views(
    session: AsyncSession,
    *,
    online_cutoff: datetime,
) -> list[_DeviceView]:
    result = await session.execute(
        select(Device)
        .options(
            selectinload(Device.person_links).selectinload(PersonDevice.person),
        )
        .order_by(Device.last_seen.desc())
    )
    devices = list(result.scalars().unique().all())
    views: list[_DeviceView] = []
    for device in devices:
        link = _active_person_link(device)
        person = link.person if link is not None else None
        views.append(
            _DeviceView(
                device=device,
                person_id=person.id if person is not None else None,
                person_name=person.name if person is not None else None,
                person_role=person.role if person is not None else None,
                is_online=device.last_seen >= online_cutoff,
                is_unassigned=person is None,
            )
        )
    return views


async def _load_review_rows(
    session: AsyncSession,
    *,
    limit: int,
) -> list[tuple[DnsActivity, DnsQuery]]:
    result = await session.execute(
        select(DnsActivity, DnsQuery)
        .join(DnsQuery, DnsQuery.id == DnsActivity.dns_query_id)
        .where(DnsActivity.needs_review.is_(True))
        .order_by(DnsActivity.queried_at.desc())
        .limit(limit)
    )
    return list(result.all())


async def _count_review_items(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(DnsActivity)
        .where(DnsActivity.needs_review.is_(True))
    )
    return int(result.scalar_one())


async def _findings_by_severity(session: AsyncSession) -> FindingsBySeverityOut:
    """Count open findings by severity (critical reserved / unused for now)."""
    result = await session.execute(
        select(Finding.severity, func.count())
        .where(Finding.status == FindingStatus.OPEN)
        .group_by(Finding.severity)
    )
    counts = {severity: int(n) for severity, n in result.all()}
    return FindingsBySeverityOut(
        critical=0,
        high=counts.get(FindingSeverity.HIGH, 0),
        medium=counts.get(FindingSeverity.MEDIUM, 0),
        low=counts.get(FindingSeverity.LOW, 0),
        info=counts.get(FindingSeverity.INFO, 0),
    )


async def _load_recent_dns_activity(
    session: AsyncSession,
    *,
    since: datetime,
    limit: int,
) -> list[tuple[DnsActivity, DnsQuery]]:
    """Meaningful recent DNS: blocked or needs review, else recent attributed."""
    blocked = await session.execute(
        select(DnsActivity, DnsQuery)
        .join(DnsQuery, DnsQuery.id == DnsActivity.dns_query_id)
        .where(
            DnsActivity.queried_at >= since,
            DnsQuery.status == DnsQueryStatus.BLOCKED,
        )
        .order_by(DnsActivity.queried_at.desc())
        .limit(limit)
    )
    rows = list(blocked.all())
    if len(rows) >= limit:
        return rows[:limit]

    review = await session.execute(
        select(DnsActivity, DnsQuery)
        .join(DnsQuery, DnsQuery.id == DnsActivity.dns_query_id)
        .where(
            DnsActivity.queried_at >= since,
            DnsActivity.needs_review.is_(True),
        )
        .order_by(DnsActivity.queried_at.desc())
        .limit(limit)
    )
    seen = {activity.id for activity, _ in rows}
    for activity, query in review.all():
        if activity.id in seen:
            continue
        rows.append((activity, query))
        seen.add(activity.id)
        if len(rows) >= limit:
            return rows[:limit]

    attributed = await session.execute(
        select(DnsActivity, DnsQuery)
        .join(DnsQuery, DnsQuery.id == DnsActivity.dns_query_id)
        .where(
            DnsActivity.queried_at >= since,
            DnsActivity.status == CorrelationStatus.ATTRIBUTED,
        )
        .order_by(DnsActivity.queried_at.desc())
        .limit(limit)
    )
    for activity, query in attributed.all():
        if activity.id in seen:
            continue
        rows.append((activity, query))
        seen.add(activity.id)
        if len(rows) >= limit:
            break
    return rows[:limit]


async def _person_device_map(
    session: AsyncSession,
) -> dict[UUID, list[UUID]]:
    result = await session.execute(
        select(PersonDevice).where(PersonDevice.active.is_(True))
    )
    mapping: dict[UUID, list[UUID]] = {}
    for link in result.scalars().all():
        mapping.setdefault(link.person_id, []).append(link.device_id)
    return mapping


async def _latest_activity_by_device(
    session: AsyncSession,
    *,
    device_ids: set[UUID],
    since: datetime,
) -> dict[UUID, datetime]:
    if not device_ids:
        return {}
    result = await session.execute(
        select(DnsActivity.device_id, func.max(DnsActivity.queried_at))
        .where(
            DnsActivity.device_id.in_(device_ids),
            DnsActivity.queried_at >= since,
            DnsActivity.status == CorrelationStatus.ATTRIBUTED,
        )
        .group_by(DnsActivity.device_id)
    )
    return {
        device_id: at
        for device_id, at in result.all()
        if device_id is not None and at is not None
    }


async def _household_dns_today(
    session: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    result = await session.execute(
        select(DnsActivity, DnsQuery)
        .join(DnsQuery, DnsQuery.id == DnsActivity.dns_query_id)
        .where(
            DnsActivity.status == CorrelationStatus.ATTRIBUTED,
            DnsActivity.queried_at >= window_start,
            DnsActivity.queried_at <= window_end,
        )
    )
    records: list[DnsActivityRecord] = []
    for activity, query in result.all():
        if activity.device_id is None:
            continue
        records.append(
            DnsActivityRecord(
                queried_at=activity.queried_at,
                domain=query.domain,
                status=query.status,
                device_id=activity.device_id,
            )
        )
    return aggregate_dns_records(
        records,
        window_start=window_start,
        window_end=window_end,
        prior_domains=(),
    )


async def _household_unifi_today(
    session: AsyncSession,
    *,
    device_ids: set[UUID],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    records = await load_unifi_records(
        session,
        device_ids=device_ids,
        window_start=window_start,
        window_end=window_end,
    )
    return aggregate_unifi_traffic(records, device_ids=device_ids)


async def _child_baseline_means(
    session: AsyncSession,
    *,
    child_ids: Sequence[UUID],
    window: str,
) -> dict[str, float]:
    """Average baseline means across children that have a stored baseline."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for person_id in child_ids:
        row = await get_latest_baseline(
            session,
            subject_id=person_id,
            window=window,
        )
        if row is None:
            continue
        baseline = row_to_baseline(row)
        for name, mb in baseline.metrics.items():
            if mb.sample_count < 1:
                continue
            sums[name] = sums.get(name, 0.0) + mb.mean
            counts[name] = counts.get(name, 0) + 1
    return {
        name: sums[name] / counts[name]
        for name in sums
        if counts.get(name, 0) > 0
    }


def _count_health_device_attention(
    *,
    health_reports: Sequence[SourceHealthReport],
    unknown_unassigned: Sequence[_DeviceView],
) -> int:
    n = 0
    for report in health_reports:
        if report.status in (SourceHealthStatus.DOWN, SourceHealthStatus.DEGRADED):
            n += 1
    return n + len(unknown_unassigned)


async def build_dashboard_summary(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    cfg: Settings | None = None,
    attention_limit: int = DEFAULT_ATTENTION_LIMIT,
    recent_limit: int = DEFAULT_RECENT_ACTIVITY_LIMIT,
) -> DashboardSummaryOut:
    """Assemble the dashboard summary from live DB + source health."""
    cfg = cfg or settings
    at = now or datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)

    online_cutoff = at - timedelta(seconds=cfg.device_online_seconds)
    trend_start = at - timedelta(hours=24)
    activity_since = online_cutoff

    health_reports = await list_source_health(session, now=at, cfg=cfg, refresh=True)
    incomplete = incomplete_sources_from_health(health_reports)
    incomplete_set = set(incomplete)
    pihole_incomplete = IngestSource.PIHOLE_API in incomplete_set
    unifi_incomplete = IngestSource.UNIFI_API in incomplete_set

    device_views = await _load_device_views(session, online_cutoff=online_cutoff)
    online_views = [v for v in device_views if v.is_online]
    unknown_unassigned_views = [
        v for v in online_views if v.device.is_unknown or v.is_unassigned
    ]

    review_rows = await _load_review_rows(session, limit=attention_limit)
    review_total = await _count_review_items(session)
    attention_items = build_attention_items(
        health_reports=health_reports,
        review_rows=review_rows,
        unknown_unassigned=unknown_unassigned_views,
        limit=attention_limit,
    )
    attention_count = (
        _count_health_device_attention(
            health_reports=health_reports,
            unknown_unassigned=unknown_unassigned_views,
        )
        + review_total
    )

    status, status_reason = derive_household_status(
        incomplete_sources=incomplete,
        attention_items=attention_items,
        attention_count=attention_count,
    )

    if unifi_incomplete:
        online_devices = OnlineDevicesOut(incomplete=True, count=None, devices=[])
        unknown_unassigned = UnknownUnassignedOut(
            incomplete=True,
            count=None,
            devices=[],
        )
    else:
        online_devices = OnlineDevicesOut(
            incomplete=False,
            count=len(online_views),
            devices=[_to_device_out(v) for v in online_views],
        )
        unknown_unassigned = UnknownUnassignedOut(
            incomplete=False,
            count=len(unknown_unassigned_views),
            devices=[_to_device_out(v) for v in unknown_unassigned_views],
        )

    person_devices = await _person_device_map(session)
    child_result = await session.execute(
        select(Person)
        .where(Person.role == PersonRole.CHILD)
        .order_by(Person.name)
    )
    children = list(child_result.scalars().all())
    child_device_ids = {
        did for pid in (c.id for c in children) for did in person_devices.get(pid, [])
    }
    latest_dns = await _latest_activity_by_device(
        session,
        device_ids=child_device_ids,
        since=activity_since,
    )
    device_by_id = {v.device.id: v for v in device_views}

    active_children: list[ActiveChildOut] = []
    for child in children:
        device_ids = person_devices.get(child.id, [])
        last_at: datetime | None = None
        active_ids: list[UUID] = []
        for did in device_ids:
            view = device_by_id.get(did)
            dns_at = latest_dns.get(did)
            device_active = False
            if view is not None and view.is_online and not unifi_incomplete:
                device_active = True
                last_at = (
                    view.device.last_seen
                    if last_at is None or view.device.last_seen > last_at
                    else last_at
                )
            if dns_at is not None and not pihole_incomplete:
                device_active = True
                last_at = dns_at if last_at is None or dns_at > last_at else last_at
            if device_active:
                active_ids.append(did)
        if active_ids:
            active_children.append(
                ActiveChildOut(
                    person_id=child.id,
                    name=child.name,
                    role=child.role,
                    device_ids=active_ids,
                    last_activity_at=last_at,
                )
            )

    active_children_incomplete = pihole_incomplete or unifi_incomplete

    if pihole_incomplete:
        recent_activity = RecentActivityOut(incomplete=True, items=[])
    else:
        recent_rows = await _load_recent_dns_activity(
            session,
            since=activity_since,
            limit=recent_limit,
        )
        recent_items: list[RecentActivityItemOut] = []
        for activity, query in recent_rows:
            person_id = None
            person_name = None
            if activity.device_id is not None:
                view = device_by_id.get(activity.device_id)
                if view is not None:
                    person_id = view.person_id
                    person_name = view.person_name
            if activity.needs_review:
                kind: Literal[
                    "correlation_review", "blocked_dns", "attributed_dns"
                ] = "correlation_review"
                summary = f"Needs review: {query.domain}"
            elif query.status == DnsQueryStatus.BLOCKED:
                kind = "blocked_dns"
                who = f" ({person_name})" if person_name else ""
                summary = f"Blocked DNS lookup for {query.domain}{who}"
            else:
                kind = "attributed_dns"
                who = f" ({person_name})" if person_name else ""
                summary = f"DNS lookup for {query.domain}{who}"
            recent_items.append(
                RecentActivityItemOut(
                    kind=kind,
                    at=activity.queried_at,
                    summary=summary,
                    domain=query.domain,
                    device_id=activity.device_id,
                    person_id=person_id,
                    person_name=person_name,
                )
            )
        recent_activity = RecentActivityOut(incomplete=False, items=recent_items)

    incomplete_reasons: list[str] = []
    if pihole_incomplete:
        incomplete_reasons.append("pihole_api down — DNS trends unavailable")
    if unifi_incomplete:
        incomplete_reasons.append("unifi_api down — network trends unavailable")

    dns_today: dict[str, Any] | None = None
    if not pihole_incomplete:
        dns_today = await _household_dns_today(
            session,
            window_start=trend_start,
            window_end=at,
        )

    unifi_today: dict[str, Any] | None = None
    if not unifi_incomplete:
        all_device_ids = {v.device.id for v in device_views}
        unifi_today = await _household_unifi_today(
            session,
            device_ids=all_device_ids,
            window_start=trend_start,
            window_end=at,
        )

    baseline_means = await _child_baseline_means(
        session,
        child_ids=[c.id for c in children],
        window=TREND_WINDOW,
    )
    baseline_note = (
        None
        if baseline_means
        else "No child baselines stored yet — today values shown without comparison"
    )

    dns_trends = [
        _trend_metric(
            metric="dns_query_volume",
            today_value=(
                None if dns_today is None else float(dns_today["dns_query_volume"])
            ),
            baseline_mean=baseline_means.get("dns_query_volume"),
            incomplete=pihole_incomplete,
            note=baseline_note if not pihole_incomplete else "pihole_api down",
        ),
        _trend_metric(
            metric="blocked_query_pct",
            today_value=(
                None if dns_today is None else float(dns_today["blocked_query_pct"])
            ),
            baseline_mean=baseline_means.get("blocked_query_pct"),
            incomplete=pihole_incomplete,
            note=baseline_note if not pihole_incomplete else "pihole_api down",
        ),
        _trend_metric(
            metric="unique_domain_count",
            today_value=(
                None
                if dns_today is None
                else float(dns_today["unique_domain_count"])
            ),
            baseline_mean=baseline_means.get("unique_domain_count"),
            incomplete=pihole_incomplete,
            note=baseline_note if not pihole_incomplete else "pihole_api down",
        ),
    ]
    network_trends = [
        _trend_metric(
            metric="upload_bytes",
            today_value=(
                None
                if unifi_today is None or unifi_today["upload_bytes"] is None
                else float(unifi_today["upload_bytes"])
            ),
            baseline_mean=baseline_means.get("upload_bytes"),
            incomplete=unifi_incomplete,
            note="unifi_api down" if unifi_incomplete else baseline_note,
        ),
        _trend_metric(
            metric="download_bytes",
            today_value=(
                None
                if unifi_today is None or unifi_today["download_bytes"] is None
                else float(unifi_today["download_bytes"])
            ),
            baseline_mean=baseline_means.get("download_bytes"),
            incomplete=unifi_incomplete,
            note="unifi_api down" if unifi_incomplete else baseline_note,
        ),
    ]

    return DashboardSummaryOut(
        status=status,
        status_reason=status_reason,
        data_incomplete=bool(incomplete),
        incomplete_sources=list(incomplete),
        attention=AttentionOut(count=attention_count, items=attention_items),
        active_children=active_children,
        active_children_incomplete=active_children_incomplete,
        online_devices=online_devices,
        unknown_unassigned=unknown_unassigned,
        recent_activity=recent_activity,
        findings_by_severity=await _findings_by_severity(session),
        trends=TrendsOut(
            window=TREND_WINDOW,
            incomplete=bool(incomplete_reasons),
            incomplete_reasons=incomplete_reasons,
            dns=dns_trends,
            network=network_trends,
        ),
        data_health=DataHealthOut(sources=[_health_out(r) for r in health_reports]),
        generated_at=at,
        logic_version=DASHBOARD_LOGIC_VERSION,
    )
