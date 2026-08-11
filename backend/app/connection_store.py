"""Load / persist encrypted Pi-hole, UniFi, and dashboard connection settings."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.models.settings import CONNECTIONS_ROW_ID, ConnectionSettings

logger = logging.getLogger(__name__)

# Sentinel: client sent this to mean "leave the stored secret unchanged".
SECRET_UNCHANGED = "__unchanged__"


def _fernet(cfg: Settings | None = None) -> Fernet:
    """Derive a Fernet key from CONNECTIONS_SECRET (or ADMIN_TOKEN fallback)."""
    c = cfg or settings
    material = (c.connections_secret or "").strip() or c.admin_token
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None, *, cfg: Settings | None = None) -> str | None:
    if value is None:
        return None
    if value == "":
        return None
    return _fernet(cfg).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(
    ciphertext: str | None, *, cfg: Settings | None = None
) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet(cfg).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.warning("failed to decrypt connection secret; treating as unset")
        return None


def _timing_safe_equal(a: str, b: str) -> bool:
    a_b = a.encode("utf-8")
    b_b = b.encode("utf-8")
    if len(a_b) != len(b_b):
        return False
    return hmac.compare_digest(a_b, b_b)


async def get_connections_row(
    session: AsyncSession,
) -> ConnectionSettings | None:
    return await session.get(ConnectionSettings, CONNECTIONS_ROW_ID)


async def ensure_connections_row(session: AsyncSession) -> ConnectionSettings:
    row = await get_connections_row(session)
    if row is not None:
        return row
    row = ConnectionSettings(id=CONNECTIONS_ROW_ID)
    session.add(row)
    await session.flush()
    return row


def connections_public_dict(
    row: ConnectionSettings | None,
    *,
    cfg: Settings | None = None,
) -> dict[str, Any]:
    """API-safe view: never returns decrypted secrets, only configured flags."""
    c = cfg or settings
    if row is None:
        return {
            "pihole_url": c.pihole_url,
            "pihole_auth_method": c.pihole_auth_method,
            "pihole_password_configured": bool(c.pihole_password),
            "pihole_token_configured": bool(c.pihole_token),
            "pihole_verify_tls": c.pihole_verify_tls,
            "unifi_url": c.unifi_url,
            "unifi_auth_method": c.unifi_auth_method,
            "unifi_username": c.unifi_username or None,
            "unifi_password_configured": bool(c.unifi_password),
            "unifi_token_configured": bool(c.unifi_token),
            "unifi_site": c.unifi_site,
            "unifi_verify_tls": c.unifi_verify_tls,
            "dashboard_username": None,
            "dashboard_password_configured": False,
            "setup_completed": False,
            "setup_completed_at": None,
            "source": "env",
            "updated_at": None,
            "syslog_port": c.unifi_syslog_port,
            "syslog_enabled": c.unifi_syslog_enabled,
        }

    has_db_pihole = bool(
        row.pihole_url or row.pihole_password_enc or row.pihole_token_enc
    )
    has_db_unifi = bool(
        row.unifi_url
        or row.unifi_username
        or row.unifi_password_enc
        or row.unifi_token_enc
    )
    source = (
        "db"
        if (has_db_pihole or has_db_unifi or row.setup_completed_at)
        else "env"
    )

    return {
        "pihole_url": row.pihole_url or c.pihole_url,
        "pihole_auth_method": row.pihole_auth_method or c.pihole_auth_method,
        "pihole_password_configured": bool(
            row.pihole_password_enc or (not has_db_pihole and c.pihole_password)
        ),
        "pihole_token_configured": bool(
            row.pihole_token_enc or (not has_db_pihole and c.pihole_token)
        ),
        "pihole_verify_tls": (
            row.pihole_verify_tls
            if row.pihole_verify_tls is not None
            else c.pihole_verify_tls
        ),
        "unifi_url": row.unifi_url or c.unifi_url,
        "unifi_auth_method": row.unifi_auth_method or c.unifi_auth_method,
        "unifi_username": row.unifi_username
        if row.unifi_username is not None
        else (c.unifi_username or None),
        "unifi_password_configured": bool(
            row.unifi_password_enc or (not has_db_unifi and c.unifi_password)
        ),
        "unifi_token_configured": bool(
            row.unifi_token_enc or (not has_db_unifi and c.unifi_token)
        ),
        "unifi_site": row.unifi_site or c.unifi_site,
        "unifi_verify_tls": (
            row.unifi_verify_tls
            if row.unifi_verify_tls is not None
            else c.unifi_verify_tls
        ),
        "dashboard_username": row.dashboard_username,
        "dashboard_password_configured": bool(row.dashboard_password_enc),
        "setup_completed": row.setup_completed_at is not None,
        "setup_completed_at": row.setup_completed_at,
        "source": source,
        "updated_at": row.updated_at,
        "syslog_port": c.unifi_syslog_port,
        "syslog_enabled": c.unifi_syslog_enabled,
    }


async def load_connections_public(
    session: AsyncSession,
    *,
    cfg: Settings | None = None,
) -> dict[str, Any]:
    row = await get_connections_row(session)
    return connections_public_dict(row, cfg=cfg)


def resolve_ingest_settings(
    row: ConnectionSettings | None,
    *,
    cfg: Settings | None = None,
) -> Settings:
    """Return Settings with DB connection fields overlayed on env defaults."""
    base = cfg or settings
    if row is None:
        return base

    updates: dict[str, Any] = {}
    if row.pihole_url:
        updates["pihole_url"] = row.pihole_url
    if row.pihole_auth_method:
        updates["pihole_auth_method"] = row.pihole_auth_method
    if row.pihole_verify_tls is not None:
        updates["pihole_verify_tls"] = row.pihole_verify_tls
    password = decrypt_secret(row.pihole_password_enc, cfg=base)
    if password is not None:
        updates["pihole_password"] = password
    token = decrypt_secret(row.pihole_token_enc, cfg=base)
    if token is not None:
        updates["pihole_token"] = token

    if row.unifi_url:
        updates["unifi_url"] = row.unifi_url
    if row.unifi_auth_method:
        updates["unifi_auth_method"] = row.unifi_auth_method
    if row.unifi_username is not None:
        updates["unifi_username"] = row.unifi_username
    if row.unifi_site:
        updates["unifi_site"] = row.unifi_site
    if row.unifi_verify_tls is not None:
        updates["unifi_verify_tls"] = row.unifi_verify_tls
    unifi_password = decrypt_secret(row.unifi_password_enc, cfg=base)
    if unifi_password is not None:
        updates["unifi_password"] = unifi_password
    unifi_token = decrypt_secret(row.unifi_token_enc, cfg=base)
    if unifi_token is not None:
        updates["unifi_token"] = unifi_token

    if not updates:
        return base
    return base.model_copy(update=updates)


async def resolve_ingest_settings_from_db(
    session: AsyncSession,
    *,
    cfg: Settings | None = None,
) -> Settings:
    row = await get_connections_row(session)
    return resolve_ingest_settings(row, cfg=cfg)


def _apply_secret_field(
    row: ConnectionSettings,
    attr: str,
    value: str | None,
    *,
    cfg: Settings,
) -> None:
    if value is None or value == SECRET_UNCHANGED:
        return
    if value == "":
        setattr(row, attr, None)
        return
    setattr(row, attr, encrypt_secret(value, cfg=cfg))


async def upsert_connections(
    session: AsyncSession,
    patch: dict[str, Any],
    *,
    cfg: Settings | None = None,
    mark_setup_complete: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply connection updates. Secrets use SECRET_UNCHANGED to keep existing.

    Returns (before_public, after_public).
    """
    c = cfg or settings
    row = await ensure_connections_row(session)
    before = connections_public_dict(row, cfg=c)

    plain_fields = (
        "pihole_url",
        "pihole_auth_method",
        "pihole_verify_tls",
        "unifi_url",
        "unifi_auth_method",
        "unifi_username",
        "unifi_site",
        "unifi_verify_tls",
        "dashboard_username",
    )
    for key in plain_fields:
        if key in patch and patch[key] is not None:
            setattr(row, key, patch[key])

    if "pihole_password" in patch:
        _apply_secret_field(
            row, "pihole_password_enc", patch["pihole_password"], cfg=c
        )
    if "pihole_token" in patch:
        _apply_secret_field(row, "pihole_token_enc", patch["pihole_token"], cfg=c)
    if "unifi_password" in patch:
        _apply_secret_field(
            row, "unifi_password_enc", patch["unifi_password"], cfg=c
        )
    if "unifi_token" in patch:
        _apply_secret_field(row, "unifi_token_enc", patch["unifi_token"], cfg=c)
    if "dashboard_password" in patch:
        _apply_secret_field(
            row, "dashboard_password_enc", patch["dashboard_password"], cfg=c
        )

    if mark_setup_complete is True and row.setup_completed_at is None:
        row.setup_completed_at = datetime.now(UTC)
    elif mark_setup_complete is False:
        row.setup_completed_at = None

    row.updated_at = datetime.now(UTC)
    await session.flush()
    after = connections_public_dict(row, cfg=c)
    return before, after


async def verify_dashboard_credentials(
    session: AsyncSession,
    username: str,
    password: str,
    *,
    cfg: Settings | None = None,
) -> bool:
    """Check username/password against DB override, else env admin credentials."""
    c = cfg or settings
    row = await get_connections_row(session)
    if (
        row is not None
        and row.dashboard_username
        and row.dashboard_password_enc
    ):
        stored = decrypt_secret(row.dashboard_password_enc, cfg=c)
        if stored is None:
            return False
        return _timing_safe_equal(
            username, row.dashboard_username
        ) and _timing_safe_equal(password, stored)

    # Fallback: ADMIN_* (typically mirrored by DASHBOARD_* at install time).
    return _timing_safe_equal(username, c.admin_username) and _timing_safe_equal(
        password, c.admin_password
    )


async def is_setup_complete(session: AsyncSession) -> bool:
    row = await get_connections_row(session)
    return row is not None and row.setup_completed_at is not None
