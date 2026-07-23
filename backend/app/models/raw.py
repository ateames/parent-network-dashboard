"""Append-only raw / source tables — preserve ingested payloads for replay."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import IngestBatchStatus, IngestSource

ingest_source_enum = ENUM(
    IngestSource,
    name="ingest_source",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)

ingest_batch_status_enum = ENUM(
    IngestBatchStatus,
    name="ingest_batch_status",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)


class IngestBatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ingest_batch"

    source: Mapped[IngestSource] = mapped_column(ingest_source_enum, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[IngestBatchStatus] = mapped_column(
        ingest_batch_status_enum,
        nullable=False,
    )
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    pihole_events: Mapped[list[RawPiholeEvent]] = relationship(back_populates="batch")
    unifi_clients: Mapped[list[RawUnifiClient]] = relationship(back_populates="batch")
    unifi_events: Mapped[list[RawUnifiEvent]] = relationship(back_populates="batch")
    unifi_syslogs: Mapped[list[RawUnifiSyslog]] = relationship(back_populates="batch")


class RawPiholeEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_pihole_event"

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    source_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingest_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_batch.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    batch: Mapped[IngestBatch] = relationship(back_populates="pihole_events")


class RawUnifiClient(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_unifi_client"

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingest_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_batch.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    batch: Mapped[IngestBatch] = relationship(back_populates="unifi_clients")


class RawUnifiEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_unifi_event"

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingest_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_batch.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    batch: Mapped[IngestBatch] = relationship(back_populates="unifi_events")


class RawUnifiSyslog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_unifi_syslog"

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    raw_line: Mapped[str] = mapped_column(Text, nullable=False)
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ingest_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_batch.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    batch: Mapped[IngestBatch] = relationship(back_populates="unifi_syslogs")
