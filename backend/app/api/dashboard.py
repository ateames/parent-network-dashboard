"""Parent dashboard summary HTTP endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dashboard.summary import build_dashboard_summary
from app.db import get_session
from app.schemas.dashboard import DashboardSummaryOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/summary", response_model=DashboardSummaryOut)
async def get_dashboard_summary(session: SessionDep) -> DashboardSummaryOut:
    """Return the single structured object the parent overview reads."""
    summary = await build_dashboard_summary(session)
    await session.commit()
    return summary
