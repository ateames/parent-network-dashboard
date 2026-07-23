"""Add finding table for versioned explainable findings.

Revision ID: 006_finding
Revises: 005_activity_baseline
Create Date: 2026-07-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "006_finding"
down_revision: str | None = "005_activity_baseline"
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
finding_status = postgresql.ENUM(
    "open",
    "acknowledged",
    "resolved",
    "dismissed",
    name="finding_status",
    create_type=False,
)
finding_confidence = postgresql.ENUM(
    "low",
    "medium",
    "high",
    name="finding_confidence",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    finding_severity.create(bind, checkfirst=True)
    finding_status.create(bind, checkfirst=True)
    finding_confidence.create(bind, checkfirst=True)

    op.create_table(
        "finding",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logic_version", sa.String(length=64), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("severity", finding_severity, nullable=False),
        sa.Column("status", finding_status, nullable=False),
        sa.Column("confidence", finding_confidence, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("why_flagged", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("subject_label", sa.String(length=255), nullable=False),
        sa.Column(
            "missing_info",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fingerprint", sa.String(length=512), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["device.id"],
            name=op.f("fk_finding_device_id_device"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_finding_person_id_person"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding")),
        sa.UniqueConstraint(
            "fingerprint",
            "logic_version",
            name="uq_finding_fingerprint_logic_version",
        ),
    )
    op.create_index("ix_finding_severity", "finding", ["severity"], unique=False)
    op.create_index("ix_finding_status", "finding", ["status"], unique=False)
    op.create_index("ix_finding_device_id", "finding", ["device_id"], unique=False)
    op.create_index("ix_finding_person_id", "finding", ["person_id"], unique=False)
    op.create_index("ix_finding_occurred_at", "finding", ["occurred_at"], unique=False)
    op.create_index("ix_finding_rule_id", "finding", ["rule_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_finding_rule_id", table_name="finding")
    op.drop_index("ix_finding_occurred_at", table_name="finding")
    op.drop_index("ix_finding_person_id", table_name="finding")
    op.drop_index("ix_finding_device_id", table_name="finding")
    op.drop_index("ix_finding_status", table_name="finding")
    op.drop_index("ix_finding_severity", table_name="finding")
    op.drop_table("finding")
    finding_confidence.drop(op.get_bind(), checkfirst=True)
    finding_status.drop(op.get_bind(), checkfirst=True)
    finding_severity.drop(op.get_bind(), checkfirst=True)
