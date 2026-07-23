"""Persisted meaningful stream events for live SSE + recent backfill."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, LogicVersionMixin, UUIDPrimaryKeyMixin
from app.models.enums import FindingSeverity, StreamEventKind
from app.models.findings import finding_severity_enum

if TYPE_CHECKING:
    from app.models.findings import Finding
    from app.models.identity import Device
    from app.models.people import Person

stream_event_kind_enum = ENUM(
    StreamEventKind,
    name="stream_event_kind",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)


class StreamEvent(UUIDPrimaryKeyMixin, LogicVersionMixin, Base):
    """One parent-readable live event (findings, new devices, source loss)."""

    __tablename__ = "stream_event"
    __table_args__ = (
        Index("ix_stream_event_severity", "severity"),
        Index("ix_stream_event_occurred_at", "occurred_at"),
        Index("ix_stream_event_kind", "kind"),
        Index("ix_stream_event_created_at", "created_at"),
    )

    kind: Mapped[StreamEventKind] = mapped_column(
        stream_event_kind_enum,
        nullable=False,
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        finding_severity_enum,
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("finding.id", ondelete="SET NULL"),
        nullable=True,
    )
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
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    finding: Mapped[Finding | None] = relationship()
    device: Mapped[Device | None] = relationship()
    person: Mapped[Person | None] = relationship()
