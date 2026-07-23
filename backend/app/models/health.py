"""Source health checks and audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import IngestSource, SourceHealthStatus
from app.models.raw import ingest_source_enum

source_health_status_enum = ENUM(
    SourceHealthStatus,
    name="source_health_status",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)


class SourceHealth(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "source_health"
    __table_args__ = (UniqueConstraint("source", name="uq_source_health_source"),)

    source: Mapped[IngestSource] = mapped_column(ingest_source_enum, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[SourceHealthStatus] = mapped_column(
        source_health_status_enum,
        nullable=False,
    )
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_log"

    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
