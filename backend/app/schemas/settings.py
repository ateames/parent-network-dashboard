"""Pydantic schemas for local settings and expected-activity schedules."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ThresholdsOut(BaseModel):
    correlation_confidence_threshold: float = Field(ge=0.0, le=1.0)
    source_health_stale_seconds: int = Field(ge=30, le=86_400)
    source_health_max_failures: int = Field(ge=1, le=100)
    pihole_poll_interval_seconds: int = Field(ge=5, le=3600)
    unifi_poll_interval_seconds: int = Field(ge=5, le=3600)
    baseline_z_threshold: float = Field(ge=0.5, le=10.0)
    updated_at: datetime | None = None


class ThresholdsPatchIn(BaseModel):
    correlation_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    source_health_stale_seconds: int | None = Field(default=None, ge=30, le=86_400)
    source_health_max_failures: int | None = Field(default=None, ge=1, le=100)
    pihole_poll_interval_seconds: int | None = Field(default=None, ge=5, le=3600)
    unifi_poll_interval_seconds: int | None = Field(default=None, ge=5, le=3600)
    baseline_z_threshold: float | None = Field(default=None, ge=0.5, le=10.0)


class ExpectedActivityScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    person_id: UUID | None
    device_id: UUID | None
    label: str | None
    expected_hours_utc: list[int]
    days_of_week: list[int] | None
    active: bool
    created_at: datetime
    updated_at: datetime


class ExpectedActivityScheduleIn(BaseModel):
    person_id: UUID | None = None
    device_id: UUID | None = None
    label: str | None = Field(default=None, max_length=255)
    expected_hours_utc: list[int] = Field(min_length=1)
    days_of_week: list[int] | None = None
    active: bool = True

    @field_validator("expected_hours_utc")
    @classmethod
    def _valid_hours(cls, value: list[int]) -> list[int]:
        cleaned = sorted({int(h) for h in value if 0 <= int(h) <= 23})
        if not cleaned:
            raise ValueError("expected_hours_utc must include at least one hour 0-23")
        return cleaned

    @field_validator("days_of_week")
    @classmethod
    def _valid_days(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        cleaned = sorted({int(d) for d in value if 0 <= int(d) <= 6})
        return cleaned or None

    @model_validator(mode="after")
    def _exactly_one_subject(self) -> ExpectedActivityScheduleIn:
        has_person = self.person_id is not None
        has_device = self.device_id is not None
        if has_person == has_device:
            raise ValueError("Provide exactly one of person_id or device_id")
        return self


class ExpectedActivitySchedulePatchIn(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    expected_hours_utc: list[int] | None = None
    days_of_week: list[int] | None = None
    active: bool | None = None

    @field_validator("expected_hours_utc")
    @classmethod
    def _valid_hours(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        cleaned = sorted({int(h) for h in value if 0 <= int(h) <= 23})
        if not cleaned:
            raise ValueError("expected_hours_utc must include at least one hour 0-23")
        return cleaned

    @field_validator("days_of_week")
    @classmethod
    def _valid_days(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        cleaned = sorted({int(d) for d in value if 0 <= int(d) <= 6})
        return cleaned


class ExpectedActivityScheduleListOut(BaseModel):
    schedules: list[ExpectedActivityScheduleOut]


class LocalSettingsOut(BaseModel):
    thresholds: ThresholdsOut
    schedules: list[ExpectedActivityScheduleOut]
