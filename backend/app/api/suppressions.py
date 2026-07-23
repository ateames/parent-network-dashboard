"""HTTP endpoints for finding suppressions (list + reverse)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit
from app.config import settings
from app.db import get_session
from app.models.findings import FindingSuppression
from app.schemas.findings import SuppressionListOut, SuppressionOut

router = APIRouter(tags=["suppressions"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _actor() -> str:
    return settings.admin_username


def _to_out(row: FindingSuppression) -> SuppressionOut:
    return SuppressionOut.model_validate(row)


def _suppression_snapshot(row: FindingSuppression) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "matching_key": row.matching_key,
        "rule_id": row.rule_id,
        "device_id": str(row.device_id) if row.device_id else None,
        "person_id": str(row.person_id) if row.person_id else None,
        "domain_pattern": row.domain_pattern,
        "source_finding_id": (
            str(row.source_finding_id) if row.source_finding_id else None
        ),
        "created_by": row.created_by,
    }


@router.get("/api/suppressions", response_model=SuppressionListOut)
async def list_suppressions(session: SessionDep) -> SuppressionListOut:
    """List active finding suppressions."""
    result = await session.execute(
        select(FindingSuppression).order_by(
            FindingSuppression.created_at.desc(),
            FindingSuppression.id.desc(),
        )
    )
    rows = list(result.scalars().all())
    items = [_to_out(row) for row in rows]
    return SuppressionListOut(items=items, count=len(items))


@router.delete(
    "/api/suppressions/{suppression_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_suppression(
    suppression_id: UUID,
    session: SessionDep,
) -> Response:
    """Remove a suppression so equivalent findings can reappear."""
    result = await session.execute(
        select(FindingSuppression).where(FindingSuppression.id == suppression_id)
    )
    row = result.scalars().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suppression not found",
        )
    before = _suppression_snapshot(row)
    await write_audit(
        session,
        actor=_actor(),
        action="finding.unsuppress",
        entity_type="finding_suppression",
        entity_id=row.id,
        before=before,
        after=None,
    )
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
