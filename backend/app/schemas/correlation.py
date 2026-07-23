"""Pydantic schemas for correlation review and manual resolution."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CorrelationStatus


class CandidateDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str | None


class ReviewItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dns_query_id: UUID
    queried_at: datetime
    domain: str
    client_identifier: str
    client_ip: str | None
    confidence: Decimal
    status: CorrelationStatus
    needs_review: bool
    evidence: dict[str, Any]
    conflicts: dict[str, Any]
    candidate_devices: list[CandidateDeviceOut] = Field(default_factory=list)
    device_id: UUID | None = None
    logic_version: str


class ReviewListOut(BaseModel):
    items: list[ReviewItemOut]


class CorrelationResolveIn(BaseModel):
    """Parent resolution for an ambiguous or unattributed correlation.

    Either pick a ``device_id`` or set ``leave_unattributed=true``. Optionally
    strengthen future matching by confirming a ``device_identifier`` (never
    rewrites historical raw payloads).
    """

    device_id: UUID | None = None
    leave_unattributed: bool = False
    strengthen_identifier: bool = False

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.leave_unattributed:
            if self.device_id is not None:
                raise ValueError(
                    "leave_unattributed cannot be combined with device_id"
                )
            if self.strengthen_identifier:
                raise ValueError(
                    "strengthen_identifier requires a chosen device_id"
                )
            return self
        if self.device_id is None:
            raise ValueError("Provide device_id or set leave_unattributed=true")
        return self


class CorrelationResolveOut(ReviewItemOut):
    """Resolved correlation activity (no longer needs review)."""
