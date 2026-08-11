"""One-shot connection probes for Pi-hole and UniFi (read-only authenticate)."""

from __future__ import annotations

from typing import Any

from app.config import Settings, settings
from app.connection_store import SECRET_UNCHANGED, resolve_ingest_settings
from app.ingest.pihole import PiholeClient, PiholeClientError
from app.ingest.unifi import UnifiClient, UnifiClientError
from app.models.settings import ConnectionSettings


def settings_from_test_payload(
    *,
    kind: str,
    body: dict[str, Any],
    row: ConnectionSettings | None,
    cfg: Settings | None = None,
) -> Settings:
    """Build Settings for a connection test from request body + stored/env values."""
    base = resolve_ingest_settings(row, cfg=cfg or settings)
    updates: dict[str, Any] = {}

    if kind == "pihole":
        if body.get("url"):
            updates["pihole_url"] = body["url"].rstrip("/")
        if body.get("auth_method"):
            updates["pihole_auth_method"] = body["auth_method"]
        if body.get("verify_tls") is not None:
            updates["pihole_verify_tls"] = body["verify_tls"]
        password = body.get("password")
        if password is not None and password != SECRET_UNCHANGED:
            updates["pihole_password"] = password
        token = body.get("token")
        if token is not None and token != SECRET_UNCHANGED:
            updates["pihole_token"] = token
    elif kind == "unifi":
        if body.get("url"):
            updates["unifi_url"] = body["url"].rstrip("/")
        if body.get("auth_method"):
            updates["unifi_auth_method"] = body["auth_method"]
        if body.get("username") is not None:
            updates["unifi_username"] = body["username"]
        if body.get("site"):
            updates["unifi_site"] = body["site"]
        if body.get("verify_tls") is not None:
            updates["unifi_verify_tls"] = body["verify_tls"]
        password = body.get("password")
        if password is not None and password != SECRET_UNCHANGED:
            updates["unifi_password"] = password
        token = body.get("token")
        if token is not None and token != SECRET_UNCHANGED:
            updates["unifi_token"] = token
    else:
        raise ValueError(f"Unknown connection test kind: {kind}")

    return base.model_copy(update=updates) if updates else base


async def test_pihole_connection(cfg: Settings) -> tuple[bool, str]:
    client = PiholeClient(cfg)
    try:
        await client.authenticate()
        # Light probe: fetch a small query window (read-only).
        await client.fetch_queries(length=1)
        return True, "Connected to Pi-hole and fetched queries"
    except PiholeClientError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 — surface any network/TLS error
        return False, f"Pi-hole connection failed: {exc}"
    finally:
        await client.aclose()


async def test_unifi_connection(cfg: Settings) -> tuple[bool, str]:
    client = UnifiClient(cfg)
    try:
        await client.authenticate()
        clients = await client.fetch_clients()
        return True, f"Connected to UniFi ({len(clients)} client(s) visible)"
    except UnifiClientError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 — surface any network/TLS error
        return False, f"UniFi connection failed: {exc}"
    finally:
        await client.aclose()
