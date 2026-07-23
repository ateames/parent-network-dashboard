"""HTTP endpoints for explainable findings."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.enums import FindingSeverity, FindingStatus
from app.models.findings import Finding
from app.schemas.findings import FindingListOut, FindingOut

router = APIRouter(tags=["findings"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _to_out(row: Finding) -> FindingOut:
    return FindingOut.model_validate(row)


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
