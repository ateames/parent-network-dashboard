"""Persisted activity baselines (versioned, transparent stats + inputs)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, LogicVersionMixin, UUIDPrimaryKeyMixin


class ActivityBaseline(UUIDPrimaryKeyMixin, LogicVersionMixin, Base):
    """Per-device or per-person baseline for one aggregation window size."""

    __tablename__ = "activity_baseline"
    __table_args__ = (
        Index("ix_activity_baseline_subject_id", "subject_id"),
        Index(
            "ix_activity_baseline_subject_window_computed",
            "subject_type",
            "subject_id",
            "window",
            "computed_at",
        ),
        UniqueConstraint(
            "subject_type",
            "subject_id",
            "window",
            "logic_version",
            "computed_at",
            name="uq_activity_baseline_subject_window_version_computed",
        ),
    )

    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    window: Mapped[str] = mapped_column(String(32), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    typical_active_hours_utc: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    day_of_week_patterns: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
