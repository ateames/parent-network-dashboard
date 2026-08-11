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


class ConnectionsOut(BaseModel):
    """Public connection settings — secrets never included, only configured flags."""

    pihole_url: str
    pihole_auth_method: str
    pihole_password_configured: bool
    pihole_token_configured: bool
    pihole_verify_tls: bool
    unifi_url: str
    unifi_auth_method: str
    unifi_username: str | None = None
    unifi_password_configured: bool
    unifi_token_configured: bool
    unifi_site: str
    unifi_verify_tls: bool
    dashboard_username: str | None = None
    dashboard_password_configured: bool
    setup_completed: bool
    setup_completed_at: datetime | None = None
    source: str
    updated_at: datetime | None = None
    syslog_port: int
    syslog_enabled: bool


class ConnectionsPutIn(BaseModel):
    """Upsert connection settings. Omit secret fields or send sentinel to keep."""

    pihole_url: str | None = Field(default=None, max_length=512)
    pihole_auth_method: str | None = Field(default=None, max_length=32)
    pihole_password: str | None = None
    pihole_token: str | None = None
    pihole_verify_tls: bool | None = None
    unifi_url: str | None = Field(default=None, max_length=512)
    unifi_auth_method: str | None = Field(default=None, max_length=32)
    unifi_username: str | None = Field(default=None, max_length=255)
    unifi_password: str | None = None
    unifi_token: str | None = None
    unifi_site: str | None = Field(default=None, max_length=64)
    unifi_verify_tls: bool | None = None
    dashboard_username: str | None = Field(default=None, max_length=255)
    dashboard_password: str | None = None
    mark_setup_complete: bool | None = None

    @field_validator("pihole_auth_method")
    @classmethod
    def _pihole_auth(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if cleaned not in {"none", "password", "token"}:
            raise ValueError("pihole_auth_method must be none, password, or token")
        return cleaned

    @field_validator("unifi_auth_method")
    @classmethod
    def _unifi_auth(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if cleaned not in {"session", "password", "token", "none"}:
            raise ValueError(
                "unifi_auth_method must be session, password, token, or none"
            )
        return cleaned


class ConnectionTestIn(BaseModel):
    """Optional override credentials for a one-shot connection test."""

    url: str | None = Field(default=None, max_length=512)
    auth_method: str | None = Field(default=None, max_length=32)
    password: str | None = None
    token: str | None = None
    username: str | None = Field(default=None, max_length=255)
    site: str | None = Field(default=None, max_length=64)
    verify_tls: bool | None = None


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str


class SetupStatusOut(BaseModel):
    setup_completed: bool
    setup_completed_at: datetime | None = None
    syslog_port: int
    syslog_enabled: bool


class DashboardVerifyIn(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)


class DashboardVerifyOut(BaseModel):
    ok: bool
    username: str
