"""HTTP endpoints for explainable findings and parent feedback."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.config import settings
from app.db import get_session
from app.findings.feedback import (
    SUPPRESSING_CLASSIFICATIONS,
    matching_key_for_finding,
    status_for_classification,
)
from app.models.enums import FindingSeverity, FindingStatus
from app.models.findings import Finding, FindingFeedback, FindingSuppression
from app.schemas.findings import (
    FindingFeedbackIn,
    FindingFeedbackOut,
    FindingListOut,
    FindingOut,
)

router = APIRouter(tags=["findings"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _actor() -> str:
    return settings.admin_username


def _to_out(row: Finding) -> FindingOut:
    return FindingOut.model_validate(row)


def _finding_snapshot(row: Finding) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "status": row.status.value,
        "rule_id": row.rule_id,
        "fingerprint": row.fingerprint,
    }


@router.get("/api/findings", response_model=FindingListOut)
async def list_findings(
    session: SessionDep,
    severity: Annotated[
        FindingSeverity | None,
        Query(description="Filter by severity."),
    ] = None,
    person: Annotated[
        UUID | None,
        Query(description="Filter by person id."),
    ] = None,
    device: Annotated[
        UUID | None,
        Query(description="Filter by device id."),
    ] = None,
    status_filter: Annotated[
        FindingStatus | None,
        Query(alias="status", description="Filter by finding status."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> FindingListOut:
    """List findings with optional severity / person / device / status filters."""
    stmt = select(Finding).order_by(Finding.occurred_at.desc(), Finding.id.desc())
    if severity is not None:
        stmt = stmt.where(Finding.severity == severity)
    if person is not None:
        stmt = stmt.where(Finding.person_id == person)
    if device is not None:
        stmt = stmt.where(Finding.device_id == device)
    if status_filter is not None:
        stmt = stmt.where(Finding.status == status_filter)
    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    items = [_to_out(row) for row in rows]
    return FindingListOut(items=items, count=len(items))


@router.get("/api/findings/{finding_id}", response_model=FindingOut)
async def get_finding(
    finding_id: UUID,
    session: SessionDep,
) -> FindingOut:
    """Return one finding by id."""
    result = await session.execute(select(Finding).where(Finding.id == finding_id))
    row = result.scalars().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found",
        )
    return _to_out(row)


@router.post(
    "/api/findings/{finding_id}/feedback",
    response_model=FindingFeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_finding_feedback(
    finding_id: UUID,
    body: FindingFeedbackIn,
    session: SessionDep,
) -> FindingFeedbackOut:
    """Record parent classification; update status and optional suppression."""
    result = await session.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalars().first()
    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found",
        )

    actor = _actor()
    before = _finding_snapshot(finding)
    new_status = status_for_classification(body.classification)
    finding.status = new_status

    feedback = FindingFeedback(
        finding_id=finding.id,
        classification=body.classification,
        actor=actor,
    )
    session.add(feedback)
    await session.flush()

    suppression_id: UUID | None = None
    if body.classification in SUPPRESSING_CLASSIFICATIONS:
        matching_key, domain_pattern = matching_key_for_finding(finding)
        existing = (
            await session.execute(
                select(FindingSuppression).where(
                    FindingSuppression.matching_key == matching_key
                )
            )
        ).scalars().first()
        if existing is None:
            suppression = FindingSuppression(
                matching_key=matching_key,
                rule_id=finding.rule_id,
                device_id=finding.device_id,
                person_id=finding.person_id,
                domain_pattern=domain_pattern,
                source_finding_id=finding.id,
                created_by=actor,
            )
            session.add(suppression)
            await session.flush()
            suppression_id = suppression.id
            await write_audit(
                session,
                actor=actor,
                action="finding.suppress",
                entity_type="finding_suppression",
                entity_id=suppression.id,
                before=None,
                after={
                    "matching_key": matching_key,
                    "rule_id": finding.rule_id,
                    "domain_pattern": domain_pattern,
                    "source_finding_id": str(finding.id),
                },
            )
        else:
            suppression_id = existing.id

    await write_audit(
        session,
        actor=actor,
        action="finding.feedback",
        entity_type="finding",
        entity_id=finding.id,
        before=before,
        after={
            **_finding_snapshot(finding),
            "classification": body.classification.value,
            "feedback_id": str(feedback.id),
            "suppression_id": str(suppression_id) if suppression_id else None,
        },
    )
    await session.commit()
    await session.refresh(feedback)
    await session.refresh(finding)

    return FindingFeedbackOut(
        id=feedback.id,
        finding_id=feedback.finding_id,
        classification=feedback.classification,
        actor=feedback.actor,
        created_at=feedback.created_at,
        finding=_to_out(finding),
        suppression_id=suppression_id,
    )
