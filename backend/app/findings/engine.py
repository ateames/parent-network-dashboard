"""Versioned deterministic findings engine — explainable rules, no ML.

Each rule produces a parent-readable finding with evidence, confidence,
severity, and a recommended action. Language never claims DNS proves content
was viewed.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.activity.aggregate import ActivitySummary
from app.activity.baseline import (
    BaselineResult,
    Deviation,
    detect_deviations,
    row_to_baseline,
)
from app.config import Settings, settings
from app.findings.feedback import matching_key_for_finding
from app.findings.phrasing import (
    assert_honest_dns_language,
    phrase_blocked_burst,
    phrase_dns_volume,
    subject_label,
)
from app.identity.resolver import normalize_mac
from app.models.activity import ActivityBaseline
from app.models.dns import DnsActivity, DnsQuery
from app.models.enums import (
    CorrelationStatus,
    DnsQueryStatus,
    FindingConfidence,
    FindingSeverity,
    FindingStatus,
    IdentifierKind,
)
from app.models.findings import Finding, FindingSuppression
from app.models.identity import Device
from app.models.people import PersonDevice
from app.models.raw import RawUnifiEvent, RawUnifiSyslog

LOGIC_VERSION = "findings.v1"

# --- Rule identifiers -------------------------------------------------------

RULE_UNKNOWN_DEVICE_ONLINE = "unknown_device_online"
RULE_BLOCKED_QUERY_BURST = "blocked_query_burst"
RULE_DNS_VOLUME_INCREASE = "dns_volume_increase"
RULE_ACTIVITY_OUTSIDE_HOURS = "activity_outside_expected_hours"
RULE_NEW_DOMAIN_BURST = "new_domain_burst"
RULE_CONNECTION_FLAPPING = "connection_flapping"
RULE_UNIFI_SECURITY_EVENT = "unifi_security_event"

ALL_RULE_IDS: tuple[str, ...] = (
    RULE_UNKNOWN_DEVICE_ONLINE,
    RULE_BLOCKED_QUERY_BURST,
    RULE_DNS_VOLUME_INCREASE,
    RULE_ACTIVITY_OUTSIDE_HOURS,
    RULE_NEW_DOMAIN_BURST,
    RULE_CONNECTION_FLAPPING,
    RULE_UNIFI_SECURITY_EVENT,
)

# --- Deterministic thresholds -----------------------------------------------

BLOCKED_BURST_MIN_COUNT = 5
BLOCKED_BURST_WINDOW = timedelta(minutes=15)

DNS_VOLUME_MIN_RATIO = 2.0
DNS_VOLUME_MIN_ABSOLUTE = 20

NEW_DOMAIN_BURST_MIN_COUNT = 8
NEW_DOMAIN_BURST_MIN_RATIO = 3.0

OUTSIDE_HOURS_MIN_LOOKUPS = 3

FLAP_MIN_TRANSITIONS = 6
FLAP_WINDOW = timedelta(minutes=30)

DEFAULT_EVAL_WINDOW = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class FindingDraft:
    """Pure finding outcome before persistence."""

    rule_id: str
    severity: FindingSeverity
    confidence: FindingConfidence
    title: str
    summary: str
    why_flagged: str
    recommended_action: str
    subject_label: str
    missing_info: tuple[str, ...]
    evidence: dict[str, Any]
    device_id: uuid.UUID | None
    person_id: uuid.UUID | None
    fingerprint: str
    occurred_at: datetime
    status: FindingStatus = FindingStatus.OPEN
    logic_version: str = LOGIC_VERSION

    def __post_init__(self) -> None:
        assert_honest_dns_language(
            self.title,
            self.summary,
            self.why_flagged,
            self.recommended_action,
            *self.missing_info,
        )


@dataclass(frozen=True, slots=True)
class DeviceContext:
    """Device + optional person for rule evaluation."""

    device_id: uuid.UUID
    display_name: str | None
    is_unknown: bool
    last_seen: datetime
    person_id: uuid.UUID | None
    person_name: str | None
    is_online: bool

    def label(self) -> str:
        return subject_label(
            person_name=self.person_name,
            device_name=self.display_name,
            device_id=self.device_id,
        )


@dataclass(frozen=True, slots=True)
class DnsLookupEvent:
    """One DNS lookup for burst / hour rules (pure / testable)."""

    queried_at: datetime
    domain: str
    status: DnsQueryStatus
    device_id: uuid.UUID | None
    person_id: uuid.UUID | None
    person_name: str | None
    device_name: str | None


@dataclass(frozen=True, slots=True)
class DnsSubjectStats:
    """Aggregated DNS stats for one device or unattributed bucket."""

    device_id: uuid.UUID | None
    person_id: uuid.UUID | None
    person_name: str | None
    device_name: str | None
    window_start: datetime
    window_end: datetime
    volume: int
    blocked_count: int
    new_domain_count: int
    new_domains: tuple[str, ...]
    active_hours_utc: tuple[int, ...]
    lookups: tuple[DnsLookupEvent, ...] = ()

    def label(self) -> str:
        return subject_label(
            person_name=self.person_name,
            device_name=self.device_name,
            device_id=self.device_id,
        )

    @property
    def blocked_pct(self) -> float:
        if self.volume <= 0:
            return 0.0
        return round(100.0 * self.blocked_count / self.volume, 4)


@dataclass(frozen=True, slots=True)
class ConnectionTransition:
    """Connect or disconnect observation for flapping detection."""

    at: datetime
    kind: Literal["connect", "disconnect"]
    mac: str | None
    device_id: uuid.UUID | None
    person_id: uuid.UUID | None
    person_name: str | None
    device_name: str | None
    event_name: str
    source: str


@dataclass(frozen=True, slots=True)
class SecuritySyslogEvent:
    """Parsed UniFi syslog line categorized as Security."""

    at: datetime
    event_name: str
    category: str
    sub_category: str | None
    msg: str | None
    mac: str | None
    client_ip: str | None
    device_id: uuid.UUID | None
    person_id: uuid.UUID | None
    person_name: str | None
    device_name: str | None
    raw_syslog_id: uuid.UUID | None = None
    severity_raw: Any = None


def _fingerprint(*parts: Any) -> str:
    return "|".join("" if p is None else str(p) for p in parts)


def _window_bucket(at: datetime, window: timedelta) -> datetime:
    """Floor ``at`` to the start of a fixed window for stable fingerprints."""
    epoch = int(at.astimezone(UTC).timestamp())
    seconds = int(window.total_seconds())
    return datetime.fromtimestamp((epoch // seconds) * seconds, tz=UTC)


# ---------------------------------------------------------------------------
# Rules (pure)
# ---------------------------------------------------------------------------


def rule_unknown_device_online(
    devices: Sequence[DeviceContext],
    *,
    now: datetime,
) -> list[FindingDraft]:
    """Flag unknown devices that appear online."""
    findings: list[FindingDraft] = []
    for device in devices:
        if not device.is_unknown or not device.is_online:
            continue
        label = device.label()
        title = "Unknown device online"
        summary = (
            f"An unrecognized device ({label}) was seen online "
            f"(last seen {device.last_seen.astimezone(UTC).isoformat()})."
        )
        why = (
            f"Rule {RULE_UNKNOWN_DEVICE_ONLINE}: device.is_unknown=true and "
            f"last_seen is within the online window "
            f"(last_seen={device.last_seen.astimezone(UTC).isoformat()})."
        )
        missing: list[str] = []
        if device.person_id is None:
            missing.append("No person assigned to this device")
        missing.append("Parent has not confirmed this device as known")
        action = (
            "Review the device, confirm whether it belongs to the household, "
            "and assign a person or mark it known."
        )
        draft = FindingDraft(
            rule_id=RULE_UNKNOWN_DEVICE_ONLINE,
            severity=FindingSeverity.MEDIUM,
            confidence=FindingConfidence.HIGH,
            title=title,
            summary=summary,
            why_flagged=why,
            recommended_action=action,
            subject_label=label,
            missing_info=tuple(missing),
            evidence={
                "rule_id": RULE_UNKNOWN_DEVICE_ONLINE,
                "device_id": str(device.device_id),
                "is_unknown": True,
                "is_online": True,
                "last_seen": device.last_seen.astimezone(UTC).isoformat(),
                "display_name": device.display_name,
                "person_id": str(device.person_id) if device.person_id else None,
            },
            device_id=device.device_id,
            person_id=device.person_id,
            fingerprint=_fingerprint(
                RULE_UNKNOWN_DEVICE_ONLINE,
                device.device_id,
                _window_bucket(now, timedelta(hours=1)).isoformat(),
            ),
            occurred_at=device.last_seen,
        )
        findings.append(draft)
    return findings


def rule_blocked_query_burst(
    lookups: Sequence[DnsLookupEvent],
    *,
    now: datetime,
    min_count: int = BLOCKED_BURST_MIN_COUNT,
    window: timedelta = BLOCKED_BURST_WINDOW,
) -> list[FindingDraft]:
    """Flag a burst of blocked DNS lookups in a short window."""
    blocked = sorted(
        (e for e in lookups if e.status == DnsQueryStatus.BLOCKED),
        key=lambda e: e.queried_at,
    )
    if len(blocked) < min_count:
        return []

    # Group by device (or unattributed).
    by_subject: dict[str, list[DnsLookupEvent]] = defaultdict(list)
    for event in blocked:
        key = str(event.device_id) if event.device_id else "unattributed"
        by_subject[key].append(event)

    findings: list[FindingDraft] = []
    for events in by_subject.values():
        events = sorted(events, key=lambda e: e.queried_at)
        best: tuple[DnsLookupEvent, ...] | None = None
        left = 0
        for right in range(len(events)):
            while events[right].queried_at - events[left].queried_at > window:
                left += 1
            span = tuple(events[left : right + 1])
            if len(span) >= min_count and (best is None or len(span) > len(best)):
                best = span
        if best is None:
            continue

        first = best[0]
        label = subject_label(
            person_name=first.person_name,
            device_name=first.device_name,
            device_id=first.device_id,
        )
        domains = sorted({e.domain for e in best})
        summary = phrase_blocked_burst(
            blocked_count=len(best),
            window_minutes=int(window.total_seconds() // 60),
            subject=label,
        )
        why = (
            f"Rule {RULE_BLOCKED_QUERY_BURST}: {len(best)} blocked DNS lookups "
            f"in {int(window.total_seconds() // 60)} minutes "
            f"(threshold>={min_count}). Sample domains: {', '.join(domains[:5])}."
        )
        missing: list[str] = []
        if first.device_id is None:
            missing.append("Device attribution unavailable for some lookups")
        if first.person_id is None:
            missing.append("No person assigned for this activity")
        missing.append(
            "DNS blocked status does not prove content was accessed"
        )
        draft = FindingDraft(
            rule_id=RULE_BLOCKED_QUERY_BURST,
            severity=FindingSeverity.MEDIUM,
            confidence=FindingConfidence.HIGH,
            title="Blocked DNS lookup burst",
            summary=summary,
            why_flagged=why,
            recommended_action=(
                "Review the blocked domains and confirm filter lists are intentional; "
                "talk with the household member if the pattern is unexpected."
            ),
            subject_label=label,
            missing_info=tuple(missing),
            evidence={
                "rule_id": RULE_BLOCKED_QUERY_BURST,
                "blocked_count": len(best),
                "window_minutes": int(window.total_seconds() // 60),
                "threshold_min_count": min_count,
                "domains": domains[:20],
                "first_at": best[0].queried_at.astimezone(UTC).isoformat(),
                "last_at": best[-1].queried_at.astimezone(UTC).isoformat(),
                "sample_lookups": [
                    {
                        "queried_at": e.queried_at.astimezone(UTC).isoformat(),
                        "domain": e.domain,
                        "status": e.status.value,
                    }
                    for e in best[:10]
                ],
            },
            device_id=first.device_id,
            person_id=first.person_id,
            fingerprint=_fingerprint(
                RULE_BLOCKED_QUERY_BURST,
                first.device_id or "unattributed",
                _window_bucket(best[0].queried_at, window).isoformat(),
            ),
            occurred_at=best[-1].queried_at,
        )
        findings.append(draft)
    return findings


def rule_dns_volume_increase(
    stats: DnsSubjectStats,
    *,
    baseline: BaselineResult | None,
    deviation: Deviation | None = None,
    min_ratio: float = DNS_VOLUME_MIN_RATIO,
    min_absolute: int = DNS_VOLUME_MIN_ABSOLUTE,
) -> FindingDraft | None:
    """Flag a large DNS lookup volume increase vs baseline mean."""
    if stats.volume < min_absolute:
        return None
    if baseline is None:
        return None
    mb = baseline.metrics.get("dns_query_volume")
    if mb is None or mb.sample_count < 1:
        return None

    mean = mb.mean
    if mean <= 0:
        ratio = float("inf") if stats.volume > 0 else 0.0
    else:
        ratio = stats.volume / mean

    z_triggered = deviation is not None and deviation.metric == "dns_query_volume"
    ratio_triggered = ratio >= min_ratio
    if not (z_triggered or ratio_triggered):
        return None

    label = stats.label()
    summary = (
        f"{phrase_dns_volume(stats.volume, subject=label)} in the recent window — "
        f"about {ratio:.1f}× the baseline mean of {mean:g}."
    )
    why = (
        f"Rule {RULE_DNS_VOLUME_INCREASE}: dns_query_volume={stats.volume} vs "
        f"baseline mean={mean:g} (stddev={mb.stddev:g}, ratio={ratio:.2f}, "
        f"min_ratio={min_ratio}, min_absolute={min_absolute})."
    )
    if deviation is not None:
        why += f" Deviation: {deviation.reason}"
    missing = [
        "DNS lookup volume does not prove specific content was accessed",
    ]
    if stats.person_id is None:
        missing.append("No person assigned for this activity")
    return FindingDraft(
        rule_id=RULE_DNS_VOLUME_INCREASE,
        severity=FindingSeverity.LOW if ratio < 4 else FindingSeverity.MEDIUM,
        confidence=(
            FindingConfidence.MEDIUM
            if mb.sample_count >= 3
            else FindingConfidence.LOW
        ),
        title="Large DNS lookup volume increase",
        summary=summary,
        why_flagged=why,
        recommended_action=(
            "Check which devices were active and whether a software update or "
            "background sync could explain the extra DNS lookups."
        ),
        subject_label=label,
        missing_info=tuple(missing),
        evidence={
            "rule_id": RULE_DNS_VOLUME_INCREASE,
            "dns_query_volume": stats.volume,
            "baseline_mean": mean,
            "baseline_stddev": mb.stddev,
            "ratio_vs_mean": round(ratio, 4) if ratio != float("inf") else None,
            "min_ratio": min_ratio,
            "min_absolute": min_absolute,
            "baseline_sample_count": mb.sample_count,
            "deviation": deviation.as_dict() if deviation else None,
            "window_start": stats.window_start.astimezone(UTC).isoformat(),
            "window_end": stats.window_end.astimezone(UTC).isoformat(),
        },
        device_id=stats.device_id,
        person_id=stats.person_id,
        fingerprint=_fingerprint(
            RULE_DNS_VOLUME_INCREASE,
            stats.device_id or stats.person_id or "unattributed",
            stats.window_start.astimezone(UTC).isoformat(),
            stats.window_end.astimezone(UTC).isoformat(),
        ),
        occurred_at=stats.window_end,
    )


def rule_activity_outside_expected_hours(
    stats: DnsSubjectStats,
    *,
    typical_hours_utc: Sequence[int],
    min_lookups: int = OUTSIDE_HOURS_MIN_LOOKUPS,
) -> FindingDraft | None:
    """Flag DNS activity in hours outside the subject's typical active hours."""
    if not typical_hours_utc:
        return None
    typical = {int(h) for h in typical_hours_utc if 0 <= int(h) <= 23}
    if not typical:
        return None

    outside = [
        e
        for e in stats.lookups
        if e.queried_at.astimezone(UTC).hour not in typical
    ]
    if len(outside) < min_lookups:
        return None

    hours = sorted({e.queried_at.astimezone(UTC).hour for e in outside})
    label = stats.label()
    summary = (
        f"{len(outside)} DNS lookups attributed to {label} occurred outside "
        f"typical active hours (UTC hours {hours})."
    )
    why = (
        f"Rule {RULE_ACTIVITY_OUTSIDE_HOURS}: {len(outside)} lookups in hours "
        f"{hours} while typical_active_hours_utc={sorted(typical)} "
        f"(threshold>={min_lookups} lookups)."
    )
    return FindingDraft(
        rule_id=RULE_ACTIVITY_OUTSIDE_HOURS,
        severity=FindingSeverity.LOW,
        confidence=FindingConfidence.MEDIUM,
        title="Activity outside expected hours",
        summary=summary,
        why_flagged=why,
        recommended_action=(
            "Confirm whether late/early network use was expected; "
            "adjust household expectations if the pattern is normal."
        ),
        subject_label=label,
        missing_info=(
            "Typical hours are statistical, not a household schedule",
            "DNS lookups do not prove specific content was accessed",
        ),
        evidence={
            "rule_id": RULE_ACTIVITY_OUTSIDE_HOURS,
            "outside_lookup_count": len(outside),
            "outside_hours_utc": hours,
            "typical_active_hours_utc": sorted(typical),
            "threshold_min_lookups": min_lookups,
            "sample_lookups": [
                {
                    "queried_at": e.queried_at.astimezone(UTC).isoformat(),
                    "domain": e.domain,
                    "hour_utc": e.queried_at.astimezone(UTC).hour,
                }
                for e in outside[:10]
            ],
        },
        device_id=stats.device_id,
        person_id=stats.person_id,
        fingerprint=_fingerprint(
            RULE_ACTIVITY_OUTSIDE_HOURS,
            stats.device_id or stats.person_id or "unattributed",
            stats.window_start.astimezone(UTC).isoformat(),
        ),
        occurred_at=outside[-1].queried_at,
    )


