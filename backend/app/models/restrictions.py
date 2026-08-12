"""Persisted UniFi client internet restrictions (block-sta / unblock-sta)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import RestrictionStatus

if TYPE_CHECKING:
    from app.models.identity import Device

restriction_status_enum = ENUM(
    RestrictionStatus,
    name="restriction_status",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)


class DeviceRestriction(UUIDPrimaryKeyMixin, Base):
    """One Disable Internet action against a durable device (by MAC)."""

    __tablename__ = "device_restriction"
    __table_args__ = (
        Index("ix_device_restriction_device_id", "device_id"),
        Index("ix_device_restriction_status_expires", "status", "expires_at"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=False,
    )
    mac: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[RestrictionStatus] = mapped_column(
        restriction_status_enum,
        nullable=False,
        default=RestrictionStatus.ACTIVE,
    )
    minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    lifted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    device: Mapped[Device] = relationship(back_populates="restrictions")
