"""Device identity HTTP endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
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

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _active_person(device: Device) -> AssignedPersonOut | None:
    for link in device.person_links:
        if link.active and link.person is not None:
            return AssignedPersonOut(
                id=link.person.id,
                name=link.person.name,
                role=link.person.role,
            )
    return None


def _current_ip(device: Device) -> str | None:
    open_rows = [
        row for row in device.ip_assignments if row.observed_to is None
    ]
    if not open_rows:
        return None
    open_rows.sort(key=lambda r: r.observed_from, reverse=True)
    return open_rows[0].ip


def _to_summary(device: Device) -> DeviceSummaryOut:
    return DeviceSummaryOut(
        id=device.id,
        display_name=device.display_name,
        notes=device.notes,
        is_unknown=device.is_unknown,
        first_seen=device.first_seen,
        last_seen=device.last_seen,
        current_ip=_current_ip(device),
        assigned_person=_active_person(device),
    )


def _to_detail(device: Device) -> DeviceDetailOut:
    identifiers = sorted(
        device.identifiers,
        key=lambda i: (i.kind.value, i.value),
    )
    history = sorted(
        device.ip_assignments,
        key=lambda a: a.observed_from,
    )
    summary = _to_summary(device)
    return DeviceDetailOut(
        **summary.model_dump(),
        identifiers=[DeviceIdentifierOut.model_validate(i) for i in identifiers],
        ip_history=[IpAssignmentOut.model_validate(a) for a in history],
        logic_version=device.logic_version,
    )


def _device_load_options() -> tuple[object, ...]:
    return (
        selectinload(Device.identifiers),
        selectinload(Device.ip_assignments),
        selectinload(Device.person_links).selectinload(PersonDevice.person),
    )


@router.get("", response_model=DeviceListOut)
async def list_devices(
    session: SessionDep,
    online: bool | None = Query(
        default=None,
        description="If true/false, filter by last_seen within the online window.",
    ),
    unknown: bool | None = Query(
        default=None,
        description="If true/false, filter by is_unknown.",
    ),
    unassigned: bool | None = Query(
        default=None,
        description="If true/false, filter by absence of an active person link.",
    ),
) -> DeviceListOut:
    now = datetime.now(UTC)
    online_cutoff = now - timedelta(seconds=settings.device_online_seconds)

    stmt = (
        select(Device)
        .options(*_device_load_options())
        .order_by(Device.last_seen.desc())
    )
    if unknown is not None:
        stmt = stmt.where(Device.is_unknown.is_(unknown))

    result = await session.execute(stmt)
    devices = list(result.scalars().unique().all())

    filtered: list[Device] = []
    for device in devices:
        if online is not None:
            is_online = device.last_seen >= online_cutoff
            if is_online != online:
                continue
        if unassigned is not None:
            is_unassigned = _active_person(device) is None
            if is_unassigned != unassigned:
                continue
        filtered.append(device)

    return DeviceListOut(devices=[_to_summary(d) for d in filtered])


@router.get("/{device_id}", response_model=DeviceDetailOut)
async def get_device(
    device_id: UUID,
    session: SessionDep,
) -> DeviceDetailOut:
    result = await session.execute(
        select(Device).options(*_device_load_options()).where(Device.id == device_id)
    )
    device = result.scalars().unique().first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    return _to_detail(device)


@router.patch("/{device_id}", response_model=DeviceDetailOut)
async def patch_device(
    device_id: UUID,
    body: DevicePatchIn,
    session: SessionDep,
) -> DeviceDetailOut:
    result = await session.execute(
        select(Device).options(*_device_load_options()).where(Device.id == device_id)
    )
    device = result.scalars().unique().first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    updates = body.model_dump(exclude_unset=True)
    if "display_name" in updates:
        device.display_name = updates["display_name"]
    if "notes" in updates:
        device.notes = updates["notes"]

    await session.commit()
    await session.refresh(device)
    # Re-load relationships after commit/refresh.
    result = await session.execute(
        select(Device).options(*_device_load_options()).where(Device.id == device_id)
    )
    device = result.scalars().unique().one()
    return _to_detail(device)
