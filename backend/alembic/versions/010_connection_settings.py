"""Connection settings singleton for onboarding wizard credentials.

Revision ID: 010_connection_settings
Revises: 009_local_settings_system_health
Create Date: 2026-08-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "010_connection_settings"
down_revision: str | None = "009_local_settings_system_health"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONNECTIONS_ROW_ID = "00000000-0000-4000-8000-000000000003"


def upgrade() -> None:
    op.create_table(
        "connection_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pihole_url", sa.String(length=512), nullable=True),
        sa.Column("pihole_auth_method", sa.String(length=32), nullable=True),
        sa.Column("pihole_password_enc", sa.Text(), nullable=True),
        sa.Column("pihole_token_enc", sa.Text(), nullable=True),
        sa.Column("pihole_verify_tls", sa.Boolean(), nullable=True),
        sa.Column("unifi_url", sa.String(length=512), nullable=True),
        sa.Column("unifi_auth_method", sa.String(length=32), nullable=True),
        sa.Column("unifi_username", sa.String(length=255), nullable=True),
        sa.Column("unifi_password_enc", sa.Text(), nullable=True),
        sa.Column("unifi_token_enc", sa.Text(), nullable=True),
        sa.Column("unifi_site", sa.String(length=64), nullable=True),
        sa.Column("unifi_verify_tls", sa.Boolean(), nullable=True),
        sa.Column("dashboard_username", sa.String(length=255), nullable=True),
        sa.Column("dashboard_password_enc", sa.Text(), nullable=True),
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connection_settings")),
    )


def downgrade() -> None:
    op.drop_table("connection_settings")
