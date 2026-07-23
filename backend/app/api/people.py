"""Household people and manual device assignment endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import write_audit
from app.config import settings
from app.db import get_session
from app.models.identity import Device
from app.models.people import Person, PersonDevice
from app.schemas.people import (
    AssignedDeviceOut,
    PersonCreateIn,
    PersonDeviceAssignIn,
    PersonDeviceOut,
    PersonListOut,
    PersonOut,
    PersonPatchIn,
)

LOGIC_VERSION = "person.v1"

router = APIRouter(prefix="/api/people", tags=["people"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _actor() -> str:
    return settings.admin_username


def _person_load_options() -> tuple[object, ...]:
    return (
        selectinload(Person.devices).selectinload(PersonDevice.device),
    )


def _link_snapshot(link: PersonDevice) -> dict[str, Any]:
    return {
        "id": str(link.id),
        "person_id": str(link.person_id),
        "device_id": str(link.device_id),
        "assigned_by": link.assigned_by,
        "assigned_at": link.assigned_at.isoformat() if link.assigned_at else None,
        "active": link.active,
    }


def _person_snapshot(person: Person) -> dict[str, Any]:
    return {
        "id": str(person.id),
        "name": person.name,
        "role": person.role.value,
        "notes": person.notes,
    }


def _to_out(person: Person) -> PersonOut:
    active_devices: list[AssignedDeviceOut] = []
    for link in person.devices:
        if not link.active or link.device is None:
            continue
        active_devices.append(
            AssignedDeviceOut(
                id=link.device.id,
                display_name=link.device.display_name,
                assigned_at=link.assigned_at,
                assigned_by=link.assigned_by,
            )
        )
    active_devices.sort(key=lambda d: (d.display_name or "", str(d.id)))
    return PersonOut(
        id=person.id,
        name=person.name,
        role=person.role,
        notes=person.notes,
        logic_version=person.logic_version,
        devices=active_devices,
    )


async def _get_person_or_404(session: AsyncSession, person_id: UUID) -> Person:
    result = await session.execute(
        select(Person).options(*_person_load_options()).where(Person.id == person_id)
    )
    person = result.scalars().unique().first()
    if person is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person not found",
        )
    return person


@router.get("", response_model=PersonListOut)
async def list_people(session: SessionDep) -> PersonListOut:
    result = await session.execute(
        select(Person).options(*_person_load_options()).order_by(Person.name)
    )
    people = list(result.scalars().unique().all())
    return PersonListOut(people=[_to_out(p) for p in people])


@router.post("", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
async def create_person(body: PersonCreateIn, session: SessionDep) -> PersonOut:
    person = Person(
        logic_version=LOGIC_VERSION,
        name=body.name,
        role=body.role,
        notes=body.notes,
    )
    session.add(person)
    await session.flush()
    await write_audit(
        session,
        actor=_actor(),
        action="person.create",
        entity_type="person",
        entity_id=person.id,
        before=None,
        after=_person_snapshot(person),
    )
    await session.commit()
    return await _get_person_or_404(session, person.id)


@router.get("/{person_id}", response_model=PersonOut)
async def get_person(person_id: UUID, session: SessionDep) -> PersonOut:
    return _to_out(await _get_person_or_404(session, person_id))


@router.patch("/{person_id}", response_model=PersonOut)
async def patch_person(
    person_id: UUID,
    body: PersonPatchIn,
    session: SessionDep,
) -> PersonOut:
    person = await _get_person_or_404(session, person_id)
    before = _person_snapshot(person)
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates:
        person.name = updates["name"]
    if "role" in updates:
        person.role = updates["role"]
    if "notes" in updates:
        person.notes = updates["notes"]
    await write_audit(
        session,
        actor=_actor(),
        action="person.update",
        entity_type="person",
        entity_id=person.id,
        before=before,
        after=_person_snapshot(person),
    )
    await session.commit()
    return await _get_person_or_404(session, person_id)


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(person_id: UUID, session: SessionDep) -> Response:
    person = await _get_person_or_404(session, person_id)
    await write_audit(
        session,
        actor=_actor(),
        action="person.delete",
        entity_type="person",
        entity_id=person.id,
        before=_person_snapshot(person),
        after=None,
    )
    await session.delete(person)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{person_id}/devices",
    response_model=PersonDeviceOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_device(
    person_id: UUID,
    body: PersonDeviceAssignIn,
    session: SessionDep,
) -> PersonDeviceOut:
    person = await _get_person_or_404(session, person_id)

    device = (
        await session.execute(select(Device).where(Device.id == body.device_id))
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    actor = _actor()
    existing_active = list(
        (
            await session.execute(
                select(PersonDevice).where(
                    PersonDevice.device_id == body.device_id,
                    PersonDevice.active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    for prior in existing_active:
        if prior.person_id == person.id:
            return PersonDeviceOut.model_validate(prior)
        before = _link_snapshot(prior)
        prior.active = False
        await write_audit(
            session,
            actor=actor,
            action="device.unassign",
            entity_type="person_device",
            entity_id=prior.id,
            before=before,
            after={**before, "active": False, "reason": "reassigned"},
        )

    link = PersonDevice(
        logic_version=LOGIC_VERSION,
        person_id=person.id,
        device_id=device.id,
        assigned_by=actor,
        assigned_at=datetime.now(UTC),
        active=True,
    )
    session.add(link)
    await session.flush()
    await write_audit(
        session,
        actor=actor,
        action="device.assign",
        entity_type="person_device",
        entity_id=link.id,
        before=None,
        after=_link_snapshot(link),
    )
    await session.commit()
    await session.refresh(link)
    return PersonDeviceOut.model_validate(link)


@router.delete(
    "/{person_id}/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unassign_device(
    person_id: UUID,
    device_id: UUID,
    session: SessionDep,
) -> Response:
    await _get_person_or_404(session, person_id)

    link = (
        await session.execute(
            select(PersonDevice).where(
                PersonDevice.person_id == person_id,
                PersonDevice.device_id == device_id,
                PersonDevice.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active device assignment not found",
        )

    before = _link_snapshot(link)
    link.active = False
    await write_audit(
        session,
        actor=_actor(),
        action="device.unassign",
        entity_type="person_device",
        entity_id=link.id,
        before=before,
        after={**before, "active": False},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
