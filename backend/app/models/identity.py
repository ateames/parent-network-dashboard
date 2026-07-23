"""Durable device identity — never keyed on IP alone."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, LogicVersionMixin, UUIDPrimaryKeyMixin
from app.models.enums import IdentifierKind

if TYPE_CHECKING:
    from app.models.people import PersonDevice

identifier_kind_enum = ENUM(
    IdentifierKind,
    name="identifier_kind",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)


class Device(UUIDPrimaryKeyMixin, LogicVersionMixin, Base):
    __tablename__ = "device"

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_unknown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    identifiers: Mapped[list[DeviceIdentifier]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )
    ip_assignments: Mapped[list[IpAssignment]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )
    person_links: Mapped[list[PersonDevice]] = relationship(back_populates="device")


class DeviceIdentifier(UUIDPrimaryKeyMixin, LogicVersionMixin, Base):
    __tablename__ = "device_identifier"
    __table_args__ = (
        UniqueConstraint("kind", "value", name="uq_device_identifier_kind_value"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[IdentifierKind] = mapped_column(identifier_kind_enum, nullable=False)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    device: Mapped[Device] = relationship(back_populates="identifiers")


class IpAssignment(UUIDPrimaryKeyMixin, LogicVersionMixin, Base):
    """IP history over time for a durable device."""

    __tablename__ = "ip_assignment"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    observed_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    observed_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    device: Mapped[Device] = relationship(back_populates="ip_assignments")
