"""Persisted explainable findings, parent feedback, and suppressions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, LogicVersionMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    FindingConfidence,
    FindingFeedbackClassification,
    FindingSeverity,
    FindingStatus,
)

if TYPE_CHECKING:
    from app.models.identity import Device
    from app.models.people import Person

finding_severity_enum = ENUM(
    FindingSeverity,
    name="finding_severity",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)

finding_status_enum = ENUM(
    FindingStatus,
    name="finding_status",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)

finding_confidence_enum = ENUM(
    FindingConfidence,
    name="finding_confidence",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)

finding_feedback_classification_enum = ENUM(
    FindingFeedbackClassification,
    name="finding_feedback_classification",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)


class Finding(UUIDPrimaryKeyMixin, LogicVersionMixin, Base):
    """One parent-readable finding produced by a versioned rule."""

    __tablename__ = "finding"
    __table_args__ = (
        UniqueConstraint(
            "fingerprint",
            "logic_version",
            name="uq_finding_fingerprint_logic_version",
        ),
        Index("ix_finding_severity", "severity"),
        Index("ix_finding_status", "status"),
        Index("ix_finding_device_id", "device_id"),
        Index("ix_finding_person_id", "person_id"),
        Index("ix_finding_occurred_at", "occurred_at"),
        Index("ix_finding_rule_id", "rule_id"),
    )

    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[FindingSeverity] = mapped_column(
        finding_severity_enum,
        nullable=False,
    )
    status: Mapped[FindingStatus] = mapped_column(
        finding_status_enum,
        nullable=False,
        default=FindingStatus.OPEN,
    )
    confidence: Mapped[FindingConfidence] = mapped_column(
        finding_confidence_enum,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    why_flagged: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    subject_label: Mapped[str] = mapped_column(String(255), nullable=False)
    missing_info: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="SET NULL"),
        nullable=True,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(512), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    device: Mapped[Device | None] = relationship()
    person: Mapped[Person | None] = relationship()
    feedback: Mapped[list[FindingFeedback]] = relationship(
        back_populates="finding",
        order_by="FindingFeedback.created_at",
    )


class FindingFeedback(UUIDPrimaryKeyMixin, Base):
    """Parent classification of a finding (who / when / what)."""

    __tablename__ = "finding_feedback"
    __table_args__ = (
        Index("ix_finding_feedback_finding_id", "finding_id"),
        Index("ix_finding_feedback_created_at", "created_at"),
    )

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("finding.id", ondelete="CASCADE"),
        nullable=False,
    )
    classification: Mapped[FindingFeedbackClassification] = mapped_column(
        finding_feedback_classification_enum,
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    finding: Mapped[Finding] = relationship(back_populates="feedback")


class FindingSuppression(UUIDPrimaryKeyMixin, Base):
    """Active rule that skips equivalent low-value findings on future runs."""

    __tablename__ = "finding_suppression"
    __table_args__ = (
        UniqueConstraint("matching_key", name="uq_finding_suppression_matching_key"),
        Index("ix_finding_suppression_rule_id", "rule_id"),
        Index("ix_finding_suppression_created_at", "created_at"),
    )

    matching_key: Mapped[str] = mapped_column(String(512), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="SET NULL"),
        nullable=True,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
    )
    domain_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    source_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("finding.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
