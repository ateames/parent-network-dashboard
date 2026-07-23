"""Versioned time-aware correlation of Pi-hole DNS queries to durable devices.

Matching uses evidence AT QUERY TIME against ``ip_assignment`` history and
``device_identifier`` records. Attribution requires confidence above a
configurable threshold with no conflicting candidates — never guess.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.models.dns import DnsActivity, DnsQuery
from app.models.enums import CorrelationStatus, IdentifierKind
from app.models.identity import DeviceIdentifier, IpAssignment

LOGIC_VERSION = "dns_correlation.v1"

# Evidence weights (deterministic; combine by taking max among agreeing devices,
# then boosting when independent signals agree on the same device).
_WEIGHT_IP_ASSIGNMENT = Decimal("0.8000")
_WEIGHT_PIHOLE_CLIENT = Decimal("0.6000")
_WEIGHT_HOSTNAME = Decimal("0.5500")
_BOOST_IP_AND_CLIENT = Decimal("0.1500")
_BOOST_IP_AND_HOSTNAME = Decimal("0.1000")
_CONFIDENCE_CAP = Decimal("0.9900")
_ZERO = Decimal("0.0000")


@dataclass(frozen=True, slots=True)
class EvidenceMatch:
    """One time-aware identifier / IP match pointing at a device."""

    kind: str
    device_id: uuid.UUID
    weight: Decimal
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "device_id": str(self.device_id),
            "weight": str(self.weight),
            **self.detail,
        }


@dataclass(frozen=True, slots=True)
class ConflictRecord:
    """Conflicting evidence that blocks attribution."""

    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, **self.detail}


@dataclass(frozen=True, slots=True)
class CorrelationDecision:
    """Pure outcome before persistence."""

    dns_query_id: uuid.UUID
    queried_at: datetime
    device_id: uuid.UUID | None
    confidence: Decimal
    evidence: list[EvidenceMatch]
    conflicts: list[ConflictRecord]
    status: CorrelationStatus
    needs_review: bool


def combine_confidence(matches: Sequence[EvidenceMatch]) -> Decimal:
    """Score when all matches agree on one device (caller enforces that)."""
    if not matches:
        return _ZERO
    by_kind = {m.kind: m.weight for m in matches}
    base = max(by_kind.values())
    has_ip = "ip_assignment" in by_kind
    has_client = "pihole_client" in by_kind
    has_hostname = "hostname" in by_kind
    score = base
    if has_ip and has_client:
        score = max(score, base + _BOOST_IP_AND_CLIENT)
    if has_ip and has_hostname:
        score = max(score, base + _BOOST_IP_AND_HOSTNAME)
    if score > _CONFIDENCE_CAP:
        return _CONFIDENCE_CAP
    return score.quantize(Decimal("0.0001"))


def decide_attribution(
    *,
    dns_query_id: uuid.UUID,
    queried_at: datetime,
    matches: Sequence[EvidenceMatch],
    conflicts: Sequence[ConflictRecord],
    threshold: Decimal,
) -> CorrelationDecision:
    """Apply attribution rules — never pick among multiple candidates."""
    conflict_list = list(conflicts)
    match_list = list(matches)

    device_ids = {m.device_id for m in match_list}
    if len(device_ids) > 1:
        conflict_list.append(
            ConflictRecord(
                reason="multiple_candidate_devices",
                detail={
                    "device_ids": sorted(str(d) for d in device_ids),
                    "match_kinds": sorted({m.kind for m in match_list}),
                },
            )
        )

    if conflict_list:
        return CorrelationDecision(
            dns_query_id=dns_query_id,
            queried_at=queried_at,
            device_id=None,
            confidence=_ZERO,
            evidence=match_list,
            conflicts=conflict_list,
            status=CorrelationStatus.AMBIGUOUS,
            needs_review=True,
        )

    if len(device_ids) != 1:
        return CorrelationDecision(
            dns_query_id=dns_query_id,
            queried_at=queried_at,
            device_id=None,
            confidence=_ZERO,
            evidence=match_list,
            conflicts=[],
            status=CorrelationStatus.UNATTRIBUTED,
            needs_review=True,
        )

    device_id = next(iter(device_ids))
    confidence = combine_confidence(match_list)
    if confidence < threshold:
        return CorrelationDecision(
            dns_query_id=dns_query_id,
            queried_at=queried_at,
            device_id=None,
            confidence=confidence,
            evidence=match_list,
            conflicts=[],
            status=CorrelationStatus.UNATTRIBUTED,
            needs_review=True,
        )

    return CorrelationDecision(
        dns_query_id=dns_query_id,
        queried_at=queried_at,
        device_id=device_id,
        confidence=confidence,
        evidence=match_list,
        conflicts=[],
        status=CorrelationStatus.ATTRIBUTED,
        needs_review=False,
    )


def _assignment_covers(row: IpAssignment, at: datetime) -> bool:
    if row.observed_from > at:
        return False
    if row.observed_to is not None and row.observed_to <= at:
        return False
    return True


def _assignment_overlaps_window(
    row: IpAssignment,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    if row.observed_from > window_end:
        return False
    if row.observed_to is not None and row.observed_to <= window_start:
        return False
    return True


def _identifier_covers(row: DeviceIdentifier, at: datetime) -> bool:
    """Identifier binding is durable once observed; valid from first_seen onward."""
    return row.first_seen <= at


def window_ip_reassignment_conflicts(
    assignments: Sequence[IpAssignment],
    *,
    ips: set[str],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, ConflictRecord]:
    """Map IP → conflict when that IP was held by >1 device during the window."""
    by_ip: dict[str, set[uuid.UUID]] = {}
    assignment_ids: dict[str, list[str]] = {}
    for row in assignments:
        if row.ip not in ips:
            continue
        if not _assignment_overlaps_window(row, window_start, window_end):
            continue
        by_ip.setdefault(row.ip, set()).add(row.device_id)
        assignment_ids.setdefault(row.ip, []).append(str(row.id))

    conflicts: dict[str, ConflictRecord] = {}
    for ip, device_ids in by_ip.items():
        if len(device_ids) < 2:
            continue
        conflicts[ip] = ConflictRecord(
            reason="ip_reassigned_in_window",
            detail={
                "ip": ip,
                "device_ids": sorted(str(d) for d in device_ids),
                "assignment_ids": assignment_ids.get(ip, []),
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            },
        )
    return conflicts


async def _load_ip_assignments_for_ips(
    session: AsyncSession,
    ips: set[str],
) -> list[IpAssignment]:
    if not ips:
        return []
    result = await session.execute(
        select(IpAssignment).where(IpAssignment.ip.in_(ips))
    )
    return list(result.scalars().all())


async def _matches_for_query(
    session: AsyncSession,
    query: DnsQuery,
    *,
    ip_assignments: Sequence[IpAssignment],
) -> list[EvidenceMatch]:
    matches: list[EvidenceMatch] = []
    at = query.queried_at

    if query.client_ip:
        for row in ip_assignments:
            if row.ip != query.client_ip:
                continue
            if not _assignment_covers(row, at):
                continue
            matches.append(
                EvidenceMatch(
                    kind="ip_assignment",
                    device_id=row.device_id,
                    weight=_WEIGHT_IP_ASSIGNMENT,
                    detail={
                        "ip": row.ip,
                        "assignment_id": str(row.id),
                        "observed_from": row.observed_from.isoformat(),
                        "observed_to": (
                            row.observed_to.isoformat() if row.observed_to else None
                        ),
                        "source": row.source,
                    },
                )
            )

    identifier = query.client_identifier.strip()
    if identifier:
        result = await session.execute(
            select(DeviceIdentifier).where(
                DeviceIdentifier.value == identifier,
                DeviceIdentifier.kind.in_(
                    (IdentifierKind.PIHOLE_CLIENT, IdentifierKind.HOSTNAME)
                ),
            )
        )
        for row in result.scalars().all():
            if not _identifier_covers(row, at):
                continue
            kind = (
                "pihole_client"
                if row.kind == IdentifierKind.PIHOLE_CLIENT
                else "hostname"
            )
            weight = (
                _WEIGHT_PIHOLE_CLIENT
                if row.kind == IdentifierKind.PIHOLE_CLIENT
                else _WEIGHT_HOSTNAME
            )
            matches.append(
                EvidenceMatch(
                    kind=kind,
                    device_id=row.device_id,
                    weight=weight,
                    detail={
                        "identifier_id": str(row.id),
                        "value": row.value,
                        "first_seen": row.first_seen.isoformat(),
                        "last_seen": row.last_seen.isoformat(),
                    },
                )
            )

    return matches


def _decision_to_row(
    decision: CorrelationDecision,
    *,
    window_start: datetime,
    window_end: datetime,
) -> DnsActivity:
    evidence_payload: dict[str, Any] = {
        "matches": [m.as_dict() for m in decision.evidence],
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
    }
    conflicts_payload: dict[str, Any] = {
        "items": [c.as_dict() for c in decision.conflicts],
    }
    return DnsActivity(
        logic_version=LOGIC_VERSION,
        dns_query_id=decision.dns_query_id,
        device_id=decision.device_id,
        queried_at=decision.queried_at,
        confidence=decision.confidence,
        evidence=evidence_payload,
        conflicts=conflicts_payload,
        status=decision.status,
        needs_review=decision.needs_review,
    )


async def correlate_window(
    session: AsyncSession,
    queries: Sequence[DnsQuery],
    *,
    threshold: Decimal | float | None = None,
    cfg: Settings | None = None,
    persist: bool = True,
) -> list[DnsActivity]:
    """Correlate a window of DNS queries; optionally persist ``dns_activity`` rows.

    Window bounds are derived from the queries' ``queried_at`` range. IP
    reassignment anywhere in that range blocks attribution for queries using
    the contested IP.
    """
    cfg = cfg or settings
    if threshold is None:
        threshold_dec = Decimal(str(cfg.correlation_confidence_threshold))
    else:
        threshold_dec = Decimal(str(threshold))

    if not queries:
        return []

    ordered = sorted(queries, key=lambda q: (q.queried_at, str(q.id)))
    window_start = ordered[0].queried_at
    window_end = ordered[-1].queried_at

    ips = {q.client_ip for q in ordered if q.client_ip}
    ip_assignments = await _load_ip_assignments_for_ips(session, ips)
    ip_conflicts = window_ip_reassignment_conflicts(
        ip_assignments,
        ips=ips,
        window_start=window_start,
        window_end=window_end,
    )

    rows: list[DnsActivity] = []
    for query in ordered:
        matches = await _matches_for_query(
            session,
            query,
            ip_assignments=ip_assignments,
        )
        conflicts: list[ConflictRecord] = []
        if query.client_ip and query.client_ip in ip_conflicts:
            conflicts.append(ip_conflicts[query.client_ip])

        decision = decide_attribution(
            dns_query_id=query.id,
            queried_at=query.queried_at,
            matches=matches,
            conflicts=conflicts,
            threshold=threshold_dec,
        )
        row = _decision_to_row(
            decision,
            window_start=window_start,
            window_end=window_end,
        )
        rows.append(row)
        if persist:
            await _upsert_activity(session, row)

    if persist:
        await session.flush()
    return rows


async def _upsert_activity(session: AsyncSession, row: DnsActivity) -> None:
    """Replace prior row for same query + logic_version (replay-safe)."""
    result = await session.execute(
        select(DnsActivity).where(
            DnsActivity.dns_query_id == row.dns_query_id,
            DnsActivity.logic_version == row.logic_version,
        )
    )
    existing = result.scalars().first()
    if existing is None:
        session.add(row)
        return
    existing.device_id = row.device_id
    existing.queried_at = row.queried_at
    existing.confidence = row.confidence
    existing.evidence = row.evidence
    existing.conflicts = row.conflicts
    existing.status = row.status
    existing.needs_review = row.needs_review
    existing.logic_version = row.logic_version


async def correlate_time_range(
    session: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    threshold: Decimal | float | None = None,
    cfg: Settings | None = None,
    persist: bool = True,
) -> list[DnsActivity]:
    """Load DNS queries in ``[window_start, window_end]`` and correlate them."""
    result = await session.execute(
        select(DnsQuery)
        .where(
            and_(
                DnsQuery.queried_at >= window_start,
                DnsQuery.queried_at <= window_end,
            )
        )
        .order_by(DnsQuery.queried_at, DnsQuery.id)
    )
    queries = list(result.scalars().all())
    return await correlate_window(
        session,
        queries,
        threshold=threshold,
        cfg=cfg,
        persist=persist,
    )
