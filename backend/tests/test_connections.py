"""Tests for encrypted connection settings and DB-over-env resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.connection_store import (
    decrypt_secret,
    encrypt_secret,
    get_connections_row,
    resolve_ingest_settings,
    upsert_connections,
    verify_dashboard_credentials,
)
from app.db import get_session
from app.main import app
from app.models.settings import CONNECTIONS_ROW_ID


@pytest.fixture
def conn_cfg() -> Settings:
    return Settings(
        connections_secret="test-connections-secret",
        admin_username="admin",
        admin_password="env-admin-pass",
        pihole_url="http://env-pihole.local",
        pihole_password="env-pihole-pass",
        unifi_url="https://env-unifi.local",
        unifi_username="env-unifi",
        unifi_password="env-unifi-pass",
    )


@pytest.fixture
async def api_client(
    migrated_engine: AsyncEngine,
    db_session: AsyncSession,
) -> AsyncClient:
    _ = db_session
    factory = async_sessionmaker(
        bind=migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def test_encrypt_decrypt_roundtrip(conn_cfg: Settings) -> None:
    cipher = encrypt_secret("super-secret", cfg=conn_cfg)
    assert cipher is not None
    assert cipher != "super-secret"
    assert decrypt_secret(cipher, cfg=conn_cfg) == "super-secret"


@pytest.mark.asyncio
async def test_db_overrides_env(
    db_session: AsyncSession,
    conn_cfg: Settings,
) -> None:
    await upsert_connections(
        db_session,
        {
            "pihole_url": "http://10.0.0.2",
            "pihole_password": "db-pihole",
            "unifi_url": "https://10.0.0.1",
            "unifi_username": "db-user",
            "unifi_password": "db-pass",
            "unifi_site": "home",
        },
        cfg=conn_cfg,
        mark_setup_complete=True,
    )
    await db_session.commit()

    row = await get_connections_row(db_session)
    assert row is not None
    assert row.id == CONNECTIONS_ROW_ID
    assert row.setup_completed_at is not None

    resolved = resolve_ingest_settings(row, cfg=conn_cfg)
    assert resolved.pihole_url == "http://10.0.0.2"
    assert resolved.pihole_password == "db-pihole"
    assert resolved.unifi_url == "https://10.0.0.1"
    assert resolved.unifi_username == "db-user"
    assert resolved.unifi_password == "db-pass"
    assert resolved.unifi_site == "home"


@pytest.mark.asyncio
async def test_env_fallback_when_no_row(
    db_session: AsyncSession,
    conn_cfg: Settings,
) -> None:
    row = await get_connections_row(db_session)
    assert row is None
    resolved = resolve_ingest_settings(None, cfg=conn_cfg)
    assert resolved.pihole_url == conn_cfg.pihole_url
    assert resolved.pihole_password == conn_cfg.pihole_password


@pytest.mark.asyncio
async def test_dashboard_verify_env_then_db(
    db_session: AsyncSession,
    conn_cfg: Settings,
) -> None:
    assert await verify_dashboard_credentials(
        db_session, "admin", "env-admin-pass", cfg=conn_cfg
    )
    assert not await verify_dashboard_credentials(
        db_session, "admin", "wrong", cfg=conn_cfg
    )

    await upsert_connections(
        db_session,
        {"dashboard_username": "family", "dashboard_password": "family-pass"},
        cfg=conn_cfg,
    )
    await db_session.commit()

    assert await verify_dashboard_credentials(
        db_session, "family", "family-pass", cfg=conn_cfg
    )
    assert not await verify_dashboard_credentials(
        db_session, "admin", "env-admin-pass", cfg=conn_cfg
    )


@pytest.mark.asyncio
async def test_connections_api_and_setup_status(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    _ = db_session

    status = await api_client.get("/api/settings/setup-status")
    assert status.status_code == 200
    assert status.json()["setup_completed"] is False

    put = await api_client.put(
        "/api/settings/connections",
        json={
            "pihole_url": "http://192.168.1.2",
            "pihole_auth_method": "password",
            "pihole_password": "secret",
            "unifi_url": "https://192.168.1.1",
            "unifi_auth_method": "session",
            "unifi_username": "ubnt",
            "unifi_password": "ubnt-pass",
            "unifi_site": "default",
            "mark_setup_complete": True,
        },
    )
    assert put.status_code == 200
    body = put.json()
    assert body["setup_completed"] is True
    assert body["pihole_url"] == "http://192.168.1.2"
    assert body["pihole_password_configured"] is True
    assert "pihole_password" not in body

    status2 = await api_client.get("/api/settings/setup-status")
    assert status2.json()["setup_completed"] is True

    got = await api_client.get("/api/settings/connections")
    assert got.status_code == 200
    assert got.json()["source"] == "db"


@pytest.mark.asyncio
async def test_pihole_connection_test_mocked(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    _ = db_session
    with patch(
        "app.api.settings.test_pihole_connection",
        new=AsyncMock(return_value=(True, "Connected to Pi-hole and fetched queries")),
    ):
        response = await api_client.post(
            "/api/settings/connections/test/pihole",
            json={
                "url": "http://192.168.1.2",
                "auth_method": "password",
                "password": "x",
            },
        )
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "message": "Connected to Pi-hole and fetched queries",
    }


@pytest.mark.asyncio
async def test_dashboard_verify_endpoint(
    db_session: AsyncSession,
    api_client: AsyncClient,
) -> None:
    _ = db_session
    # Uses process settings admin_* from env/defaults.
    from app.config import settings as app_settings

    bad = await api_client.post(
        "/api/settings/dashboard/verify",
        json={"username": "nope", "password": "nope"},
    )
    assert bad.status_code == 401

    ok = await api_client.post(
        "/api/settings/dashboard/verify",
        json={
            "username": app_settings.admin_username,
            "password": app_settings.admin_password,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["ok"] is True
