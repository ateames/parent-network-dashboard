"""Pydantic schemas for household people and device assignments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PersonRole


class PersonCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    role: PersonRole
    notes: str | None = None


class PersonPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: PersonRole | None = None
    notes: str | None = None


class PersonDeviceAssignIn(BaseModel):
    device_id: UUID


class AssignedDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str | None
    assigned_at: datetime
    assigned_by: str


class PersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    role: PersonRole
    notes: str | None
    logic_version: str
    devices: list[AssignedDeviceOut] = Field(default_factory=list)


class PersonListOut(BaseModel):
    people: list[PersonOut]


class PersonDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    person_id: UUID
    device_id: UUID
    assigned_by: str
    assigned_at: datetime
    active: bool
    logic_version: str
