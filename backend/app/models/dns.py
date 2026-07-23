"""Normalized DNS query records and versioned device correlations."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, LogicVersionMixin, UUIDPrimaryKeyMixin
from app.models.enums import CorrelationStatus, DnsQueryStatus
from app.models.raw import IngestBatch, RawPiholeEvent

if TYPE_CHECKING:
    from app.models.identity import Device

dns_query_status_enum = ENUM(
    DnsQueryStatus,
    name="dns_query_status",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)

correlation_status_enum = ENUM(
    CorrelationStatus,
    name="correlation_status",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)


class DnsQuery(UUIDPrimaryKeyMixin, LogicVersionMixin, Base):
    """Structured DNS activity for later device attribution by client + time."""

    __tablename__ = "dns_query"
    __table_args__ = (
        Index(
            "ix_dns_query_client_identifier_queried_at",
            "client_identifier",
            "queried_at",
        ),
        Index("ix_dns_query_queried_at", "queried_at"),
    )

    queried_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    client_identifier: Mapped[str] = mapped_column(String(512), nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    domain: Mapped[str] = mapped_column(String(2048), nullable=False)
    query_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[DnsQueryStatus] = mapped_column(
        dns_query_status_enum,
        nullable=False,
    )
    upstream: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pihole_query_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    raw_pihole_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_pihole_event.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ingest_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_batch.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    raw_event: Mapped[RawPiholeEvent] = relationship()
    batch: Mapped[IngestBatch] = relationship()
    activities: Mapped[list[DnsActivity]] = relationship(back_populates="dns_query")


class DnsActivity(UUIDPrimaryKeyMixin, LogicVersionMixin, Base):
    """Time-aware correlation of a DNS query to a durable device (or none)."""

    __tablename__ = "dns_activity"
    __table_args__ = (
        UniqueConstraint(
            "dns_query_id",
            "logic_version",
            name="uq_dns_activity_dns_query_id_logic_version",
        ),
        Index("ix_dns_activity_queried_at", "queried_at"),
        Index("ix_dns_activity_status", "status"),
        Index("ix_dns_activity_needs_review", "needs_review"),
    )

    dns_query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dns_query.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    queried_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    conflicts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[CorrelationStatus] = mapped_column(
        correlation_status_enum,
        nullable=False,
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    correlated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    dns_query: Mapped[DnsQuery] = relationship(back_populates="activities")
    device: Mapped[Device | None] = relationship()
