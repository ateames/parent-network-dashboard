"""Add dns_activity correlation table.

Revision ID: 004_dns_activity
Revises: 003_dns_query
Create Date: 2026-07-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "004_dns_activity"
down_revision: str | None = "003_dns_query"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

correlation_status = postgresql.ENUM(
    "attributed",
    "ambiguous",
    "unattributed",
    name="correlation_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    correlation_status.create(bind, checkfirst=True)

    op.create_table(
        "dns_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logic_version", sa.String(length=64), nullable=False),
        sa.Column("dns_query_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("queried_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("conflicts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", correlation_status, nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column(
            "correlated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["device.id"],
            name=op.f("fk_dns_activity_device_id_device"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dns_query_id"],
            ["dns_query.id"],
            name=op.f("fk_dns_activity_dns_query_id_dns_query"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dns_activity")),
        sa.UniqueConstraint(
            "dns_query_id",
            "logic_version",
            name="uq_dns_activity_dns_query_id_logic_version",
        ),
    )
    op.create_index(
        op.f("ix_dns_activity_dns_query_id"),
        "dns_activity",
        ["dns_query_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dns_activity_device_id"),
        "dns_activity",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dns_activity_queried_at"),
        "dns_activity",
        ["queried_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dns_activity_status"),
        "dns_activity",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dns_activity_needs_review"),
        "dns_activity",
        ["needs_review"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dns_activity_needs_review"), table_name="dns_activity")
    op.drop_index(op.f("ix_dns_activity_status"), table_name="dns_activity")
    op.drop_index(op.f("ix_dns_activity_queried_at"), table_name="dns_activity")
    op.drop_index(op.f("ix_dns_activity_device_id"), table_name="dns_activity")
    op.drop_index(op.f("ix_dns_activity_dns_query_id"), table_name="dns_activity")
    op.drop_table("dns_activity")
    correlation_status.drop(op.get_bind(), checkfirst=True)
