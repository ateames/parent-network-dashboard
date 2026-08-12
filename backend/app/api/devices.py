"""Device identity HTTP endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import write_audit
from app.config import settings
from app.db import get_session
from app.models.identity import Device
from app.models.people import PersonDevice
from app.models.restrictions import DeviceRestriction
from app.restrictions import (
    RestrictionError,
    active_restriction,
    apply_internet_restriction,
    lift_internet_restriction,
    load_active_restrictions_by_device,
    restriction_snapshot,
)
from app.schemas.devices import (
    AssignedPersonOut,
    DeviceDetailOut,
    DeviceIdentifierOut,
    DeviceListOut,
    DevicePatchIn,
    DeviceSummaryOut,
    InternetRestrictionCreateIn,
    InternetRestrictionOut,
    IpAssignmentOut,
)

router = APIRouter(prefix="/api/devices", tags=["devices"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _actor() -> str:
    return settings.admin_username


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


def _restriction_out(
    row: DeviceRestriction | None,
) -> InternetRestrictionOut | None:
    if row is None:
        return None
    return InternetRestrictionOut.model_validate(row)


def _to_summary(
    device: Device,
    *,
    restriction: DeviceRestriction | None = None,
) -> DeviceSummaryOut:
    active = restriction
    if active is None and hasattr(device, "restrictions"):
        active = active_restriction(device)
    return DeviceSummaryOut(
        id=device.id,
        display_name=device.display_name,
        notes=device.notes,
        is_unknown=device.is_unknown,
        first_seen=device.first_seen,
        last_seen=device.last_seen,
        current_ip=_current_ip(device),
        assigned_person=_active_person(device),
        internet_restriction=_restriction_out(active),
    )


def _to_detail(
    device: Device,
    *,
    restriction: DeviceRestriction | None = None,
) -> DeviceDetailOut:
    identifiers = sorted(
        device.identifiers,
        key=lambda i: (i.kind.value, i.value),
    )
    history = sorted(
        device.ip_assignments,
        key=lambda a: a.observed_from,
    )
    summary = _to_summary(device, restriction=restriction)
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
        selectinload(Device.restrictions),
    )


def _http_for_restriction_error(exc: RestrictionError) -> HTTPException:
    code_map: dict[str, int] = {
        "missing_mac": status.HTTP_400_BAD_REQUEST,
        "invalid_mac": status.HTTP_400_BAD_REQUEST,
        "not_restricted": status.HTTP_404_NOT_FOUND,
        "session_auth_required": status.HTTP_409_CONFLICT,
        "unifi_block_failed": status.HTTP_502_BAD_GATEWAY,
        "unifi_unblock_failed": status.HTTP_502_BAD_GATEWAY,
    }
    return HTTPException(
        status_code=code_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
        detail={"message": exc.message, "code": exc.code},
    )


async def _get_device_or_404(
    session: AsyncSession,
    device_id: UUID,
) -> Device:
    result = await session.execute(
        select(Device)
        .options(*_device_load_options())
        .where(Device.id == device_id)
        .execution_options(populate_existing=True)
    )
    device = result.scalars().unique().first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    return device


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

    active_by_device = await load_active_restrictions_by_device(
        session, [d.id for d in filtered]
    )
    return DeviceListOut(
        devices=[
            _to_summary(d, restriction=active_by_device.get(d.id)) for d in filtered
        ]
    )


@router.get("/{device_id}", response_model=DeviceDetailOut)
async def get_device(
    device_id: UUID,
    session: SessionDep,
) -> DeviceDetailOut:
    device = await _get_device_or_404(session, device_id)
    return _to_detail(device)


@router.patch("/{device_id}", response_model=DeviceDetailOut)
async def patch_device(
    device_id: UUID,
    body: DevicePatchIn,
    session: SessionDep,
) -> DeviceDetailOut:
    device = await _get_device_or_404(session, device_id)

    updates = body.model_dump(exclude_unset=True)
    if "display_name" in updates:
        device.display_name = updates["display_name"]
    if "notes" in updates:
        device.notes = updates["notes"]

    await session.commit()
    device = await _get_device_or_404(session, device_id)
    return _to_detail(device)


@router.post(
    "/{device_id}/internet-restriction",
    response_model=DeviceDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_internet_restriction(
    device_id: UUID,
    body: InternetRestrictionCreateIn,
    session: SessionDep,
) -> DeviceDetailOut:
    device = await _get_device_or_404(session, device_id)
    before: dict[str, Any] | None = None
    prior = active_restriction(device)
    if prior is not None:
        before = restriction_snapshot(prior)

    try:
        row = await apply_internet_restriction(
            session, device, minutes=body.minutes
        )
    except RestrictionError as exc:
        await session.rollback()
        raise _http_for_restriction_error(exc) from exc

    await write_audit(
        session,
        actor=_actor(),
        action="device.internet_restriction.create",
        entity_type="device",
        entity_id=device.id,
        before=before,
        after=restriction_snapshot(row),
    )
    await session.commit()
    device = await _get_device_or_404(session, device_id)
    return _to_detail(device)


@router.delete(
    "/{device_id}/internet-restriction",
    response_model=DeviceDetailOut,
)
async def delete_internet_restriction(
    device_id: UUID,
    session: SessionDep,
) -> DeviceDetailOut:
    device = await _get_device_or_404(session, device_id)
    prior = active_restriction(device)
    before = restriction_snapshot(prior) if prior else None

    try:
        row = await lift_internet_restriction(session, device, restriction=prior)
    except RestrictionError as exc:
        await session.commit()  # persist error on active row when unblock failed
        raise _http_for_restriction_error(exc) from exc

    await write_audit(
        session,
        actor=_actor(),
        action="device.internet_restriction.delete",
        entity_type="device",
        entity_id=device.id,
        before=before,
        after=restriction_snapshot(row),
    )
    await session.commit()
    device = await _get_device_or_404(session, device_id)
    return _to_detail(device)
