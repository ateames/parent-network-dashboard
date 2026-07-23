"""Pydantic schemas for the parent dashboard summary endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import IngestSource, PersonRole, SourceHealthStatus

HouseholdStatus = Literal["ok", "attention-needed"]
AttentionKind = Literal[
    "source_down",
    "source_degraded",
    "correlation_review",
    "unknown_device",
    "unassigned_device",
]
RecentActivityKind = Literal[
    "blocked_dns",
    "correlation_review",
    "attributed_dns",
]


class AttentionItemOut(BaseModel):
    kind: AttentionKind
    summary: str
    id: UUID | None = None
    source: IngestSource | None = None


class AttentionOut(BaseModel):
    count: int
    items: list[AttentionItemOut] = Field(default_factory=list)


class ActiveChildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    person_id: UUID
    name: str
    role: PersonRole
    device_ids: list[UUID] = Field(default_factory=list)
    last_activity_at: datetime | None = None


class DashboardDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str | None
    is_unknown: bool
    last_seen: datetime
    assigned_person_id: UUID | None = None
    assigned_person_name: str | None = None


class OnlineDevicesOut(BaseModel):
    """Online device roster — count is null when UniFi data is incomplete."""

    incomplete: bool = False
    count: int | None = None
    devices: list[DashboardDeviceOut] = Field(default_factory=list)


class UnknownUnassignedOut(BaseModel):
    incomplete: bool = False
    count: int | None = None
    devices: list[DashboardDeviceOut] = Field(default_factory=list)


class RecentActivityItemOut(BaseModel):
    kind: RecentActivityKind
    at: datetime
    summary: str
    domain: str | None = None
    device_id: UUID | None = None
    person_id: UUID | None = None
    person_name: str | None = None


class RecentActivityOut(BaseModel):
    incomplete: bool = False
    items: list[RecentActivityItemOut] = Field(default_factory=list)


class FindingsBySeverityOut(BaseModel):
    """Placeholder until findings land — always empty-safe zeros."""

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class TrendMetricOut(BaseModel):
    metric: str
    today_value: float | None = None
    baseline_mean: float | None = None
    delta_from_baseline: float | None = None
    incomplete: bool = False
    note: str | None = None


class TrendsOut(BaseModel):
    window: str
    incomplete: bool = False
    incomplete_reasons: list[str] = Field(default_factory=list)
    dns: list[TrendMetricOut] = Field(default_factory=list)
    network: list[TrendMetricOut] = Field(default_factory=list)
    disclaimer: str = (
        "DNS query counts reflect lookups; they do not prove that specific "
        "content was viewed."
    )


class DataHealthSourceOut(BaseModel):
    source: IngestSource
    status: SourceHealthStatus
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    staleness_seconds: int | None
    detail: str


class DataHealthOut(BaseModel):
    sources: list[DataHealthSourceOut] = Field(default_factory=list)


class DashboardSummaryOut(BaseModel):
    status: HouseholdStatus
    status_reason: str
    data_incomplete: bool
    incomplete_sources: list[IngestSource] = Field(default_factory=list)
    attention: AttentionOut
    active_children: list[ActiveChildOut] = Field(default_factory=list)
    active_children_incomplete: bool = False
    online_devices: OnlineDevicesOut
    unknown_unassigned: UnknownUnassignedOut
    recent_activity: RecentActivityOut
    findings_by_severity: FindingsBySeverityOut = Field(
        default_factory=FindingsBySeverityOut,
    )
    trends: TrendsOut
    data_health: DataHealthOut
    generated_at: datetime
    logic_version: str
