"""Add finding feedback and suppression tables.

Revision ID: 007_finding_feedback
Revises: 006_finding
Create Date: 2026-07-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "007_finding_feedback"
down_revision: str | None = "006_finding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

finding_feedback_classification = postgresql.ENUM(
    "expected",
    "concerning",
    "incorrect",
    "ignore_once",
    "suppress_similar",
    "needs_investigation",
    "acknowledge",
    "resolve",
    name="finding_feedback_classification",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    finding_feedback_classification.create(bind, checkfirst=True)

    op.create_table(
        "finding_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classification", finding_feedback_classification, nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["finding.id"],
            name=op.f("fk_finding_feedback_finding_id_finding"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_feedback")),
    )
    op.create_index(
        "ix_finding_feedback_finding_id",
        "finding_feedback",
        ["finding_id"],
        unique=False,
    )
    op.create_index(
        "ix_finding_feedback_created_at",
        "finding_feedback",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "finding_suppression",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("matching_key", sa.String(length=512), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("domain_pattern", sa.String(length=255), nullable=False),
        sa.Column("source_finding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["device.id"],
            name=op.f("fk_finding_suppression_device_id_device"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_finding_suppression_person_id_person"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_finding_id"],
            ["finding.id"],
            name=op.f("fk_finding_suppression_source_finding_id_finding"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_suppression")),
        sa.UniqueConstraint(
            "matching_key",
            name="uq_finding_suppression_matching_key",
        ),
    )
    op.create_index(
        "ix_finding_suppression_rule_id",
        "finding_suppression",
        ["rule_id"],
        unique=False,
    )
    op.create_index(
        "ix_finding_suppression_created_at",
        "finding_suppression",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_finding_suppression_created_at", table_name="finding_suppression")
    op.drop_index("ix_finding_suppression_rule_id", table_name="finding_suppression")
    op.drop_table("finding_suppression")
    op.drop_index("ix_finding_feedback_created_at", table_name="finding_feedback")
    op.drop_index("ix_finding_feedback_finding_id", table_name="finding_feedback")
    op.drop_table("finding_feedback")
    finding_feedback_classification.drop(op.get_bind(), checkfirst=True)
