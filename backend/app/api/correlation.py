"""Correlation review queue and manual resolution endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import write_audit
from app.config import settings
from app.db import get_session
from app.identity.resolver import confirm_device_identifier
from app.models.dns import DnsActivity
from app.models.enums import CorrelationStatus, IdentifierKind
from app.models.identity import Device
from app.schemas.correlation import (
    CandidateDeviceOut,
    CorrelationResolveIn,
    CorrelationResolveOut,
    ReviewItemOut,
    ReviewListOut,
)

_MANUAL_CONFIDENCE = Decimal("1.0000")

router = APIRouter(prefix="/api/correlation", tags=["correlation"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _actor() -> str:
    return settings.admin_username


def _activity_load_options() -> tuple[object, ...]:
    return (selectinload(DnsActivity.dns_query),)


def _candidate_ids_from_activity(activity: DnsActivity) -> list[UUID]:
    """Collect candidate device ids from stored evidence and conflicts."""
    ids: set[UUID] = set()
    for match in activity.evidence.get("matches") or []:
        raw = match.get("device_id")
        if raw:
            ids.add(UUID(str(raw)))
    for item in activity.conflicts.get("items") or []:
        raw = item.get("device_id")
        if raw:
            ids.add(UUID(str(raw)))
        for raw in item.get("device_ids") or []:
            ids.add(UUID(str(raw)))
    return sorted(ids, key=str)


def _activity_snapshot(activity: DnsActivity) -> dict[str, Any]:
    return {
        "id": str(activity.id),
        "dns_query_id": str(activity.dns_query_id),
        "device_id": str(activity.device_id) if activity.device_id else None,
        "status": activity.status.value,
        "needs_review": activity.needs_review,
        "confidence": str(activity.confidence),
        "manual_resolution": (activity.evidence or {}).get("manual_resolution"),
    }


def _to_review_item(
    activity: DnsActivity,
    devices_by_id: dict[UUID, Device],
) -> ReviewItemOut:
    query = activity.dns_query
    candidates: list[CandidateDeviceOut] = []
    for device_id in _candidate_ids_from_activity(activity):
        device = devices_by_id.get(device_id)
        candidates.append(
            CandidateDeviceOut(
                id=device_id,
                display_name=device.display_name if device else None,
            )
        )
    return ReviewItemOut(
        id=activity.id,
        dns_query_id=activity.dns_query_id,
        queried_at=activity.queried_at,
        domain=query.domain if query is not None else "",
        client_identifier=query.client_identifier if query is not None else "",
        client_ip=query.client_ip if query is not None else None,
        confidence=activity.confidence,
        status=activity.status,
        needs_review=activity.needs_review,
        evidence=activity.evidence,
        conflicts=activity.conflicts,
        candidate_devices=candidates,
        device_id=activity.device_id,
        logic_version=activity.logic_version,
    )


async def _load_devices(
    session: AsyncSession,
    device_ids: set[UUID],
) -> dict[UUID, Device]:
    if not device_ids:
        return {}
    result = await session.execute(
        select(Device).where(Device.id.in_(device_ids))
    )
    return {d.id: d for d in result.scalars().all()}


async def _get_review_activity_or_404(
    session: AsyncSession,
    activity_id: UUID,
) -> DnsActivity:
    result = await session.execute(
        select(DnsActivity)
        .options(*_activity_load_options())
        .where(DnsActivity.id == activity_id)
    )
    activity = result.scalars().unique().first()
    if activity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Correlation activity not found",
        )
    return activity


@router.get("/review", response_model=ReviewListOut)
async def list_review_queue(session: SessionDep) -> ReviewListOut:
    """List ambiguous and unattributed correlations that still need review."""
    result = await session.execute(
        select(DnsActivity)
        .options(*_activity_load_options())
        .where(
            DnsActivity.needs_review.is_(True),
            DnsActivity.status.in_(
                (CorrelationStatus.AMBIGUOUS, CorrelationStatus.UNATTRIBUTED)
            ),
        )
        .order_by(DnsActivity.queried_at.desc(), DnsActivity.id)
    )
    activities = list(result.scalars().unique().all())

    candidate_ids: set[UUID] = set()
    for activity in activities:
        candidate_ids.update(_candidate_ids_from_activity(activity))
    devices_by_id = await _load_devices(session, candidate_ids)

    return ReviewListOut(
        items=[_to_review_item(a, devices_by_id) for a in activities]
    )


@router.post(
    "/review/{activity_id}/resolve",
    response_model=CorrelationResolveOut,
)
async def resolve_review_item(
    activity_id: UUID,
    body: CorrelationResolveIn,
    session: SessionDep,
) -> CorrelationResolveOut:
    """Apply a parent decision: attribute to a device or leave unattributed."""
    activity = await _get_review_activity_or_404(session, activity_id)
    if not activity.needs_review:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Correlation already resolved",
        )
    if activity.status not in (
        CorrelationStatus.AMBIGUOUS,
        CorrelationStatus.UNATTRIBUTED,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Correlation is not in the review queue",
        )

    before = _activity_snapshot(activity)
    actor = _actor()
    resolved_at = datetime.now(UTC)
    strengthened = False

    if body.leave_unattributed:
        activity.device_id = None
        activity.status = CorrelationStatus.UNATTRIBUTED
        activity.needs_review = False
        decision = "leave_unattributed"
    else:
        assert body.device_id is not None
        device = (
            await session.execute(select(Device).where(Device.id == body.device_id))
        ).scalar_one_or_none()
        if device is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found",
            )
        activity.device_id = device.id
        activity.status = CorrelationStatus.ATTRIBUTED
        activity.confidence = _MANUAL_CONFIDENCE
        activity.needs_review = False
        decision = "attribute"

        if body.strengthen_identifier and activity.dns_query is not None:
            client = activity.dns_query.client_identifier.strip()
            if client:
                await confirm_device_identifier(
                    session,
                    device,
                    kind=IdentifierKind.PIHOLE_CLIENT,
                    value=client,
                    observed_at=activity.queried_at,
                )
                await confirm_device_identifier(
                    session,
                    device,
                    kind=IdentifierKind.HOSTNAME,
                    value=client,
                    observed_at=activity.queried_at,
                )
                strengthened = True

    # Preserve prior evidence/conflicts; record the human decision for replay safety.
    evidence = dict(activity.evidence or {})
    evidence["manual_resolution"] = {
        "decision": decision,
        "device_id": str(activity.device_id) if activity.device_id else None,
        "resolved_at": resolved_at.isoformat(),
        "actor": actor,
        "strengthen_identifier": body.strengthen_identifier,
        "strengthened": strengthened,
    }
    activity.evidence = evidence

    await write_audit(
        session,
        actor=actor,
        action="correlation.resolve",
        entity_type="dns_activity",
        entity_id=activity.id,
        before=before,
        after=_activity_snapshot(activity),
    )
    await session.commit()

    activity = await _get_review_activity_or_404(session, activity_id)
    device_ids = set(_candidate_ids_from_activity(activity))
    if activity.device_id is not None:
        device_ids.add(activity.device_id)
    devices_by_id = await _load_devices(session, device_ids)
    return CorrelationResolveOut.model_validate(
        _to_review_item(activity, devices_by_id).model_dump()
    )
