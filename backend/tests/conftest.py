"""Pytest fixtures — disposable test schema + migrated tables."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

# Truncated before each DB test so commits in one test do not leak into another.
_TRUNCATE_TABLES = (
    "finding_feedback",
    "finding_suppression",
    "finding",
    "activity_baseline",
    "dns_activity",
    "ip_assignment",
    "device_identifier",
    "person_device",
    "person",
    "device",
    "dns_query",
    "raw_pihole_event",
    "raw_unifi_client",
    "raw_unifi_event",
    "raw_unifi_syslog",
    "ingest_batch",
    "source_health",
    "audit_log",
)


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://parent:parent@localhost:5432/parent_network",
    )


@pytest.fixture(scope="session")
def database_url() -> str:
    return _database_url()


@pytest.fixture(scope="session")
def test_schema_name() -> str:
    """Unique schema per pytest session so runs do not clash."""
    return f"pnd_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def migrated_schema(
    database_url: str,
    test_schema_name: str,
    alembic_config: Config,
) -> Iterator[str]:
    """
    Create a disposable schema, apply Alembic migrations into it, yield the
    schema name, then drop the schema.

    Sync fixture so `alembic upgrade` can call asyncio.run() safely.
    """

    async def _create_schema() -> None:
        engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{test_schema_name}"'))
        finally:
            await engine.dispose()

    async def _drop_schema() -> None:
        engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(
                    text(f'DROP SCHEMA IF EXISTS "{test_schema_name}" CASCADE')
                )
        finally:
            await engine.dispose()

    asyncio.run(_create_schema())
    previous = os.environ.get("ALEMBIC_SCHEMA")
    os.environ["ALEMBIC_SCHEMA"] = test_schema_name
    try:
        command.upgrade(alembic_config, "head")
        yield test_schema_name
    finally:
        if previous is None:
            os.environ.pop("ALEMBIC_SCHEMA", None)
        else:
            os.environ["ALEMBIC_SCHEMA"] = previous
        asyncio.run(_drop_schema())


@pytest_asyncio.fixture
async def migrated_engine(
    database_url: str,
    migrated_schema: str,
) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": migrated_schema}},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(migrated_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Request-scoped session on a clean slate of domain tables."""
    factory = async_sessionmaker(
        bind=migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(_TRUNCATE_TABLES)
                + " RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
        yield session
        await session.rollback()
