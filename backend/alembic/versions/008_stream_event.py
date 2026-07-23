"""Add stream_event table for live SSE + recent backfill.

Revision ID: 008_stream_event
Revises: 007_finding_feedback
Create Date: 2026-07-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "008_stream_event"
down_revision: str | None = "007_finding_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

finding_severity = postgresql.ENUM(
    "info",
    "low",
    "medium",
    "high",
    name="finding_severity",
    create_type=False,
)
stream_event_kind = postgresql.ENUM(
    "new_device_joined",
    "unknown_device_online",
    "blocked_query_burst",
    "dns_volume_increase",
    "activity_outside_expected_hours",
    "new_domain_burst",
    "connection_flapping",
    "unifi_security_event",
    "source_data_loss",
    name="stream_event_kind",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    stream_event_kind.create(bind, checkfirst=True)

    op.create_table(
        "stream_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logic_version", sa.String(length=64), nullable=False),
        sa.Column("kind", stream_event_kind, nullable=False),
        sa.Column("severity", finding_severity, nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["finding.id"],
            name="fk_stream_event_finding_id_finding",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["device.id"],
            name="fk_stream_event_device_id_device",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name="fk_stream_event_person_id_person",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stream_event"),
    )
    op.create_index("ix_stream_event_severity", "stream_event", ["severity"])
    op.create_index("ix_stream_event_occurred_at", "stream_event", ["occurred_at"])
    op.create_index("ix_stream_event_kind", "stream_event", ["kind"])
    op.create_index("ix_stream_event_created_at", "stream_event", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_stream_event_created_at", table_name="stream_event")
    op.drop_index("ix_stream_event_kind", table_name="stream_event")
    op.drop_index("ix_stream_event_occurred_at", table_name="stream_event")
    op.drop_index("ix_stream_event_severity", table_name="stream_event")
    op.drop_table("stream_event")
    stream_event_kind.drop(op.get_bind(), checkfirst=True)
