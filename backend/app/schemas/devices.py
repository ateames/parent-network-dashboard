"""Pydantic schemas for device identity API responses."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import IdentifierKind, PersonRole


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


class DeviceListOut(BaseModel):
    devices: list[DeviceSummaryOut]


class DeviceDetailOut(DeviceSummaryOut):
    identifiers: list[DeviceIdentifierOut] = Field(default_factory=list)
    ip_history: list[IpAssignmentOut] = Field(default_factory=list)
    logic_version: str


class DevicePatchIn(BaseModel):
    display_name: str | None = None
    notes: str | None = None
