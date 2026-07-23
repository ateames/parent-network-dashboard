"""Add activity_baseline table for transparent per-subject baselines.

Revision ID: 005_activity_baseline
Revises: 004_dns_activity
Create Date: 2026-07-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "005_activity_baseline"
down_revision: str | None = "004_dns_activity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_baseline",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logic_version", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("window", sa.String(length=32), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "typical_active_hours_utc",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "day_of_week_patterns",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_baseline")),
        sa.UniqueConstraint(
            "subject_type",
            "subject_id",
            "window",
            "logic_version",
            "computed_at",
            name="uq_activity_baseline_subject_window_version_computed",
        ),
    )
    op.create_index(
        "ix_activity_baseline_subject_id",
        "activity_baseline",
        ["subject_id"],
        unique=False,
    )
    op.create_index(
        "ix_activity_baseline_subject_window_computed",
        "activity_baseline",
        ["subject_type", "subject_id", "window", "computed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_activity_baseline_subject_window_computed",
        table_name="activity_baseline",
    )
    op.drop_index("ix_activity_baseline_subject_id", table_name="activity_baseline")
    op.drop_table("activity_baseline")
