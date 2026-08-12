"""Apply and lift UniFi client internet restrictions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.connection_store import resolve_ingest_settings_from_db
from app.identity.resolver import normalize_mac
from app.ingest.unifi import (
    UnifiClient,
    UnifiClientError,
    UnifiControlUnsupportedError,
)
from app.models.enums import IdentifierKind, RestrictionStatus
from app.models.identity import Device
from app.models.restrictions import DeviceRestriction

logger = logging.getLogger(__name__)


class RestrictionError(Exception):
    """Domain error for internet restriction flows."""

    def __init__(self, message: str, *, code: str = "restriction_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def device_mac(device: Device) -> str | None:
    """Return the strongest MAC identifier for a loaded device."""
    macs_sorted = sorted(
        (
            row
            for row in device.identifiers
            if row.kind == IdentifierKind.MAC and row.value
        ),
        key=lambda r: (r.confidence, r.value),
        reverse=True,
    )
    if not macs_sorted:
        return None
    return macs_sorted[0].value


def active_restriction(device: Device) -> DeviceRestriction | None:
    active = [
        row for row in device.restrictions if row.status == RestrictionStatus.ACTIVE
    ]
    if not active:
        return None
    active.sort(key=lambda r: r.created_at, reverse=True)
    return active[0]


def restriction_snapshot(row: DeviceRestriction) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "device_id": str(row.device_id),
        "mac": row.mac,
        "status": row.status.value,
        "minutes": row.minutes,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "lifted_at": row.lifted_at.isoformat() if row.lifted_at else None,
        "error": row.error,
    }


async def load_active_restrictions_by_device(
    session: AsyncSession,
    device_ids: list[UUID],
) -> dict[UUID, DeviceRestriction]:
    if not device_ids:
        return {}
    result = await session.execute(
        select(DeviceRestriction).where(
            DeviceRestriction.device_id.in_(device_ids),
            DeviceRestriction.status == RestrictionStatus.ACTIVE,
        )
    )
    rows = list(result.scalars().all())
    by_device: dict[UUID, DeviceRestriction] = {}
    for row in rows:
        existing = by_device.get(row.device_id)
        if existing is None or row.created_at > existing.created_at:
            by_device[row.device_id] = row
    return by_device


async def _unifi_client(session: AsyncSession) -> tuple[UnifiClient, Settings]:
    cfg = await resolve_ingest_settings_from_db(session)
    return UnifiClient(cfg), cfg


async def apply_internet_restriction(
    session: AsyncSession,
    device: Device,
    *,
    minutes: int | None,
) -> DeviceRestriction:
    """Block the device at UniFi, then persist an active restriction (fail closed)."""
    raw_mac = device_mac(device)
    if not raw_mac:
        raise RestrictionError(
            "Device has no MAC identifier; cannot disable internet via UniFi.",
            code="missing_mac",
        )
    try:
        mac = normalize_mac(raw_mac)
    except ValueError as exc:
        raise RestrictionError(
            f"Device MAC is invalid: {raw_mac!r}",
            code="invalid_mac",
        ) from exc

    now = datetime.now(UTC)
    expires_at: datetime | None = None
    if minutes is not None:
        expires_at = now + timedelta(minutes=minutes)

    client, _cfg = await _unifi_client(session)
    try:
        await client.block_client(mac)
    except UnifiControlUnsupportedError as exc:
        raise RestrictionError(str(exc), code="session_auth_required") from exc
    except UnifiClientError as exc:
        raise RestrictionError(
            f"UniFi refused to block the device: {exc}",
            code="unifi_block_failed",
        ) from exc
    finally:
        await client.aclose()

    # Lift any prior active rows for this device (controller now has latest block).
    prior = await session.execute(
        select(DeviceRestriction).where(
            DeviceRestriction.device_id == device.id,
            DeviceRestriction.status == RestrictionStatus.ACTIVE,
        )
    )
    for row in prior.scalars().all():
        row.status = RestrictionStatus.LIFTED
        row.lifted_at = now
        row.error = "replaced_by_new_restriction"

    row = DeviceRestriction(
        device_id=device.id,
        mac=mac,
        status=RestrictionStatus.ACTIVE,
        minutes=minutes,
        expires_at=expires_at,
        created_at=now,
        lifted_at=None,
        error=None,
    )
    # Satisfy LogicVersionMixin-style auditing without a column: store in notes path.
    session.add(row)
    await session.flush()
    return row


async def lift_internet_restriction(
    session: AsyncSession,
    device: Device,
    *,
    restriction: DeviceRestriction | None = None,
) -> DeviceRestriction:
    """Unblock at UniFi and mark the active restriction lifted."""
    row = restriction or active_restriction(device)
    if row is None:
        raise RestrictionError(
            "Device has no active internet restriction.",
            code="not_restricted",
        )

    client, _cfg = await _unifi_client(session)
    try:
        await client.unblock_client(row.mac)
    except UnifiControlUnsupportedError as exc:
        row.error = str(exc)
        await session.flush()
        raise RestrictionError(str(exc), code="session_auth_required") from exc
    except UnifiClientError as exc:
        row.error = str(exc)
        await session.flush()
        raise RestrictionError(
            f"UniFi refused to unblock the device: {exc}",
            code="unifi_unblock_failed",
        ) from exc
    finally:
        await client.aclose()

    now = datetime.now(UTC)
    row.status = RestrictionStatus.LIFTED
    row.lifted_at = now
    row.error = None
    await session.flush()
    return row


async def lift_expired_restrictions(session: AsyncSession) -> int:
    """Unblock active timed restrictions past expires_at. Returns lift count."""
    now = datetime.now(UTC)
    result = await session.execute(
        select(DeviceRestriction)
        .options(selectinload(DeviceRestriction.device))
        .where(
            DeviceRestriction.status == RestrictionStatus.ACTIVE,
            DeviceRestriction.expires_at.is_not(None),
            DeviceRestriction.expires_at <= now,
        )
        .order_by(DeviceRestriction.expires_at.asc())
    )
    rows = list(result.scalars().all())
    lifted = 0
    if not rows:
        return 0

    client, _cfg = await _unifi_client(session)
    try:
        for row in rows:
            try:
                await client.unblock_client(row.mac)
            except UnifiControlUnsupportedError as exc:
                row.error = str(exc)
                logger.error(
                    "cannot lift expired restriction %s: session auth required",
                    row.id,
                )
                continue
            except UnifiClientError as exc:
                row.error = str(exc)
                logger.warning(
                    "failed to unblock expired restriction %s mac=%s: %s",
                    row.id,
                    row.mac,
                    exc,
                )
                continue
            row.status = RestrictionStatus.LIFTED
            row.lifted_at = now
            row.error = None
            lifted += 1
            logger.info(
                "lifted expired restriction %s device=%s mac=%s",
                row.id,
                row.device_id,
                row.mac,
            )
    finally:
        await client.aclose()

    await session.flush()
    return lifted
