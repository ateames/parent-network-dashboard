"""Device identity HTTP endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_session
from app.models.identity import Device
from app.models.people import PersonDevice
from app.schemas.devices import (
    AssignedPersonOut,
    DeviceDetailOut,
    DeviceIdentifierOut,
    DeviceListOut,
    DevicePatchIn,
    DeviceSummaryOut,
    IpAssignmentOut,
)

router = APIRouter(prefix="/api/devices", tags=["devices"])


def _is_online(device: Device, *, now: datetime, online_seconds: int) -> bool:
    cutoff = now - timedelta(seconds=online_seconds)
    last_seen = device.last_seen
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    return last_seen >= cutoff


def _current_ip(device: Device) -> str | None:
    open_rows = [a for a in device.ip_assignments if a.observed_to is None]
    if not open_rows:
        return None
    open_rows.sort(key=lambda a: a.observed_from, reverse=True)
    return open_rows[0].ip


def _assigned_person(device: Device) -> AssignedPersonOut | None:
    active = [link for link in device.person_links if link.active]
    if not active:
        return None
    active.sort(key=lambda link: link.assigned_at, reverse=True)
    person = active[0].person
    return AssignedPersonOut(id=person.id, name=person.name, role=person.role)


def _to_summary(
    device: Device,
    *,
    now: datetime,
    online_seconds: int,
) -> DeviceSummaryOut:
    return DeviceSummaryOut(
        id=device.id,
        display_name=device.display_name,
        notes=device.notes,
        first_seen=device.first_seen,
        last_seen=device.last_seen,
        is_unknown=device.is_unknown,
        is_online=_is_online(device, now=now, online_seconds=online_seconds),
        current_ip=_current_ip(device),
        assigned_person=_assigned_person(device),
    )


def _device_load_options() -> tuple[object, ...]:
    return (
        selectinload(Device.identifiers),
        selectinload(Device.ip_assignments),
        selectinload(Device.person_links).selectinload(PersonDevice.person),
    )


@router.get("", response_model=DeviceListOut)
async def list_devices(
    session: Annotated[AsyncSession, Depends(get_session)],
    online: Annotated[bool | None, Query()] = None,
    unknown: Annotated[bool | None, Query()] = None,
    unassigned: Annotated[bool | None, Query()] = None,
) -> DeviceListOut:
    result = await session.execute(
        select(Device)
        .options(*_device_load_options())
        .order_by(Device.last_seen.desc())
    )
    devices = list(result.scalars().unique().all())
    now = datetime.now(UTC)
    online_seconds = settings.device_online_seconds

    summaries: list[DeviceSummaryOut] = []
    for device in devices:
        summary = _to_summary(device, now=now, online_seconds=online_seconds)
        if online is not None and summary.is_online != online:
            continue
        if unknown is not None and summary.is_unknown != unknown:
            continue
        if unassigned is not None:
            is_unassigned = summary.assigned_person is None
            if is_unassigned != unassigned:
                continue
        summaries.append(summary)
    return DeviceListOut(devices=summaries)


@router.get("/{device_id}", response_model=DeviceDetailOut)
async def get_device(
    device_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceDetailOut:
    result = await session.execute(
        select(Device).options(*_device_load_options()).where(Device.id == device_id)
    )
    device = result.scalars().unique().first()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    now = datetime.now(UTC)
    summary = _to_summary(
        device, now=now, online_seconds=settings.device_online_seconds
    )
    identifiers = sorted(
        device.identifiers,
        key=lambda row: (row.kind.value, row.value),
    )
    ip_history = sorted(
        device.ip_assignments,
        key=lambda row: row.observed_from,
        reverse=True,
    )
    return DeviceDetailOut(
        **summary.model_dump(),
        identifiers=[DeviceIdentifierOut.model_validate(i) for i in identifiers],
        ip_history=[IpAssignmentOut.model_validate(a) for a in ip_history],
        logic_version=device.logic_version,
    )


@router.patch("/{device_id}", response_model=DeviceDetailOut)
async def patch_device(
    device_id: UUID,
    body: DevicePatchIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceDetailOut:
    result = await session.execute(
        select(Device).options(*_device_load_options()).where(Device.id == device_id)
    )
    device = result.scalars().unique().first()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    payload = body.model_dump(exclude_unset=True)
    if "display_name" in payload:
        device.display_name = payload["display_name"]
    if "notes" in payload:
        device.notes = payload["notes"]
    await session.commit()

    # Re-load for fresh relationships after commit.
    result = await session.execute(
        select(Device).options(*_device_load_options()).where(Device.id == device_id)
    )
    device = result.scalars().unique().one()
    now = datetime.now(UTC)
    summary = _to_summary(
        device, now=now, online_seconds=settings.device_online_seconds
    )
    identifiers = sorted(
        device.identifiers,
        key=lambda row: (row.kind.value, row.value),
    )
    ip_history = sorted(
        device.ip_assignments,
        key=lambda row: row.observed_from,
        reverse=True,
    )
    return DeviceDetailOut(
        **summary.model_dump(),
        identifiers=[DeviceIdentifierOut.model_validate(i) for i in identifiers],
        ip_history=[IpAssignmentOut.model_validate(a) for a in ip_history],
        logic_version=device.logic_version,
    )