def rule_new_domain_burst(
    stats: DnsSubjectStats,
    *,
    baseline: BaselineResult | None,
    min_count: int = NEW_DOMAIN_BURST_MIN_COUNT,
    min_ratio: float = NEW_DOMAIN_BURST_MIN_RATIO,
) -> FindingDraft | None:
    """Flag many newly seen domains in a window."""
    if stats.new_domain_count < min_count:
        return None

    mean = 0.0
    ratio = float("inf")
    if baseline is not None:
        mb = baseline.metrics.get("new_domain_count")
        if mb is not None and mb.sample_count >= 1:
            mean = mb.mean
            ratio = (
                float("inf")
                if mean <= 0 and stats.new_domain_count > 0
                else (stats.new_domain_count / mean if mean > 0 else 0.0)
            )
            if mean > 0 and ratio < min_ratio:
                return None

    label = stats.label()
    sample = list(stats.new_domains[:8])
    summary = (
        f"{stats.new_domain_count} newly seen domains appeared in DNS lookups "
        f"attributed to {label}"
        + (f" (sample: {', '.join(sample)})" if sample else ".")
    )
    if not summary.endswith("."):
        summary += "."
    why = (
        f"Rule {RULE_NEW_DOMAIN_BURST}: new_domain_count={stats.new_domain_count} "
        f"(threshold>={min_count}"
        + (
            f", baseline_mean={mean:g}, ratio={ratio:.2f}, min_ratio={min_ratio}"
            if baseline is not None and mean > 0
            else ""
        )
        + ")."
    )
    return FindingDraft(
        rule_id=RULE_NEW_DOMAIN_BURST,
        severity=FindingSeverity.LOW,
        confidence=FindingConfidence.MEDIUM,
        title="New domain burst",
        summary=summary,
        why_flagged=why,
        recommended_action=(
            "Scan the new domain list for unexpected destinations; "
            "a DNS lookup only shows a name was requested, not that content loaded."
        ),
        subject_label=label,
        missing_info=(
            "New-domain detection depends on prior history completeness",
            "DNS lookups do not prove specific content was accessed",
        ),
        evidence={
            "rule_id": RULE_NEW_DOMAIN_BURST,
            "new_domain_count": stats.new_domain_count,
            "new_domains": list(stats.new_domains[:30]),
            "threshold_min_count": min_count,
            "baseline_mean": mean if baseline is not None else None,
            "ratio_vs_mean": (
                None
                if ratio == float("inf")
                else round(ratio, 4) if baseline is not None and mean > 0 else None
            ),
            "window_start": stats.window_start.astimezone(UTC).isoformat(),
            "window_end": stats.window_end.astimezone(UTC).isoformat(),
        },
        device_id=stats.device_id,
        person_id=stats.person_id,
        fingerprint=_fingerprint(
            RULE_NEW_DOMAIN_BURST,
            stats.device_id or stats.person_id or "unattributed",
            stats.window_start.astimezone(UTC).isoformat(),
        ),
        occurred_at=stats.window_end,
    )


