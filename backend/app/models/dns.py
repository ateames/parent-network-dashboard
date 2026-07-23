"""Normalized DNS query records derived from Pi-hole (versioned logic)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, LogicVersionMixin, UUIDPrimaryKeyMixin
from app.models.enums import DnsQueryStatus
from app.models.raw import IngestBatch, RawPiholeEvent

dns_query_status_enum = ENUM(
    DnsQueryStatus,
    name="dns_query_status",
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
