"""Add unique source + consecutive_failures to source_health.

Revision ID: 002_source_health_upsert
Revises: 001_initial_schema
Create Date: 2026-07-23

"""

from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "002_source_health_upsert"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _schema() -> str | None:
    """Honor disposable test schema (see alembic/env.py ALEMBIC_SCHEMA)."""
    value = os.environ.get("ALEMBIC_SCHEMA", "").strip()
    return value or None


def upgrade() -> None:
    schema = _schema()
    bind = op.get_bind()
    insp = inspect(bind)
    columns = {col["name"] for col in insp.get_columns("source_health", schema=schema)}
    if "consecutive_failures" not in columns:
        op.add_column(
            "source_health",
            sa.Column(
                "consecutive_failures",
                sa.Integer(),
                server_default="0",
                nullable=False,
            ),
            schema=schema,
        )

    uq_name = "uq_source_health_source"
    existing = {c["name"] for c in insp.get_unique_constraints("source_health", schema=schema)}
    # Also check indexes that may back a unique constraint.
    existing |= {i["name"] for i in insp.get_indexes("source_health", schema=schema) if i.get("unique")}
    if uq_name not in existing:
        op.create_unique_constraint(
            op.f(uq_name),
            "source_health",
            ["source"],
            schema=schema,
        )


def downgrade() -> None:
    schema = _schema()
    bind = op.get_bind()
    insp = inspect(bind)
    uq_name = "uq_source_health_source"
    existing = {c["name"] for c in insp.get_unique_constraints("source_health", schema=schema)}
    if uq_name in existing:
        op.drop_constraint(op.f(uq_name), "source_health", type_="unique", schema=schema)

    columns = {col["name"] for col in insp.get_columns("source_health", schema=schema)}
    if "consecutive_failures" in columns:
        op.drop_column("source_health", "consecutive_failures", schema=schema)
