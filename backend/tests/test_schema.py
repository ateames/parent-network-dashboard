"""Confirm Alembic initial migration creates the core domain tables."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import EXPECTED_TABLES


@pytest.mark.asyncio
async def test_alembic_creates_all_core_tables(
    migrated_engine: AsyncEngine,
    migrated_schema: str,
) -> None:
    async with migrated_engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = :schema
                  AND table_type = 'BASE TABLE'
                """
            ),
            {"schema": migrated_schema},
        )
        tables = {row[0] for row in result}

    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing tables after migration: {sorted(missing)}"
    assert "alembic_version" in tables


@pytest.mark.asyncio
async def test_derived_tables_have_logic_version(
    migrated_engine: AsyncEngine,
    migrated_schema: str,
) -> None:
    derived = {
        "device",
        "device_identifier",
        "ip_assignment",
        "person",
        "person_device",
        "dns_query",
        "dns_activity",
    }
    async with migrated_engine.connect() as conn:
        for table in sorted(derived):
            result = await conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                      AND table_name = :table
                      AND column_name = 'logic_version'
                    """
                ),
                {"schema": migrated_schema, "table": table},
            )
            assert result.first() is not None, f"{table} missing logic_version"
