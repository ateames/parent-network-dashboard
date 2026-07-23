"""Versioned durable device identity from Pi-hole / UniFi client observations.

Matching priority:
1. MAC — strong; same MAC => same device
2. UniFi client id — strong; same id => same device
3. Hostname — weak evidence only (stored, never used to merge)
4. IP — never used to merge; ``ip_assignment`` is the IP-over-time truth

Devices without a strong identifier (MAC or UniFi client id) are flagged
``is_unknown=true``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import IdentifierKind
from app.models.identity import Device, DeviceIdentifier, IpAssignment

logger = logging.getLogger(__name__)

LOGIC_VERSION = "device_identity.v1"

STRONG_IDENTIFIER_KINDS: frozenset[IdentifierKind] = frozenset(
    {
        IdentifierKind.MAC,
        IdentifierKind.UNIFI_CLIENT_ID,
    }
)

_MAC_RE = re.compile(r"[^0-9a-fA-F]")

_CONFIDENCE_MAC = Decimal("1.0000")
_CONFIDENCE_UNIFI_ID = Decimal("1.0000")
_CONFIDENCE_HOSTNAME = Decimal("0.5000")
_CONFIDENCE_PIHOLE_CLIENT = Decimal("0.5000")
_CONFIDENCE_IP = Decimal("0.1000")
# Parent-confirmed weak identifiers beat auto-observed ones; still below MAC/id.
_CONFIDENCE_CONFIRMED_CLIENT = Decimal("0.9000")


@dataclass(frozen=True, slots=True)
class ClientObservation:
    """One client sighting from Pi-hole or UniFi (or a test fixture)."""

    observed_at: datetime
    source: str
    first_seen: datetime | None = None
    mac: str | None = None
    unifi_client_id: str | None = None
    hostname: str | None = None
    pihole_client: str | None = None
    ip: str | None = None


def normalize_mac(value: str) -> str:
    """Canonical durable MAC: lowercase colon-separated."""
    hex_only = _MAC_RE.sub("", value.strip()).lower()
    if len(hex_only) != 12:
        raise ValueError(f"Invalid MAC address: {value!r}")
    return ":".join(hex_only[i : i + 2] for i in range(0, 12, 2))


def _has_strong_identity(obs: ClientObservation) -> bool:
    return bool(obs.mac or obs.unifi_client_id)


def _display_name_hint(obs: ClientObservation) -> str | None:
    return obs.hostname or obs.pihole_client


async def _find_device_by_identifier(
    session: AsyncSession,
    kind: IdentifierKind,
    value: str,
) -> Device | None:
    result = await session.execute(
        select(Device)
        .join(DeviceIdentifier, DeviceIdentifier.device_id == Device.id)
        .where(
            DeviceIdentifier.kind == kind,
            DeviceIdentifier.value == value,
        )
    )
    return result.scalars().first()


async def _match_device(
    session: AsyncSession,
    obs: ClientObservation,
) -> Device | None:
    """Resolve an existing device by strong identifiers only — never by IP/hostname."""
    if obs.mac:
        device = await _find_device_by_identifier(
            session, IdentifierKind.MAC, obs.mac
        )
        if device is not None:
            return device
    if obs.unifi_client_id:
        device = await _find_device_by_identifier(
            session,
            IdentifierKind.UNIFI_CLIENT_ID,
            obs.unifi_client_id,
        )
        if device is not None:
            return device
    # Hostname / pihole_client / IP are evidence only — never merge keys.
    return None


async def _device_has_strong_identifier(
    session: AsyncSession,
    device_id: object,
) -> bool:
    result = await session.execute(
        select(DeviceIdentifier.id)
        .where(
            DeviceIdentifier.device_id == device_id,
            DeviceIdentifier.kind.in_(STRONG_IDENTIFIER_KINDS),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _upsert_identifier(
    session: AsyncSession,
    device: Device,
    *,
    kind: IdentifierKind,
    value: str,
    confidence: Decimal,
    first_seen: datetime,
    last_seen: datetime,
) -> None:
    result = await session.execute(
        select(DeviceIdentifier).where(
            DeviceIdentifier.kind == kind,
            DeviceIdentifier.value == value,
        )
    )
    existing = result.scalars().first()
    if existing is None:
        session.add(
            DeviceIdentifier(
                logic_version=LOGIC_VERSION,
                device_id=device.id,
                kind=kind,
                value=value,
                confidence=confidence,
                first_seen=first_seen,
                last_seen=last_seen,
            )
        )
        return
    if existing.device_id != device.id:
        # Conflicting evidence: keep the other binding; do not steal the key.
        logger.warning(
            "identifier conflict kind=%s value=%s existing_device=%s new_device=%s",
            kind.value,
            value,
            existing.device_id,
            device.id,
        )
        return
    if first_seen < existing.first_seen:
        existing.first_seen = first_seen
    if last_seen > existing.last_seen:
        existing.last_seen = last_seen
    existing.confidence = confidence
    existing.logic_version = LOGIC_VERSION


async def _update_ip_assignment(
    session: AsyncSession,
    device: Device,
    *,
    ip: str,
    observed_at: datetime,
    source: str,
) -> None:
    """Maintain open-ended IP history; never key identity on IP."""
    result = await session.execute(
        select(IpAssignment)
        .where(
            IpAssignment.device_id == device.id,
            IpAssignment.observed_to.is_(None),
        )
        .order_by(IpAssignment.observed_from.desc())
    )
    open_row = result.scalars().first()
    if open_row is not None and open_row.ip == ip:
        return
    if open_row is not None:
        open_row.observed_to = observed_at
    session.add(
        IpAssignment(
            logic_version=LOGIC_VERSION,
            device_id=device.id,
            ip=ip,
            observed_from=observed_at,
            observed_to=None,
            source=source,
        )
    )


async def confirm_device_identifier(
    session: AsyncSession,
    device: Device,
    *,
    kind: IdentifierKind,
    value: str,
    observed_at: datetime,
) -> None:
    """Add or confirm a durable identifier binding for future correlation.

    Parent confirmation may reassign *weak* identifiers (hostname /
    pihole_client / ip) when evidence previously pointed elsewhere. Strong
    identifiers (MAC / UniFi client id) are never stolen. Never touches raw
    ingest tables or historical payloads.
    """
    cleaned = value.strip()
    if not cleaned:
        return
    if kind in STRONG_IDENTIFIER_KINDS:
        confidence = (
            _CONFIDENCE_MAC if kind == IdentifierKind.MAC else _CONFIDENCE_UNIFI_ID
        )
    elif kind in (IdentifierKind.PIHOLE_CLIENT, IdentifierKind.HOSTNAME):
        confidence = _CONFIDENCE_CONFIRMED_CLIENT
    else:
        confidence = _CONFIDENCE_IP

    result = await session.execute(
        select(DeviceIdentifier).where(
            DeviceIdentifier.kind == kind,
            DeviceIdentifier.value == cleaned,
        )
    )
    existing = result.scalars().first()
    if existing is not None and existing.device_id != device.id:
        if kind in STRONG_IDENTIFIER_KINDS:
            logger.warning(
                "confirm refused strong identifier conflict kind=%s value=%s "
                "existing_device=%s confirmed_device=%s",
                kind.value,
                cleaned,
                existing.device_id,
                device.id,
            )
            return
        # Parent resolution is authoritative for weak client-name bindings.
        existing.device_id = device.id
        existing.confidence = confidence
        existing.logic_version = LOGIC_VERSION
        if observed_at < existing.first_seen:
            existing.first_seen = observed_at
        if observed_at > existing.last_seen:
            existing.last_seen = observed_at
        await session.flush()
        return

    await _upsert_identifier(
        session,
        device,
        kind=kind,
        value=cleaned,
        confidence=confidence,
        first_seen=observed_at,
        last_seen=observed_at,
    )
    await session.flush()


async def resolve_observation(
    session: AsyncSession,
    obs: ClientObservation,
) -> Device:
    """Upsert a device + identifiers from one client observation."""
    first_seen = obs.first_seen or obs.observed_at
    last_seen = obs.observed_at
    if last_seen < first_seen:
        first_seen, last_seen = last_seen, first_seen

    device = await _match_device(session, obs)
    if device is None:
        device = Device(
            logic_version=LOGIC_VERSION,
            first_seen=first_seen,
            last_seen=last_seen,
            display_name=_display_name_hint(obs),
            is_unknown=not _has_strong_identity(obs),
        )
        session.add(device)
        await session.flush()
    else:
        if first_seen < device.first_seen:
            device.first_seen = first_seen
        if last_seen > device.last_seen:
            device.last_seen = last_seen
        if device.display_name is None:
            hint = _display_name_hint(obs)
            if hint:
                device.display_name = hint
        device.logic_version = LOGIC_VERSION

    if obs.mac:
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.MAC,
            value=obs.mac,
            confidence=_CONFIDENCE_MAC,
            first_seen=first_seen,
            last_seen=last_seen,
        )
    if obs.unifi_client_id:
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.UNIFI_CLIENT_ID,
            value=obs.unifi_client_id,
            confidence=_CONFIDENCE_UNIFI_ID,
            first_seen=first_seen,
            last_seen=last_seen,
        )
    if obs.hostname:
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.HOSTNAME,
            value=obs.hostname,
            confidence=_CONFIDENCE_HOSTNAME,
            first_seen=first_seen,
            last_seen=last_seen,
        )
    if obs.pihole_client:
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.PIHOLE_CLIENT,
            value=obs.pihole_client,
            confidence=_CONFIDENCE_PIHOLE_CLIENT,
            first_seen=first_seen,
            last_seen=last_seen,
        )
    if obs.ip:
        # Stored as weak evidence when unbound; never used for matching.
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.IP,
            value=obs.ip,
            confidence=_CONFIDENCE_IP,
            first_seen=first_seen,
            last_seen=last_seen,
        )
        await _update_ip_assignment(
            session,
            device,
            ip=obs.ip,
            observed_at=last_seen,
            source=obs.source,
        )

    device.is_unknown = not await _device_has_strong_identifier(session, device.id)
    device.logic_version = LOGIC_VERSION
    await session.flush()
    return device


async def resolve_observations(
    session: AsyncSession,
    observations: Sequence[ClientObservation],
) -> list[Device]:
    """Resolve many observations in order; returns the device for each."""
    devices: list[Device] = []
    for obs in observations:
        devices.append(await resolve_observation(session, obs))
    return devices


def observation_from_pihole_client(
    *,
    observed_at: datetime,
    ip: str | None = None,
    client_name: str | None = None,
    first_seen: datetime | None = None,
) -> ClientObservation:
    """Build an observation from Pi-hole client fields (IP + optional name)."""
    name = client_name.strip() if client_name else None
    return ClientObservation(
        observed_at=observed_at,
        source="pihole_api",
        first_seen=first_seen,
        ip=ip,
        pihole_client=name,
        hostname=name,
    )
