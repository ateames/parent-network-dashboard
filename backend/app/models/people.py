"""People and person↔device assignments."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, LogicVersionMixin, UUIDPrimaryKeyMixin
from app.models.enums import PersonRole

if TYPE_CHECKING:
    from app.models.identity import Device

person_role_enum = ENUM(
    PersonRole,
    name="person_role",
    values_callable=lambda e: [m.value for m in e],
    create_type=True,
)


class Person(UUIDPrimaryKeyMixin, LogicVersionMixin, Base):
    __tablename__ = "person"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[PersonRole] = mapped_column(person_role_enum, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    devices: Mapped[list[PersonDevice]] = relationship(
        back_populates="person",
        cascade="all, delete-orphan",
    )


class PersonDevice(UUIDPrimaryKeyMixin, LogicVersionMixin, Base):
    __tablename__ = "person_device"

    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_by: Mapped[str] = mapped_column(String(255), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    person: Mapped[Person] = relationship(back_populates="devices")
    device: Mapped[Device] = relationship(back_populates="person_links")
