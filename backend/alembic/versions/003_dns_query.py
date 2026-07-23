"""Add normalized dns_query table for Pi-hole ingestion.

Revision ID: 003_dns_query
Revises: 002_source_health_upsert
Create Date: 2026-07-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "003_dns_query"
down_revision: str | None = "002_source_health_upsert"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

dns_query_status = postgresql.ENUM(
    "allowed",
    "blocked",
    "cached",
    name="dns_query_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    dns_query_status.create(bind, checkfirst=True)

    op.create_table(
        "dns_query",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logic_version", sa.String(length=64), nullable=False),
        sa.Column("queried_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_identifier", sa.String(length=512), nullable=False),
        sa.Column("client_ip", sa.String(length=45), nullable=True),
        sa.Column("domain", sa.String(length=2048), nullable=False),
        sa.Column("query_type", sa.String(length=32), nullable=False),
        sa.Column("status", dns_query_status, nullable=False),
        sa.Column("upstream", sa.String(length=512), nullable=True),
        sa.Column("pihole_query_id", sa.String(length=64), nullable=True),
        sa.Column("raw_pihole_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingest_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingest_batch_id"],
            ["ingest_batch.id"],
            name=op.f("fk_dns_query_ingest_batch_id_ingest_batch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_pihole_event_id"],
            ["raw_pihole_event.id"],
            name=op.f("fk_dns_query_raw_pihole_event_id_raw_pihole_event"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dns_query")),
    )
    op.create_index(
        op.f("ix_dns_query_client_identifier_queried_at"),
        "dns_query",
        ["client_identifier", "queried_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dns_query_queried_at"),
        "dns_query",
        ["queried_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dns_query_raw_pihole_event_id"),
        "dns_query",
        ["raw_pihole_event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dns_query_ingest_batch_id"),
        "dns_query",
        ["ingest_batch_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dns_query_ingest_batch_id"), table_name="dns_query")
    op.drop_index(op.f("ix_dns_query_raw_pihole_event_id"), table_name="dns_query")
    op.drop_index(op.f("ix_dns_query_queried_at"), table_name="dns_query")
    op.drop_index(
        op.f("ix_dns_query_client_identifier_queried_at"),
        table_name="dns_query",
    )
    op.drop_table("dns_query")
    dns_query_status.drop(op.get_bind(), checkfirst=True)
