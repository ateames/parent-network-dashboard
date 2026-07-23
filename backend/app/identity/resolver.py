"""Resolve client observations into durable device identities.

Matching priority (strong → weak):
1. MAC — same device
2. UniFi client id — same device
3. Hostname — weak evidence only (attach, never match/merge)
4. IP — never used to match or merge; recorded via identifiers + ip_assignment

Devices without MAC or UniFi client id are flagged ``is_unknown=true``.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import IdentifierKind
from app.models.identity import Device, DeviceIdentifier, IpAssignment

logger = logging.getLogger(__name__)

LOGIC_VERSION = "device_identity.v1"

_MAC_RE = re.compile(r"[^0-9a-fA-F]")

_CONFIDENCE_MAC = Decimal("1.0000")
_CONFIDENCE_UNIFI_ID = Decimal("1.0000")
_CONFIDENCE_HOSTNAME = Decimal("0.8000")
_CONFIDENCE_PIHOLE_CLIENT = Decimal("0.7000")
_CONFIDENCE_IP = Decimal("0.1000")

_STRONG_KINDS = frozenset({IdentifierKind.MAC, IdentifierKind.UNIFI_CLIENT_ID})


@dataclass(frozen=True, slots=True)
class ClientObservation:
    """One normalized client sighting from UniFi and/or Pi-hole ingest."""

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


def _has_strong_identifier(observation: ClientObservation) -> bool:
    return bool(observation.mac or observation.unifi_client_id)


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


async def _resolve_device(
    session: AsyncSession,
    observation: ClientObservation,
) -> Device | None:
    """Match by strong identifiers only. Never hostname or IP."""
    if observation.mac:
        device = await _find_device_by_identifier(
            session, IdentifierKind.MAC, observation.mac
        )
        if device is not None:
            return device
    if observation.unifi_client_id:
        device = await _find_device_by_identifier(
            session,
            IdentifierKind.UNIFI_CLIENT_ID,
            observation.unifi_client_id,
        )
        if device is not None:
            return device
    # Continuity for Pi-hole-only streams: same client string → same device.
    # This is not a cross-source merge key (hostname/IP still never merge).
    if observation.pihole_client and not _has_strong_identifier(observation):
        return await _find_device_by_identifier(
            session,
            IdentifierKind.PIHOLE_CLIENT,
            observation.pihole_client,
        )
    return None


async def _device_has_strong_identifier(
    session: AsyncSession,
    device_id: uuid.UUID,
) -> bool:
    result = await session.execute(
        select(DeviceIdentifier.kind).where(
            DeviceIdentifier.device_id == device_id,
            DeviceIdentifier.kind.in_(_STRONG_KINDS),
        )
    )
    return result.first() is not None


async def _upsert_identifier(
    session: AsyncSession,
    device: Device,
    *,
    kind: IdentifierKind,
    value: str,
    confidence: Decimal,
    first_seen: datetime,
    last_seen: datetime,
    reassign_on_conflict: bool = False,
    device_has_strong: bool = False,
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
        can_reassign = False
        if reassign_on_conflict:
            # IP may move to a strongly identified device, but an IP-only
            # observation must never steal IP from a MAC / UniFi-backed device.
            if device_has_strong:
                can_reassign = True
            else:
                old_strong = await _device_has_strong_identifier(
                    session, existing.device_id
                )
                can_reassign = not old_strong
        if can_reassign:
            logger.info(
                "reassigning ephemeral identifier kind=%s value=%s "
                "from_device=%s to_device=%s",
                kind.value,
                value,
                existing.device_id,
                device.id,
            )
            existing.device_id = device.id
            existing.first_seen = first_seen
            existing.last_seen = last_seen
            existing.confidence = confidence
            existing.logic_version = LOGIC_VERSION
            return
        # Conflicting durable evidence: leave the other binding.
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
    """Maintain open/closed intervals — source of IP-over-time truth."""
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


async def _refresh_unknown_flag(session: AsyncSession, device: Device) -> None:
    result = await session.execute(
        select(DeviceIdentifier.kind).where(DeviceIdentifier.device_id == device.id)
    )
    kinds = {row[0] for row in result.all()}
    device.is_unknown = not bool(kinds & _STRONG_KINDS)


def _display_name_hint(observation: ClientObservation) -> str | None:
    return observation.hostname or observation.pihole_client


async def resolve_observation(
    session: AsyncSession,
    observation: ClientObservation,
) -> Device:
    """Upsert a device + identifiers from one client observation."""
    mac = normalize_mac(observation.mac) if observation.mac else None
    if mac is not None and mac != observation.mac:
        observation = ClientObservation(
            observed_at=observation.observed_at,
            source=observation.source,
            first_seen=observation.first_seen,
            mac=mac,
            unifi_client_id=observation.unifi_client_id,
            hostname=observation.hostname,
            pihole_client=observation.pihole_client,
            ip=observation.ip,
        )

    first_seen = observation.first_seen or observation.observed_at
    last_seen = observation.observed_at
    if last_seen < first_seen:
        first_seen, last_seen = last_seen, first_seen

    strong = _has_strong_identifier(observation)
    device = await _resolve_device(session, observation)
    if device is None:
        device = Device(
            logic_version=LOGIC_VERSION,
            first_seen=first_seen,
            last_seen=last_seen,
            display_name=_display_name_hint(observation),
            is_unknown=not strong,
        )
        session.add(device)
        await session.flush()
    else:
        if first_seen < device.first_seen:
            device.first_seen = first_seen
        if last_seen > device.last_seen:
            device.last_seen = last_seen
        if device.display_name is None:
            hint = _display_name_hint(observation)
            if hint:
                device.display_name = hint
        device.logic_version = LOGIC_VERSION
        if not strong:
            strong = await _device_has_strong_identifier(session, device.id)

    if observation.mac:
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.MAC,
            value=observation.mac,
            confidence=_CONFIDENCE_MAC,
            first_seen=first_seen,
            last_seen=last_seen,
        )
    if observation.unifi_client_id:
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.UNIFI_CLIENT_ID,
            value=observation.unifi_client_id,
            confidence=_CONFIDENCE_UNIFI_ID,
            first_seen=first_seen,
            last_seen=last_seen,
        )
    if observation.hostname:
        # Weak evidence: attach only — never used for matching above.
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.HOSTNAME,
            value=observation.hostname,
            confidence=_CONFIDENCE_HOSTNAME,
            first_seen=first_seen,
            last_seen=last_seen,
        )
    if observation.pihole_client:
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.PIHOLE_CLIENT,
            value=observation.pihole_client,
            confidence=_CONFIDENCE_PIHOLE_CLIENT,
            first_seen=first_seen,
            last_seen=last_seen,
        )
    if observation.ip:
        # Ephemeral: may reassign when IP moves; never used for matching.
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.IP,
            value=observation.ip,
            confidence=_CONFIDENCE_IP,
            first_seen=first_seen,
            last_seen=last_seen,
            reassign_on_conflict=True,
            device_has_strong=strong,
        )
        await _update_ip_assignment(
            session,
            device,
            ip=observation.ip,
            observed_at=last_seen,
            source=observation.source,
        )

    await session.flush()
    await _refresh_unknown_flag(session, device)
    await session.flush()
    return device
