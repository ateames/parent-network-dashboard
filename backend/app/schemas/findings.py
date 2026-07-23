"""Pydantic schemas for findings, feedback, and suppressions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    FindingConfidence,
    FindingFeedbackClassification,
    FindingSeverity,
    FindingStatus,
)


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


class FindingFeedbackIn(BaseModel):
    classification: FindingFeedbackClassification


class FindingFeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    finding_id: UUID
    classification: FindingFeedbackClassification
    actor: str
    created_at: datetime
    finding: FindingOut
    suppression_id: UUID | None = None


class SuppressionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    matching_key: str
    rule_id: str
    device_id: UUID | None = None
    person_id: UUID | None = None
    domain_pattern: str
    source_finding_id: UUID | None = None
    created_by: str
    created_at: datetime


class SuppressionListOut(BaseModel):
    items: list[SuppressionOut] = Field(default_factory=list)
    count: int = 0
