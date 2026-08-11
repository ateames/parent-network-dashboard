"""Local settings HTTP endpoints (thresholds, schedules, connections)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.config import settings
from app.connection_store import (
    get_connections_row,
    load_connections_public,
    upsert_connections,
    verify_dashboard_credentials,
)
from app.connection_test import (
    settings_from_test_payload,
    test_pihole_connection,
    test_unifi_connection,
)
from app.db import get_session
from app.models.settings import (
    CONNECTIONS_ROW_ID,
    THRESHOLDS_ROW_ID,
    ExpectedActivitySchedule,
)
from app.schemas.settings import (
    ConnectionsOut,
    ConnectionsPutIn,
    ConnectionTestIn,
    ConnectionTestOut,
    DashboardVerifyIn,
    DashboardVerifyOut,
    ExpectedActivityScheduleIn,
    ExpectedActivityScheduleListOut,
    ExpectedActivityScheduleOut,
    ExpectedActivitySchedulePatchIn,
    LocalSettingsOut,
    SetupStatusOut,
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


def _connections_out(data: dict) -> ConnectionsOut:
    return ConnectionsOut(**data)


def _audit_connections_snapshot(data: dict) -> dict:
    """JSON-safe audit payload: no secrets, no raw datetimes."""
    skip = {
        "pihole_password_configured",
        "pihole_token_configured",
        "unifi_password_configured",
        "unifi_token_configured",
        "dashboard_password_configured",
        "setup_completed_at",
        "updated_at",
    }
    out: dict = {}
    for key, value in data.items():
        if key in skip:
            continue
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


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


@router.get("/setup-status", response_model=SetupStatusOut)
async def get_setup_status(session: SessionDep) -> SetupStatusOut:
    row = await get_connections_row(session)
    await session.commit()
    return SetupStatusOut(
        setup_completed=row is not None and row.setup_completed_at is not None,
        setup_completed_at=row.setup_completed_at if row else None,
        syslog_port=settings.unifi_syslog_port,
        syslog_enabled=settings.unifi_syslog_enabled,
    )


@router.get("/connections", response_model=ConnectionsOut)
async def get_connections(session: SessionDep) -> ConnectionsOut:
    data = await load_connections_public(session)
    await session.commit()
    return _connections_out(data)


@router.put("/connections", response_model=ConnectionsOut)
async def put_connections(
    body: ConnectionsPutIn,
    session: SessionDep,
) -> ConnectionsOut:
    patch = body.model_dump(exclude_unset=True)
    mark = patch.pop("mark_setup_complete", None)
    if not patch and mark is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No connection fields to update",
        )
    before, after = await upsert_connections(
        session,
        patch,
        mark_setup_complete=mark,
    )
    await write_audit(
        session,
        actor=_actor(),
        action="connections.update",
        entity_type="connection_settings",
        entity_id=CONNECTIONS_ROW_ID,
        before=_audit_connections_snapshot(before),
        after=_audit_connections_snapshot(after),
    )
    await session.commit()
    return _connections_out(after)


@router.post("/connections/test/pihole", response_model=ConnectionTestOut)
async def test_pihole(
    body: ConnectionTestIn,
    session: SessionDep,
) -> ConnectionTestOut:
    row = await get_connections_row(session)
    cfg = settings_from_test_payload(
        kind="pihole",
        body=body.model_dump(exclude_unset=True),
        row=row,
    )
    ok, message = await test_pihole_connection(cfg)
    await session.commit()
    return ConnectionTestOut(ok=ok, message=message)


@router.post("/connections/test/unifi", response_model=ConnectionTestOut)
async def test_unifi(
    body: ConnectionTestIn,
    session: SessionDep,
) -> ConnectionTestOut:
    row = await get_connections_row(session)
    cfg = settings_from_test_payload(
        kind="unifi",
        body=body.model_dump(exclude_unset=True),
        row=row,
    )
    ok, message = await test_unifi_connection(cfg)
    await session.commit()
    return ConnectionTestOut(ok=ok, message=message)


@router.post("/dashboard/verify", response_model=DashboardVerifyOut)
async def verify_dashboard(
    body: DashboardVerifyIn,
    session: SessionDep,
) -> DashboardVerifyOut:
    username = body.username.strip()
    ok = await verify_dashboard_credentials(session, username, body.password)
    if not ok:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    row = await get_connections_row(session)
    resolved_username = (
        row.dashboard_username
        if row is not None and row.dashboard_username
        else username
    )
    await session.commit()
    return DashboardVerifyOut(ok=True, username=resolved_username)


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
