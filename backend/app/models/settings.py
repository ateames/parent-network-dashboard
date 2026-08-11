"""Persisted local configuration: thresholds and expected-activity schedules."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin

# Stable singleton IDs (also used as audit entity_id for thresholds).
THRESHOLDS_ROW_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
WORKER_HEARTBEAT_ROW_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
CONNECTIONS_ROW_ID = uuid.UUID("00000000-0000-4000-8000-000000000003")


class AppThresholds(Base):
    """Singleton row of tunable analysis / ingest thresholds."""

    __tablename__ = "app_thresholds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=THRESHOLDS_ROW_ID,
    )
    correlation_confidence_threshold: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    source_health_stale_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    source_health_max_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    pihole_poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    unifi_poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_z_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ConnectionSettings(Base):
    """Singleton row for Pi-hole / UniFi / optional dashboard credentials.

    Secret columns store Fernet ciphertext (or NULL when unset). Non-secret
    fields (URLs, auth methods, site) are plaintext. DB values override env
    when present so the first-run wizard can configure ingest without editing
    infra/.env.
    """

    __tablename__ = "connection_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=CONNECTIONS_ROW_ID,
    )

    pihole_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pihole_auth_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pihole_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    pihole_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    pihole_verify_tls: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    unifi_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    unifi_auth_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unifi_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unifi_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    unifi_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    unifi_site: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unifi_verify_tls: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    dashboard_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dashboard_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    setup_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ExpectedActivitySchedule(UUIDPrimaryKeyMixin, Base):
    """Parent-defined expected active hours for a person or device."""

    __tablename__ = "expected_activity_schedule"

    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_hours_utc: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    days_of_week: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class WorkerHeartbeat(Base):
    """Singleton liveness signal written by the worker process."""

    __tablename__ = "worker_heartbeat"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=WORKER_HEARTBEAT_ROW_ID,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
