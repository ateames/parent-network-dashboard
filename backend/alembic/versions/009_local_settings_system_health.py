"""Local settings, expected-activity schedules, and worker heartbeat.

Revision ID: 009_local_settings_system_health
Revises: 008_stream_event
Create Date: 2026-07-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "009_local_settings_system_health"
down_revision: str | None = "008_stream_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Singleton primary keys (stable for audit / upserts).
THRESHOLDS_ROW_ID = "00000000-0000-4000-8000-000000000001"
WORKER_HEARTBEAT_ROW_ID = "00000000-0000-4000-8000-000000000002"


def upgrade() -> None:
    op.create_table(
        "app_thresholds",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "correlation_confidence_threshold",
            sa.Float(),
            nullable=False,
        ),
        sa.Column("source_health_stale_seconds", sa.Integer(), nullable=False),
        sa.Column("source_health_max_failures", sa.Integer(), nullable=False),
        sa.Column("pihole_poll_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("unifi_poll_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("baseline_z_threshold", sa.Float(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_thresholds")),
    )

    op.create_table(
        "expected_activity_schedule",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column(
            "expected_hours_utc",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "days_of_week",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(person_id IS NOT NULL AND device_id IS NULL) OR "
            "(person_id IS NULL AND device_id IS NOT NULL)",
            name="ck_expected_activity_schedule_subject",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_expected_activity_schedule_person_id_person"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["device.id"],
            name=op.f("fk_expected_activity_schedule_device_id_device"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expected_activity_schedule")),
    )
    op.create_index(
        op.f("ix_expected_activity_schedule_person_id"),
        "expected_activity_schedule",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_expected_activity_schedule_device_id"),
        "expected_activity_schedule",
        ["device_id"],
        unique=False,
    )

    op.create_table(
        "worker_heartbeat",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker_heartbeat")),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeat")
    op.drop_index(
        op.f("ix_expected_activity_schedule_device_id"),
        table_name="expected_activity_schedule",
    )
    op.drop_index(
        op.f("ix_expected_activity_schedule_person_id"),
        table_name="expected_activity_schedule",
    )
    op.drop_table("expected_activity_schedule")
    op.drop_table("app_thresholds")
