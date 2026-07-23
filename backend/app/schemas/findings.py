"""Pydantic schemas for findings API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FindingConfidence, FindingSeverity, FindingStatus


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    logic_version: str
    rule_id: str
    severity: FindingSeverity
    status: FindingStatus
    confidence: FindingConfidence
    title: str
    summary: str
    why_flagged: str
    recommended_action: str
    subject_label: str
    missing_info: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    device_id: UUID | None = None
    person_id: UUID | None = None
    fingerprint: str
    occurred_at: datetime
    detected_at: datetime


class FindingListOut(BaseModel):
    items: list[FindingOut] = Field(default_factory=list)
    count: int = 0
