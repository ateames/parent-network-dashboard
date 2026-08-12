"""Pydantic schemas for device identity API responses."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import IdentifierKind, PersonRole, RestrictionStatus


class DeviceIdentifierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: IdentifierKind
    value: str
    confidence: Decimal
    first_seen: datetime
    last_seen: datetime


class IpAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ip: str
    observed_from: datetime
    observed_to: datetime | None
    source: str


class AssignedPersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    role: PersonRole


class InternetRestrictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: RestrictionStatus
    mac: str
    minutes: int | None = None
    expires_at: datetime | None = None
    created_at: datetime
    lifted_at: datetime | None = None
    error: str | None = None


class DeviceSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str | None
    notes: str | None
    is_unknown: bool
    first_seen: datetime
    last_seen: datetime
    current_ip: str | None = None
    assigned_person: AssignedPersonOut | None = None
    internet_restriction: InternetRestrictionOut | None = None


class DeviceListOut(BaseModel):
    devices: list[DeviceSummaryOut]


class DeviceDetailOut(DeviceSummaryOut):
    identifiers: list[DeviceIdentifierOut] = Field(default_factory=list)
    ip_history: list[IpAssignmentOut] = Field(default_factory=list)
    logic_version: str


class DevicePatchIn(BaseModel):
    display_name: str | None = None
    notes: str | None = None


class InternetRestrictionCreateIn(BaseModel):
    """Disable Internet for a device. Omit or null minutes = indefinite."""

    minutes: int | None = Field(
        default=None,
        description="Duration in minutes; null/omitted disables indefinitely.",
    )

    @field_validator("minutes")
    @classmethod
    def minutes_positive(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 1:
            raise ValueError("minutes must be >= 1 when set")
        return value