def rule_connection_flapping(
    transitions: Sequence[ConnectionTransition],
    *,
    min_transitions: int = FLAP_MIN_TRANSITIONS,
    window: timedelta = FLAP_WINDOW,
) -> list[FindingDraft]:
    """Flag repeated connect/disconnect cycles (Wi‑Fi flapping)."""
    by_key: dict[str, list[ConnectionTransition]] = defaultdict(list)
    for event in transitions:
        key = (
            str(event.device_id)
            if event.device_id is not None
            else (event.mac or "unknown")
        )
        by_key[key].append(event)

    findings: list[FindingDraft] = []
    for events in by_key.values():
        events = sorted(events, key=lambda e: e.at)
        best: tuple[ConnectionTransition, ...] | None = None
        left = 0
        for right in range(len(events)):
            while events[right].at - events[left].at > window:
                left += 1
            span = tuple(events[left : right + 1])
            if len(span) >= min_transitions and (best is None or len(span) > len(best)):
                best = span
        if best is None:
            continue
        connects = sum(1 for e in best if e.kind == "connect")
        disconnects = sum(1 for e in best if e.kind == "disconnect")
        if connects < 1 or disconnects < 1:
            continue
        first = best[0]
        label = subject_label(
            person_name=first.person_name,
            device_name=first.device_name,
            device_id=first.device_id,
        )
        if label == "unattributed" and first.mac:
            label = f"MAC {first.mac}"
        summary = (
            f"Device {label} connected/disconnected {len(best)} times within "
            f"{int(window.total_seconds() // 60)} minutes "
            f"({connects} connects, {disconnects} disconnects)."
        )
        why = (
            f"Rule {RULE_CONNECTION_FLAPPING}: {len(best)} connect/disconnect "
            f"transitions in {int(window.total_seconds() // 60)} minutes "
            f"(threshold>={min_transitions})."
        )
        findings.append(
            FindingDraft(
                rule_id=RULE_CONNECTION_FLAPPING,
                severity=FindingSeverity.LOW,
                confidence=FindingConfidence.HIGH,
                title="Repeated connect/disconnect (flapping)",
                summary=summary,
                why_flagged=why,
                recommended_action=(
                    "Check Wi‑Fi signal, AP placement, or a flaky client; "
                    "no content-viewing claim is implied."
                ),
                subject_label=label if first.device_id or first.person_name else (
                    f"MAC {first.mac}" if first.mac else "unattributed"
                ),
                missing_info=tuple(
                    m
                    for m in (
                        None
                        if first.device_id
                        else "Could not map MAC to a durable device",
                        None
                        if first.person_id
                        else "No person assigned for this device",
                    )
                    if m
                ),
                evidence={
                    "rule_id": RULE_CONNECTION_FLAPPING,
                    "transition_count": len(best),
                    "connect_count": connects,
                    "disconnect_count": disconnects,
                    "window_minutes": int(window.total_seconds() // 60),
                    "threshold_min_transitions": min_transitions,
                    "mac": first.mac,
                    "transitions": [
                        {
                            "at": e.at.astimezone(UTC).isoformat(),
                            "kind": e.kind,
                            "event_name": e.event_name,
                            "source": e.source,
                        }
                        for e in best[:20]
                    ],
                },
                device_id=first.device_id,
                person_id=first.person_id,
                fingerprint=_fingerprint(
                    RULE_CONNECTION_FLAPPING,
                    first.device_id or first.mac or "unattributed",
                    _window_bucket(best[0].at, window).isoformat(),
                ),
                occurred_at=best[-1].at,
            )
        )
    return findings


def rule_unifi_security_event(
    events: Sequence[SecuritySyslogEvent],
) -> list[FindingDraft]:
    """Flag UniFi syslog lines categorized as Security."""
    findings: list[FindingDraft] = []
    for event in events:
        if (event.category or "").lower() != "security":
            continue
        label = subject_label(
            person_name=event.person_name,
            device_name=event.device_name,
            device_id=event.device_id,
        )
        if label == "unattributed" and event.mac:
            label = f"MAC {event.mac}"
        elif label == "unattributed" and event.client_ip:
            label = f"IP {event.client_ip}"
        msg = (event.msg or event.event_name or "security event").strip()
        summary = f"UniFi security event for {label}: {msg}"
        why = (
            f"Rule {RULE_UNIFI_SECURITY_EVENT}: syslog category=Security "
            f"(event_name={event.event_name!r}, "
            f"sub_category={event.sub_category!r})."
        )
        missing: list[str] = []
        if event.device_id is None:
            missing.append("Client could not be mapped to a durable device")
        if event.person_id is None:
            missing.append("No person assigned for this client")
        findings.append(
            FindingDraft(
                rule_id=RULE_UNIFI_SECURITY_EVENT,
                severity=FindingSeverity.HIGH,
                confidence=FindingConfidence.HIGH,
                title="UniFi security event",
                summary=summary,
                why_flagged=why,
                recommended_action=(
                    "Review the UniFi security/threat details and confirm the "
                    "affected device; escalate if the event is unexpected."
                ),
                subject_label=label,
        missing_info=tuple(missing),
        evidence={
            "rule_id": RULE_UNIFI_SECURITY_EVENT,
                    "event_name": event.event_name,
                    "category": event.category,
                    "sub_category": event.sub_category,
                    "msg": event.msg,
                    "mac": event.mac,
                    "client_ip": event.client_ip,
                    "severity_raw": event.severity_raw,
                    "at": event.at.astimezone(UTC).isoformat(),
                    "raw_syslog_id": (
                        str(event.raw_syslog_id) if event.raw_syslog_id else None
                    ),
                },
                device_id=event.device_id,
                person_id=event.person_id,
                fingerprint=_fingerprint(
                    RULE_UNIFI_SECURITY_EVENT,
                    event.raw_syslog_id
                    or f"{event.at.isoformat()}:{event.event_name}:{event.mac}",
                ),
                occurred_at=event.at,
            )
        )
    return findings


def evaluate_rules(
    *,
    devices: Sequence[DeviceContext] = (),
    lookups: Sequence[DnsLookupEvent] = (),
    subject_stats: Sequence[DnsSubjectStats] = (),
    baselines: dict[uuid.UUID, BaselineResult] | None = None,
    deviations: dict[uuid.UUID, list[Deviation]] | None = None,
    transitions: Sequence[ConnectionTransition] = (),
    security_events: Sequence[SecuritySyslogEvent] = (),
    now: datetime | None = None,
) -> list[FindingDraft]:
    """Run all deterministic rules over in-memory inputs."""
    at = now or datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    baselines = baselines or {}
    deviations = deviations or {}

    findings: list[FindingDraft] = []
    findings.extend(rule_unknown_device_online(devices, now=at))
    findings.extend(rule_blocked_query_burst(lookups, now=at))
    findings.extend(rule_connection_flapping(transitions))
    findings.extend(rule_unifi_security_event(security_events))

    for stats in subject_stats:
        subject_key = stats.device_id or stats.person_id
        baseline = baselines.get(subject_key) if subject_key else None
        devs = deviations.get(subject_key, []) if subject_key else []
        volume_dev = next(
            (d for d in devs if d.metric == "dns_query_volume"),
            None,
        )
        draft = rule_dns_volume_increase(
            stats,
            baseline=baseline,
            deviation=volume_dev,
        )
        if draft is not None:
            findings.append(draft)

        typical = (
            baseline.typical_active_hours_utc if baseline is not None else ()
        )
        outside = rule_activity_outside_expected_hours(
            stats,
            typical_hours_utc=typical,
        )
        if outside is not None:
            findings.append(outside)

        new_domains = rule_new_domain_burst(stats, baseline=baseline)
        if new_domains is not None:
            findings.append(new_domains)

    findings.sort(key=lambda f: (f.occurred_at, f.rule_id, f.fingerprint))
    return findings


# ---------------------------------------------------------------------------
# Persistence + DB evaluation
# ---------------------------------------------------------------------------


def draft_to_row(
    draft: FindingDraft,
    *,
    detected_at: datetime | None = None,
) -> Finding:
    at = detected_at or datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return Finding(
        logic_version=draft.logic_version,
        rule_id=draft.rule_id,
        severity=draft.severity,
        status=draft.status,
        confidence=draft.confidence,
        title=draft.title,
        summary=draft.summary,
        why_flagged=draft.why_flagged,
        recommended_action=draft.recommended_action,
        subject_label=draft.subject_label,
        missing_info=list(draft.missing_info),
        evidence=dict(draft.evidence),
        device_id=draft.device_id,
        person_id=draft.person_id,
        fingerprint=draft.fingerprint,
        occurred_at=draft.occurred_at,
        detected_at=at,
    )


async def upsert_finding(session: AsyncSession, draft: FindingDraft) -> Finding:
    """Insert or refresh a finding for the same fingerprint + logic_version."""
    result = await session.execute(
        select(Finding).where(
            Finding.fingerprint == draft.fingerprint,
            Finding.logic_version == draft.logic_version,
        )
    )
    existing = result.scalars().first()
    if existing is None:
        row = draft_to_row(draft)
        session.add(row)
        await session.flush()
        return row

    # Do not reopen dismissed/resolved findings on replay.
    if existing.status in (FindingStatus.DISMISSED, FindingStatus.RESOLVED):
        return existing

    existing.severity = draft.severity
    existing.confidence = draft.confidence
    existing.title = draft.title
    existing.summary = draft.summary
    existing.why_flagged = draft.why_flagged
    existing.recommended_action = draft.recommended_action
    existing.subject_label = draft.subject_label
    existing.missing_info = list(draft.missing_info)
    existing.evidence = dict(draft.evidence)
    existing.device_id = draft.device_id
    existing.person_id = draft.person_id
    existing.occurred_at = draft.occurred_at
    existing.detected_at = datetime.now(UTC)
    await session.flush()
    return existing


def _classify_transition_kind(
    event_name: str,
    msg: str | None = None,
) -> Literal["connect", "disconnect", "other"]:
    text = f"{event_name} {msg or ''}".lower()
    if "disconnect" in text or "disassociat" in text:
        return "disconnect"
    if "connect" in text or "associat" in text:
        return "connect"
    return "other"


async def _load_device_contexts(
    session: AsyncSession,
    *,
    now: datetime,
    online_seconds: int,
) -> tuple[
    list[DeviceContext],
    dict[str, DeviceContext],
    dict[uuid.UUID, DeviceContext],
]:
    cutoff = now - timedelta(seconds=online_seconds)
    result = await session.execute(
        select(Device)
        .options(
            selectinload(Device.person_links).selectinload(PersonDevice.person),
            selectinload(Device.identifiers),
        )
        .order_by(Device.last_seen.desc())
    )
    devices = list(result.scalars().unique().all())
    contexts: list[DeviceContext] = []
    by_mac: dict[str, DeviceContext] = {}
    by_id: dict[uuid.UUID, DeviceContext] = {}
    for device in devices:
        person_id = None
        person_name = None
        for link in device.person_links:
            if link.active and link.person is not None:
                person_id = link.person.id
                person_name = link.person.name
                break
        ctx = DeviceContext(
            device_id=device.id,
            display_name=device.display_name,
            is_unknown=device.is_unknown,
            last_seen=device.last_seen,
            person_id=person_id,
            person_name=person_name,
            is_online=device.last_seen >= cutoff,
        )
        contexts.append(ctx)
        by_id[device.id] = ctx
        for ident in device.identifiers:
            if ident.kind == IdentifierKind.MAC:
                by_mac[normalize_mac(ident.value)] = ctx
    return contexts, by_mac, by_id


async def _load_lookups(
    session: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    by_device: dict[uuid.UUID, DeviceContext],
) -> list[DnsLookupEvent]:
    result = await session.execute(
        select(DnsActivity, DnsQuery)
        .join(DnsQuery, DnsQuery.id == DnsActivity.dns_query_id)
        .where(
            and_(
                DnsActivity.queried_at >= window_start,
                DnsActivity.queried_at <= window_end,
            )
        )
        .order_by(DnsActivity.queried_at)
    )
    events: list[DnsLookupEvent] = []
    for activity, query in result.all():
        ctx = by_device.get(activity.device_id) if activity.device_id else None
        # Prefer attributed rows; still include unattributed for burst rules.
        if (
            activity.status != CorrelationStatus.ATTRIBUTED
            and activity.device_id is not None
        ):
            # Ambiguous with a guessed device id should not attribute to a person.
            ctx = None
        events.append(
            DnsLookupEvent(
                queried_at=activity.queried_at,
                domain=query.domain,
                status=query.status,
                device_id=(
                    activity.device_id
                    if activity.status == CorrelationStatus.ATTRIBUTED
                    else None
                ),
                person_id=ctx.person_id if ctx else None,
                person_name=ctx.person_name if ctx else None,
                device_name=ctx.display_name if ctx else None,
            )
        )
    return events


def _build_subject_stats(
    lookups: Sequence[DnsLookupEvent],
    *,
    window_start: datetime,
    window_end: datetime,
    prior_domains_by_device: dict[uuid.UUID, set[str]],
) -> list[DnsSubjectStats]:
    by_device: dict[uuid.UUID | None, list[DnsLookupEvent]] = defaultdict(list)
    for event in lookups:
        by_device[event.device_id].append(event)

    stats_list: list[DnsSubjectStats] = []
    for device_id, events in by_device.items():
        if device_id is None:
            # Unattributed aggregate — useful for bursts already handled per-event.
            continue
        domains = {e.domain.strip().lower().rstrip(".") for e in events if e.domain}
        prior = prior_domains_by_device.get(device_id, set())
        new_domains = tuple(sorted(d for d in domains if d not in prior))
        hours = tuple(sorted({e.queried_at.astimezone(UTC).hour for e in events}))
        first = events[0]
        stats_list.append(
            DnsSubjectStats(
                device_id=device_id,
                person_id=first.person_id,
                person_name=first.person_name,
                device_name=first.device_name,
                window_start=window_start,
                window_end=window_end,
                volume=len(events),
                blocked_count=sum(
                    1 for e in events if e.status == DnsQueryStatus.BLOCKED
                ),
                new_domain_count=len(new_domains),
                new_domains=new_domains,
                active_hours_utc=hours,
                lookups=tuple(events),
            )
        )
    return stats_list


async def _load_prior_domains(
    session: AsyncSession,
    *,
    device_ids: set[uuid.UUID],
    before: datetime,
) -> dict[uuid.UUID, set[str]]:
    if not device_ids:
        return {}
    result = await session.execute(
        select(DnsActivity.device_id, DnsQuery.domain)
        .join(DnsQuery, DnsQuery.id == DnsActivity.dns_query_id)
        .where(
            DnsActivity.device_id.in_(device_ids),
            DnsActivity.queried_at < before,
            DnsActivity.status == CorrelationStatus.ATTRIBUTED,
        )
    )
    mapping: dict[uuid.UUID, set[str]] = defaultdict(set)
    for device_id, domain in result.all():
        if device_id is None or not domain:
            continue
        mapping[device_id].add(domain.strip().lower().rstrip("."))
    return mapping


async def _load_baselines(
    session: AsyncSession,
    subject_ids: set[uuid.UUID],
    *,
    window: str = "24h",
) -> dict[uuid.UUID, BaselineResult]:
    out: dict[uuid.UUID, BaselineResult] = {}
    for subject_id in subject_ids:
        result = await session.execute(
            select(ActivityBaseline)
            .where(
                ActivityBaseline.subject_id == subject_id,
                ActivityBaseline.window == window,
            )
            .order_by(ActivityBaseline.computed_at.desc())
            .limit(1)
        )
        row = result.scalars().first()
        if row is not None:
            out[subject_id] = row_to_baseline(row)
    return out


def _transition_from_payload(
    *,
    at: datetime,
    event_name: str,
    msg: str | None,
    mac: str | None,
    source: str,
    by_mac: dict[str, DeviceContext],
) -> ConnectionTransition | None:
    kind = _classify_transition_kind(event_name, msg)
    if kind == "other":
        return None
    ctx = by_mac.get(normalize_mac(mac)) if mac else None
    return ConnectionTransition(
        at=at,
        kind=kind,
        mac=normalize_mac(mac) if mac else None,
        device_id=ctx.device_id if ctx else None,
        person_id=ctx.person_id if ctx else None,
        person_name=ctx.person_name if ctx else None,
        device_name=ctx.display_name if ctx else None,
        event_name=event_name,
        source=source,
    )


async def _load_transitions(
    session: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    by_mac: dict[str, DeviceContext],
) -> list[ConnectionTransition]:
    transitions: list[ConnectionTransition] = []

    syslog_rows = await session.execute(
        select(RawUnifiSyslog).where(
            and_(
                RawUnifiSyslog.ingested_at >= window_start,
                RawUnifiSyslog.ingested_at <= window_end,
            )
        )
    )
    for row in syslog_rows.scalars().all():
        parsed = row.parsed or {}
        event_name = str(parsed.get("event_name") or "")
        mac = parsed.get("mac")
        msg = parsed.get("msg")
        t = _transition_from_payload(
            at=row.ingested_at,
            event_name=event_name,
            msg=msg if isinstance(msg, str) else None,
            mac=mac if isinstance(mac, str) else None,
            source="unifi_syslog",
            by_mac=by_mac,
        )
        if t is not None:
            transitions.append(t)

    event_rows = await session.execute(
        select(RawUnifiEvent).where(
            and_(
                RawUnifiEvent.ingested_at >= window_start,
                RawUnifiEvent.ingested_at <= window_end,
            )
        )
    )
    for row in event_rows.scalars().all():
        payload = row.payload or {}
        event_name = str(payload.get("key") or payload.get("event_name") or "")
        mac = payload.get("mac")
        msg = payload.get("msg")
        # Prefer controller event timestamp when present.
        at = row.ingested_at
        if isinstance(payload.get("time"), int | float):
            at = datetime.fromtimestamp(float(payload["time"]), tz=UTC)
        elif isinstance(payload.get("datetime"), str):
            try:
                at = datetime.fromisoformat(
                    payload["datetime"].replace("Z", "+00:00")
                )
            except ValueError:
                pass
        t = _transition_from_payload(
            at=at,
            event_name=event_name,
            msg=msg if isinstance(msg, str) else None,
            mac=mac if isinstance(mac, str) else None,
            source="unifi_event",
            by_mac=by_mac,
        )
        if t is not None:
            transitions.append(t)

    transitions.sort(key=lambda e: e.at)
    return transitions


async def _load_security_events(
    session: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    by_mac: dict[str, DeviceContext],
) -> list[SecuritySyslogEvent]:
    result = await session.execute(
        select(RawUnifiSyslog).where(
            and_(
                RawUnifiSyslog.ingested_at >= window_start,
                RawUnifiSyslog.ingested_at <= window_end,
                RawUnifiSyslog.parsed.is_not(None),
            )
        )
    )
    events: list[SecuritySyslogEvent] = []
    for row in result.scalars().all():
        parsed = row.parsed or {}
        category = parsed.get("category")
        if not isinstance(category, str) or category.lower() != "security":
            continue
        mac = parsed.get("mac") if isinstance(parsed.get("mac"), str) else None
        ctx = by_mac.get(normalize_mac(mac)) if mac else None
        events.append(
            SecuritySyslogEvent(
                at=row.ingested_at,
                event_name=str(parsed.get("event_name") or "security_event"),
                category=category,
                sub_category=(
                    str(parsed["sub_category"])
                    if parsed.get("sub_category") is not None
                    else None
                ),
                msg=parsed.get("msg") if isinstance(parsed.get("msg"), str) else None,
                mac=normalize_mac(mac) if mac else None,
                client_ip=(
                    parsed.get("client_ip")
                    if isinstance(parsed.get("client_ip"), str)
                    else None
                ),
                device_id=ctx.device_id if ctx else None,
                person_id=ctx.person_id if ctx else None,
                person_name=ctx.person_name if ctx else None,
                device_name=ctx.display_name if ctx else None,
                raw_syslog_id=row.id,
                severity_raw=parsed.get("severity"),
            )
        )
    return events


async def load_suppression_keys(session: AsyncSession) -> set[str]:
    """Return active suppression matching keys."""
    result = await session.execute(select(FindingSuppression.matching_key))
    return {row[0] for row in result.all()}


def filter_suppressed_drafts(
    drafts: Sequence[FindingDraft],
    suppression_keys: set[str],
) -> list[FindingDraft]:
    """Drop drafts whose matching key is actively suppressed."""
    if not suppression_keys:
        return list(drafts)
    kept: list[FindingDraft] = []
    for draft in drafts:
        key, _ = matching_key_for_finding(draft)
        if key in suppression_keys:
            continue
        kept.append(draft)
    return kept


async def evaluate_and_persist(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    cfg: Settings | None = None,
    window: timedelta = DEFAULT_EVAL_WINDOW,
    persist: bool = True,
) -> list[FindingDraft]:
    """Load recent household signals, run rules, optionally persist findings."""
    cfg = cfg or settings
    at = now or datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    window_start = at - window

    devices, by_mac, by_id = await _load_device_contexts(
        session,
        now=at,
        online_seconds=cfg.device_online_seconds,
    )
    lookups = await _load_lookups(
        session,
        window_start=window_start,
        window_end=at,
        by_device=by_id,
    )
    device_ids = {d.device_id for d in devices}
    prior = await _load_prior_domains(
        session,
        device_ids=device_ids,
        before=window_start,
    )
    subject_stats = _build_subject_stats(
        lookups,
        window_start=window_start,
        window_end=at,
        prior_domains_by_device=prior,
    )
    baselines = await _load_baselines(
        session,
        {s.device_id for s in subject_stats if s.device_id is not None},
        window="24h",
    )
    # Deviations are optional; volume rule also uses ratio vs mean.
    deviations: dict[uuid.UUID, list[Deviation]] = {}
    for stats in subject_stats:
        if stats.device_id is None or stats.device_id not in baselines:
            continue
        summary = ActivitySummary(
            subject_type="device",
            subject_id=stats.device_id,
            window_start=stats.window_start,
            window_end=stats.window_end,
            dns_query_volume=stats.volume,
            blocked_query_count=stats.blocked_count,
            blocked_query_pct=stats.blocked_pct,
            unique_domain_count=len({e.domain for e in stats.lookups}),
            new_domain_count=stats.new_domain_count,
            active_hour_count=len(stats.active_hours_utc),
            active_hours_utc=stats.active_hours_utc,
            upload_bytes=None,
            download_bytes=None,
            connection_duration_seconds=None,
        )
        deviations[stats.device_id] = detect_deviations(
            summary,
            baselines[stats.device_id],
        )

    transitions = await _load_transitions(
        session,
        window_start=window_start,
        window_end=at,
        by_mac=by_mac,
    )
    security_events = await _load_security_events(
        session,
        window_start=window_start,
        window_end=at,
        by_mac=by_mac,
    )

    drafts = evaluate_rules(
        devices=devices,
        lookups=lookups,
        subject_stats=subject_stats,
        baselines=baselines,
        deviations=deviations,
        transitions=transitions,
        security_events=security_events,
        now=at,
    )
    suppression_keys = await load_suppression_keys(session)
    drafts = filter_suppressed_drafts(drafts, suppression_keys)
    if persist:
        for draft in drafts:
            await upsert_finding(session, draft)
        await session.flush()
    return drafts
