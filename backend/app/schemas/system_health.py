"""Pydantic schemas for GET /api/system/health."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import IngestBatchStatus, IngestSource, SourceHealthStatus


class ComponentStatusOut(BaseModel):
    status: str = Field(description="ok | degraded | down")
    detail: str = ""


class WorkerHealthOut(BaseModel):
    status: str
    last_seen_at: datetime | None
    staleness_seconds: int | None
    detail: str = ""


class LastBatchOut(BaseModel):
    source: IngestSource
    batch_id: str | None = None
    status: IngestBatchStatus | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    record_count: int | None = None
    error: str | None = None


class SourceErrorCountOut(BaseModel):
    source: IngestSource
    failed_batches_24h: int
    source_status: SourceHealthStatus | None = None


class SystemHealthOut(BaseModel):
    status: str = Field(description="Overall: ok | degraded | down")
    checked_at: datetime
    api: ComponentStatusOut
    database: ComponentStatusOut
    worker: WorkerHealthOut
    last_batches: list[LastBatchOut]
    error_counts: list[SourceErrorCountOut]
