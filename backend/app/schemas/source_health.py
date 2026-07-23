"""Pydantic schemas for source health API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import IngestSource, SourceHealthStatus


class SourceHealthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: IngestSource
    status: SourceHealthStatus
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    staleness_seconds: int | None = Field(
        description="Seconds since last_success_at; null if never succeeded.",
    )
    detail: str


class SourceHealthListOut(BaseModel):
    sources: list[SourceHealthOut]
