"""Initial core domain schema.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-07-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ingest_source = postgresql.ENUM(
    "pihole_api",
    "unifi_api",
    "unifi_syslog",
    name="ingest_source",
    create_type=False,
)
ingest_batch_status = postgresql.ENUM(
    "running",
    "succeeded",
    "failed",
    name="ingest_batch_status",
    create_type=False,
)
identifier_kind = postgresql.ENUM(
    "mac",
    "unifi_client_id",
    "hostname",
    "pihole_client",
    "ip",
    name="identifier_kind",
    create_type=False,
)
person_role = postgresql.ENUM(
    "parent",
    "child",
    "other",
    name="person_role",
    create_type=False,
)
source_health_status = postgresql.ENUM(
    "ok",
    "degraded",
    "down",
    name="source_health_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    ingest_source.create(bind, checkfirst=True)
    ingest_batch_status.create(bind, checkfirst=True)
    identifier_kind.create(bind, checkfirst=True)
    person_role.create(bind, checkfirst=True)
    source_health_status.create(bind, checkfirst=True)

    op.create_table(
        "ingest_batch",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", ingest_source, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", ingest_batch_status, nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingest_batch")),
    )

    op.create_table(
        "raw_pihole_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ingest_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingest_batch_id"],
            ["ingest_batch.id"],
            name=op.f("fk_raw_pihole_event_ingest_batch_id_ingest_batch"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_pihole_event")),
    )
    op.create_index(
        op.f("ix_raw_pihole_event_ingest_batch_id"),
        "raw_pihole_event",
        ["ingest_batch_id"],
        unique=False,
    )

    op.create_table(
        "raw_unifi_client",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ingest_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingest_batch_id"],
            ["ingest_batch.id"],
            name=op.f("fk_raw_unifi_client_ingest_batch_id_ingest_batch"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_unifi_client")),
    )
    op.create_index(
        op.f("ix_raw_unifi_client_ingest_batch_id"),
        "raw_unifi_client",
        ["ingest_batch_id"],
        unique=False,
    )

    op.create_table(
        "raw_unifi_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ingest_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingest_batch_id"],
            ["ingest_batch.id"],
            name=op.f("fk_raw_unifi_event_ingest_batch_id_ingest_batch"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_unifi_event")),
    )
    op.create_index(
        op.f("ix_raw_unifi_event_ingest_batch_id"),
        "raw_unifi_event",
        ["ingest_batch_id"],
        unique=False,
    )

    op.create_table(
        "raw_unifi_syslog",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("raw_line", sa.Text(), nullable=False),
        sa.Column("parsed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ingest_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingest_batch_id"],
            ["ingest_batch.id"],
            name=op.f("fk_raw_unifi_syslog_ingest_batch_id_ingest_batch"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_unifi_syslog")),
    )
    op.create_index(
        op.f("ix_raw_unifi_syslog_ingest_batch_id"),
        "raw_unifi_syslog",
        ["ingest_batch_id"],
        unique=False,
    )

    op.create_table(
        "device",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logic_version", sa.String(length=64), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_unknown", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device")),
    )

    op.create_table(
        "person",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logic_version", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", person_role, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person")),
    )

    op.create_table(
        "source_health",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", ingest_source, nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", source_health_status, nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_health")),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_at"), "audit_log", ["at"], unique=False)

    op.create_table(
        "device_identifier",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logic_version", sa.String(length=64), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", identifier_kind, nullable=False),
        sa.Column("value", sa.String(length=512), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["device.id"],
            name=op.f("fk_device_identifier_device_id_device"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_identifier")),
        sa.UniqueConstraint(
            "kind",
            "value",
            name="uq_device_identifier_kind_value",
        ),
    )
    op.create_index(
        op.f("ix_device_identifier_device_id"),
        "device_identifier",
        ["device_id"],
        unique=False,
    )

    op.create_table(
        "ip_assignment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logic_version", sa.String(length=64), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("observed_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["device.id"],
            name=op.f("fk_ip_assignment_device_id_device"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ip_assignment")),
    )
    op.create_index(
        op.f("ix_ip_assignment_device_id"),
        "ip_assignment",
        ["device_id"],
        unique=False,
    )

    op.create_table(
        "person_device",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logic_version", sa.String(length=64), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by", sa.String(length=255), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["device.id"],
            name=op.f("fk_person_device_device_id_device"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_person_device_person_id_person"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_device")),
    )
    op.create_index(
        op.f("ix_person_device_device_id"),
        "person_device",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_person_device_person_id"),
        "person_device",
        ["person_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_person_device_person_id"), table_name="person_device")
    op.drop_index(op.f("ix_person_device_device_id"), table_name="person_device")
    op.drop_table("person_device")

    op.drop_index(op.f("ix_ip_assignment_device_id"), table_name="ip_assignment")
    op.drop_table("ip_assignment")

    op.drop_index(
        op.f("ix_device_identifier_device_id"),
        table_name="device_identifier",
    )
    op.drop_table("device_identifier")

    op.drop_index(op.f("ix_audit_log_at"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("source_health")
    op.drop_table("person")
    op.drop_table("device")

    op.drop_index(
        op.f("ix_raw_unifi_syslog_ingest_batch_id"),
        table_name="raw_unifi_syslog",
    )
    op.drop_table("raw_unifi_syslog")
    op.drop_index(
        op.f("ix_raw_unifi_event_ingest_batch_id"),
        table_name="raw_unifi_event",
    )
    op.drop_table("raw_unifi_event")
    op.drop_index(
        op.f("ix_raw_unifi_client_ingest_batch_id"),
        table_name="raw_unifi_client",
    )
    op.drop_table("raw_unifi_client")
    op.drop_index(
        op.f("ix_raw_pihole_event_ingest_batch_id"),
        table_name="raw_pihole_event",
    )
    op.drop_table("raw_pihole_event")
    op.drop_table("ingest_batch")

    bind = op.get_bind()
    source_health_status.drop(bind, checkfirst=True)
    person_role.drop(bind, checkfirst=True)
    identifier_kind.drop(bind, checkfirst=True)
    ingest_batch_status.drop(bind, checkfirst=True)
    ingest_source.drop(bind, checkfirst=True)
