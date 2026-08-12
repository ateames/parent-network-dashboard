"""Add device_restriction for UniFi client internet controls.

Revision ID: 011_device_restriction
Revises: 010_connection_settings
Create Date: 2026-08-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "011_device_restriction"
down_revision: str | None = "010_connection_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

restriction_status = postgresql.ENUM(
    "active",
    "lifted",
    "failed",
    name="restriction_status",
    create_type=False,
)


def upgrade() -> None:
    restriction_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "device_restriction",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mac", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            restriction_status,
            nullable=False,
        ),
        sa.Column("minutes", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["device.id"],
            name=op.f("fk_device_restriction_device_id_device"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_restriction")),
    )
    op.create_index(
        "ix_device_restriction_device_id",
        "device_restriction",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        "ix_device_restriction_status_expires",
        "device_restriction",
        ["status", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_device_restriction_status_expires",
        table_name="device_restriction",
    )
    op.drop_index("ix_device_restriction_device_id", table_name="device_restriction")
    op.drop_table("device_restriction")
    restriction_status.drop(op.get_bind(), checkfirst=True)
