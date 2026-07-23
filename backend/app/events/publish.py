"""Persist + fan-out meaningful stream events (never raw DNS lines)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.bus import get_event_bus
from app.models.enums import FindingSeverity, StreamEventKind
from app.models.events import StreamEvent
from app.models.findings import Finding
from app.schemas.events import StreamEventOut

LOGIC_VERSION = "stream_events.v1"

# Map finding rule_id → stream event kind (1:1 for meaningful findings).
RULE_TO_EVENT_KIND: dict[str, StreamEventKind] = {
    "unknown_device_online": StreamEventKind.UNKNOWN_DEVICE_ONLINE,
    "blocked_query_burst": StreamEventKind.BLOCKED_QUERY_BURST,
    "dns_volume_increase": StreamEventKind.DNS_VOLUME_INCREASE,
    "activity_outside_expected_hours": StreamEventKind.ACTIVITY_OUTSIDE_EXPECTED_HOURS,
    "new_domain_burst": StreamEventKind.NEW_DOMAIN_BURST,
    "connection_flapping": StreamEventKind.CONNECTION_FLAPPING,
    "unifi_security_event": StreamEventKind.UNIFI_SECURITY_EVENT,
}


def event_from_row(row: StreamEvent) -> StreamEventOut:
    return StreamEventOut.model_validate(row)


async def publish_stream_event(
    session: AsyncSession,
    *,
    kind: StreamEventKind,
    severity: FindingSeverity,
    summary: str,
    finding_id: UUID | None = None,
    device_id: UUID | None = None,
    person_id: UUID | None = None,
    source: str | None = None,
    occurred_at: datetime | None = None,
    logic_version: str = LOGIC_VERSION,
    fanout: bool = True,
) -> StreamEventOut:
    """Insert a stream event and publish it on the in-process bus."""
    at = occurred_at or datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    row = StreamEvent(
        logic_version=logic_version,
        kind=kind,
        severity=severity,
        summary=summary,
        finding_id=finding_id,
        device_id=device_id,
        person_id=person_id,
        source=source,
        occurred_at=at,
    )
    session.add(row)
    await session.flush()
    event = event_from_row(row)
    if fanout:
        get_event_bus().publish(event)
    return event


async def publish_finding_created(
    session: AsyncSession,
    finding: Finding,
) -> StreamEventOut | None:
    """Publish a live event for a newly persisted finding (if mapped)."""
    kind = RULE_TO_EVENT_KIND.get(finding.rule_id)
    if kind is None:
        return None
    return await publish_stream_event(
        session,
        kind=kind,
        severity=finding.severity,
        summary=finding.summary,
        finding_id=finding.id,
        device_id=finding.device_id,
        person_id=finding.person_id,
        occurred_at=finding.occurred_at,
    )


async def publish_new_device(
    session: AsyncSession,
    *,
    device_id: UUID,
    display_name: str | None,
    is_unknown: bool,
    occurred_at: datetime,
) -> StreamEventOut:
    if display_name and display_name.strip():
        label = display_name.strip()
    else:
        label = "a device"
    summary = f"A new device joined the network ({label})."
    if is_unknown:
        summary = (
            f"A new unrecognized device joined the network ({label}). "
            "Confirm whether it belongs to the household."
        )
    return await publish_stream_event(
        session,
        kind=StreamEventKind.NEW_DEVICE_JOINED,
        severity=FindingSeverity.LOW if is_unknown else FindingSeverity.INFO,
        summary=summary,
        device_id=device_id,
        occurred_at=occurred_at,
    )


async def publish_source_data_loss(
    session: AsyncSession,
    *,
    source: str,
    detail: str,
    occurred_at: datetime | None = None,
) -> StreamEventOut:
    label = {
        "pihole_api": "Pi-hole",
        "unifi_api": "UniFi",
        "unifi_syslog": "UniFi syslog",
    }.get(source, source)
    summary = f"Loss of {label} data: {detail}"
    return await publish_stream_event(
        session,
        kind=StreamEventKind.SOURCE_DATA_LOSS,
        severity=FindingSeverity.HIGH,
        summary=summary,
        source=source,
        occurred_at=occurred_at,
    )


__all__ = [
    "LOGIC_VERSION",
    "RULE_TO_EVENT_KIND",
    "event_from_row",
    "publish_finding_created",
    "publish_new_device",
    "publish_source_data_loss",
    "publish_stream_event",
]
