"""Pydantic schemas for activity aggregation and baselines."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SubjectType = Literal["device", "person"]


class DeviationOut(BaseModel):
    metric: str
    value: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float | None = None
    threshold_kind: str
    threshold_value: float
    delta_from_mean: float
    reason: str


class ActivitySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject_type: SubjectType
    subject_id: UUID
    window: str
    window_start: datetime
    window_end: datetime
    dns_query_volume: int
    blocked_query_count: int
    blocked_query_pct: float
    unique_domain_count: int
    new_domain_count: int
    active_hour_count: int
    active_hours_utc: list[int]
    upload_bytes: int | None = None
    download_bytes: int | None = None
    connection_duration_seconds: float | None = None
    deviations: list[DeviationOut] = Field(default_factory=list)
    logic_version: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = (
        "DNS query counts reflect lookups attributed to this subject; "
        "they do not prove that specific content was viewed."
    )


class MetricBaselineOut(BaseModel):
    metric: str
    sample_count: int
    mean: float
    stddev: float
    percentile: float
    percentile_value: float
    z_threshold: float
    high_threshold_z: float
    high_threshold_percentile: float
    samples: list[float] = Field(default_factory=list)


class BaselineOut(BaseModel):
    subject_type: SubjectType
    subject_id: UUID
    window: str
    computed_at: datetime
    sample_count: int
    metrics: dict[str, MetricBaselineOut]
    typical_active_hours_utc: list[int]
    day_of_week_patterns: dict[str, Any]
    logic_version: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    method: str = (
        "Transparent statistics only (mean, sample stddev, nearest-rank "
        "percentile, z-score thresholds). No machine learning."
    )
