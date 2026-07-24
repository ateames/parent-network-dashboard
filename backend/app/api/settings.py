"""Local settings HTTP endpoints (thresholds + expected-activity schedules)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.config import settings
from app.db import get_session
from app.models.settings import THRESHOLDS_ROW_ID, ExpectedActivitySchedule
from app.schemas.settings import (
    ExpectedActivityScheduleIn,
    ExpectedActivityScheduleListOut,
    ExpectedActivityScheduleOut,
    ExpectedActivitySchedulePatchIn,
    LocalSettingsOut,
    ThresholdsOut,
    ThresholdsPatchIn,
)
from app.settings_store import (
    get_schedule,
    list_schedules,
    load_thresholds,
    patch_thresholds,
    schedule_to_dict,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _actor() -> str:
    return settings.admin_username


def _thresholds_out(data: dict) -> ThresholdsOut:
    return ThresholdsOut(**data)


def _schedule_out(row: ExpectedActivitySchedule) -> ExpectedActivityScheduleOut:
    return ExpectedActivityScheduleOut(
        id=row.id,
        person_id=row.person_id,
        device_id=row.device_id,
        label=row.label,
        expected_hours_utc=[int(h) for h in row.expected_hours_utc],
        days_of_week=(
            [int(d) for d in row.days_of_week] if row.days_of_week is not None else None
        ),
        active=row.active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=LocalSettingsOut)
async def get_local_settings(session: SessionDep) -> LocalSettingsOut:
    thresholds = await load_thresholds(session)
    schedules = await list_schedules(session)
    await session.commit()
    return LocalSettingsOut(
        thresholds=_thresholds_out(thresholds),
        schedules=[_schedule_out(s) for s in schedules],
    )


@router.get("/thresholds", response_model=ThresholdsOut)
async def get_thresholds(session: SessionDep) -> ThresholdsOut:
    data = await load_thresholds(session)
    await session.commit()
    return _thresholds_out(data)


@router.patch("/thresholds", response_model=ThresholdsOut)
async def update_thresholds(
    body: ThresholdsPatchIn,
    session: SessionDep,
) -> ThresholdsOut:
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No threshold fields to update",
        )
    before, after = await patch_thresholds(session, patch)
    await write_audit(
        session,
        actor=_actor(),
        action="thresholds.update",
        entity_type="app_thresholds",
        entity_id=THRESHOLDS_ROW_ID,
        before={k: before[k] for k in patch},
        after={k: after[k] for k in patch},
    )
    await session.commit()
    return _thresholds_out(after)


@router.get("/schedules", response_model=ExpectedActivityScheduleListOut)
async def get_schedules(session: SessionDep) -> ExpectedActivityScheduleListOut:
    rows = await list_schedules(session)
    await session.commit()
    return ExpectedActivityScheduleListOut(
        schedules=[_schedule_out(r) for r in rows]
    )


@router.post(
    "/schedules",
    response_model=ExpectedActivityScheduleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    body: ExpectedActivityScheduleIn,
    session: SessionDep,
) -> ExpectedActivityScheduleOut:
    row = ExpectedActivitySchedule(
        person_id=body.person_id,
        device_id=body.device_id,
        label=body.label,
        expected_hours_utc=body.expected_hours_utc,
        days_of_week=body.days_of_week,
        active=body.active,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    await write_audit(
        session,
        actor=_actor(),
        action="schedule.create",
        entity_type="expected_activity_schedule",
        entity_id=row.id,
        before=None,
        after=schedule_to_dict(row),
    )
    out = _schedule_out(row)
    await session.commit()
    return out


@router.patch("/schedules/{schedule_id}", response_model=ExpectedActivityScheduleOut)
async def update_schedule(
    schedule_id: UUID,
    body: ExpectedActivitySchedulePatchIn,
    session: SessionDep,
) -> ExpectedActivityScheduleOut:
    row = await get_schedule(session, schedule_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    before = schedule_to_dict(row)
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No schedule fields to update",
        )
    for key, value in patch.items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(row)
    after = schedule_to_dict(row)
    await write_audit(
        session,
        actor=_actor(),
        action="schedule.update",
        entity_type="expected_activity_schedule",
        entity_id=row.id,
        before=before,
        after=after,
    )
    out = _schedule_out(row)
    await session.commit()
    return out


@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_schedule(
    schedule_id: UUID,
    session: SessionDep,
) -> Response:
    row = await get_schedule(session, schedule_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    before = schedule_to_dict(row)
    await write_audit(
        session,
        actor=_actor(),
        action="schedule.delete",
        entity_type="expected_activity_schedule",
        entity_id=row.id,
        before=before,
        after=None,
    )
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
