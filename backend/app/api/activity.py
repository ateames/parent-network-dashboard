"""HTTP endpoints for aggregated activity and transparent baselines."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.activity.aggregate import aggregate_activity, parse_window, subject_exists
from app.activity.baseline import (
    DEFAULT_LOOKBACK_SAMPLES,
    BaselineResult,
    compute_and_store_baseline,
    detect_deviations,
    get_latest_baseline,
    row_to_baseline,
)
from app.db import get_session
from app.schemas.activity import (
    ActivitySummaryOut,
    BaselineOut,
    DeviationOut,
    MetricBaselineOut,
)

router = APIRouter(tags=["activity"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
DeviceFilter = Annotated[
    UUID | None,
    Query(description="Device id filter."),
]
PersonFilter = Annotated[
    UUID | None,
    Query(description="Person id filter."),
]


def _baseline_out(result: BaselineResult) -> BaselineOut:
    metrics = {
        name: MetricBaselineOut(**mb.as_dict()) for name, mb in result.metrics.items()
    }
    return BaselineOut(
        subject_type=result.subject_type,
        subject_id=result.subject_id,
        window=result.window,
        computed_at=result.computed_at,
        sample_count=result.sample_count,
        metrics=metrics,
        typical_active_hours_utc=list(result.typical_active_hours_utc),
        day_of_week_patterns=result.day_of_week_patterns,
        logic_version=result.logic_version,
        inputs=dict(result.inputs),
    )


@router.get("/api/activity", response_model=ActivitySummaryOut)
async def get_activity(
    session: SessionDep,
    window: str = Query(
        default="24h",
        description="Aggregation window, e.g. 1h, 6h, 24h, 7d.",
    ),
    device: DeviceFilter = None,
    person: PersonFilter = None,
    compare_baseline: bool = Query(
        default=True,
        description="If true, attach deviations vs the latest stored baseline.",
    ),
) -> ActivitySummaryOut:
    """Return aggregated DNS + UniFi activity for one device or person."""
    if (device is None) == (person is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one of person or device",
        )
    try:
        parse_window(window)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if device is not None:
        resolved = await subject_exists(session, device)
        if resolved is None or resolved[0] != "device":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found",
            )
    else:
        assert person is not None
        resolved = await subject_exists(session, person)
        if resolved is None or resolved[0] != "person":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Person not found",
            )

    try:
        summary = await aggregate_activity(
            session,
            window=window,
            device_id=device,
            person_id=person,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    deviations: list[DeviationOut] = []
    if compare_baseline:
        row = await get_latest_baseline(
            session,
            subject_id=summary.subject_id,
            window=window,
        )
        if row is not None:
            baseline = row_to_baseline(row)
            deviations = [
                DeviationOut(**d.as_dict())
                for d in detect_deviations(summary, baseline)
            ]

    return ActivitySummaryOut(
        subject_type=summary.subject_type,
        subject_id=summary.subject_id,
        window=window,
        window_start=summary.window_start,
        window_end=summary.window_end,
        dns_query_volume=summary.dns_query_volume,
        blocked_query_count=summary.blocked_query_count,
        blocked_query_pct=summary.blocked_query_pct,
        unique_domain_count=summary.unique_domain_count,
        new_domain_count=summary.new_domain_count,
        active_hour_count=summary.active_hour_count,
        active_hours_utc=list(summary.active_hours_utc),
        upload_bytes=summary.upload_bytes,
        download_bytes=summary.download_bytes,
        connection_duration_seconds=summary.connection_duration_seconds,
        deviations=deviations,
        logic_version=summary.logic_version,
        inputs=dict(summary.inputs),
    )


@router.get("/api/baselines/{subject_id}", response_model=BaselineOut)
async def get_baseline(
    subject_id: UUID,
    session: SessionDep,
    window: str = Query(
        default="24h",
        description="Window size the baseline was (or will be) computed for.",
    ),
    recompute: bool = Query(
        default=False,
        description="If true, recompute from recent history and store.",
    ),
    samples: int = Query(
        default=DEFAULT_LOOKBACK_SAMPLES,
        ge=1,
        le=90,
        description="Historical windows to use when computing.",
    ),
) -> BaselineOut:
    """Return the latest baseline for a device_id or person_id."""
    try:
        parse_window(window)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    resolved = await subject_exists(session, subject_id)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device or person not found",
        )
    subject_type, _ = resolved

    if not recompute:
        row = await get_latest_baseline(
            session,
            subject_id=subject_id,
            window=window,
        )
        if row is not None:
            return _baseline_out(row_to_baseline(row))

    result = await compute_and_store_baseline(
        session,
        subject_type=subject_type,
        subject_id=subject_id,
        window=window,
        sample_count=samples,
        persist=True,
    )
    await session.commit()
    return _baseline_out(result)
