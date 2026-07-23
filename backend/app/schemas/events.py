"""Pydantic schemas for the live event stream."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FindingSeverity, StreamEventKind


class StreamEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    logic_version: str
    kind: StreamEventKind
    severity: FindingSeverity
    summary: str
    finding_id: UUID | None = None
    device_id: UUID | None = None
    person_id: UUID | None = None
    source: str | None = None
    occurred_at: datetime
    created_at: datetime


class StreamEventListOut(BaseModel):
    items: list[StreamEventOut] = Field(default_factory=list)
    count: int = 0
