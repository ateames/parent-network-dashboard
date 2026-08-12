"""UniFi controller client: read-only ingest + client block/unblock writes."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.db import AsyncSessionLocal, engine
from app.health.source_health import record_attempt, record_failure, record_success
from app.identity.resolver import (
    LOGIC_VERSION as IDENTITY_LOGIC_VERSION,
)
from app.identity.resolver import (
    ClientObservation,
    normalize_mac,
    resolve_observation,
)
from app.models.enums import IngestBatchStatus, IngestSource
from app.models.identity import Device
from app.models.raw import IngestBatch, RawUnifiClient, RawUnifiEvent

logger = logging.getLogger(__name__)

# Device rows are versioned by the identity resolver; kept for callers/tests.
LOGIC_VERSION = IDENTITY_LOGIC_VERSION
IP_ASSIGNMENT_SOURCE = "unifi_api"


@dataclass(frozen=True, slots=True)
class NormalizedClient:
    """Structured fields extracted from one UniFi station/client payload."""

    mac: str
    unifi_client_id: str | None
    hostname: str | None
    ip: str | None
    uplink: str | None
    first_seen: datetime
    last_seen: datetime
    tx_bytes: int | None
    rx_bytes: int | None
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class UnifiSnapshot:
    """One read-only poll: clients, infrastructure, and recent events."""

    clients: list[dict[str, Any]]
    devices: list[dict[str, Any]]
    networks: list[dict[str, Any]]
    events: list[dict[str, Any]]


class UnifiClientError(RuntimeError):
    """Raised when a UniFi API call fails."""


class UnifiControlUnsupportedError(UnifiClientError):
    """Raised when client block/unblock requires session auth but token mode is set."""


_UNIFI_OS_RETRY_STATUSES = frozenset({401, 403, 404})
# GET /stat/event is gone or POST-only on Network 9/10; treat these as "no events".
_EVENTS_OPTIONAL_STATUSES = frozenset({400, 404})
_CLASSIC_LOGIN_PATH = "/api/login"
_UNIFI_OS_LOGIN_PATH = "/api/auth/login"
_UNIFI_OS_NETWORK_PREFIX = "/proxy/network"
# Official UniFi Integrations API (X-API-KEY). Classic /api/s/* rejects these keys.
_INTEGRATION_API_PREFIX = "/proxy/network/integration/v1"
_INTEGRATION_PAGE_LIMIT = 100
_HTTP_ERROR_BODY_MAX = 500
_CSRF_RESPONSE_HEADERS = ("x-updated-csrf-token", "x-csrf-token")
_CSRF_COOKIE_NAMES = ("csrf_token", "X-CSRF-Token")


def format_unifi_http_error(prefix: str, response: httpx.Response) -> str:
    """Build an error string with status and a truncated UniFi response body."""
    body = (response.text or "").strip().replace("\n", " ")
    if len(body) > _HTTP_ERROR_BODY_MAX:
        body = body[:_HTTP_ERROR_BODY_MAX] + "…"
    if body:
        return f"{prefix}: HTTP {response.status_code} — {body}"
    return f"{prefix}: HTTP {response.status_code}"


def csrf_token_from_jwt(token: str) -> str | None:
    """Read UniFi OS ``csrfToken`` from an unverified TOKEN JWT payload."""
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding)
        data = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    csrf = data.get("csrfToken") or data.get("csrf_token")
    if csrf is None:
        return None
    text = str(csrf).strip()
    return text or None


def csrf_token_from_response(response: httpx.Response) -> str | None:
    """CSRF from UniFi OS response headers or classic CSRF cookies."""
    for name in _CSRF_RESPONSE_HEADERS:
        value = response.headers.get(name)
        if value and value.strip():
            return value.strip()
    for name in _CSRF_COOKIE_NAMES:
        value = response.cookies.get(name)
        if value and str(value).strip():
            return str(value).strip()
    return None


def unifi_os_network_path(path: str) -> str | None:
    """Return UniFi OS proxied Network API path, or None if not applicable.

    Classic ``/api/s/...`` becomes ``/proxy/network/api/s/...``. Paths that
    already use the proxy prefix (or are absolute URLs) are left alone.
    """
    if path.startswith(("http://", "https://")):
        return None
    normalized = path if path.startswith("/") else f"/{path}"
    if normalized.startswith(f"{_UNIFI_OS_NETWORK_PREFIX}/"):
        return None
    if normalized.startswith("/api/"):
        return f"{_UNIFI_OS_NETWORK_PREFIX}{normalized}"
    return None


def map_integration_client(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Map Integration API client overview → classic-shaped client dict."""
    mac = row.get("macAddress") or row.get("mac")
    if not mac:
        return None
    connected = row.get("connectedAt")
    client_type = str(row.get("type") or "").upper()
    return {
        "_id": row.get("id"),
        "mac": mac,
        "hostname": row.get("name"),
        "name": row.get("name"),
        "ip": row.get("ipAddress") or row.get("ip"),
        "first_seen": connected,
        "last_seen": connected,
        "is_wired": client_type == "WIRED",
        "type": row.get("type"),
        "uplinkDeviceId": row.get("uplinkDeviceId"),
        "access": row.get("access"),
        "tx_bytes": row.get("tx_bytes"),
        "rx_bytes": row.get("rx_bytes"),
        "_integration": True,
    }


def map_integration_device(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Map Integration API adopted device → classic-shaped device dict."""
    mac = row.get("macAddress") or row.get("mac")
    if not mac:
        return None
    return {
        "_id": row.get("id"),
        "mac": mac,
        "name": row.get("name"),
        "hostname": row.get("name"),
        "ip": row.get("ipAddress") or row.get("ip"),
        "model": row.get("model"),
        "state": row.get("state"),
        "type": row.get("model"),
        "features": row.get("features"),
        "_integration": True,
    }


def map_integration_network(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map Integration API network overview → classic-ish networkconf dict."""
    return {
        "_id": row.get("id"),
        "name": row.get("name"),
        "vlan": row.get("vlanId"),
        "enabled": row.get("enabled"),
        "attr_hidden_id": "default" if row.get("default") else None,
        "purpose": "corporate",
        "_integration": True,
    }


def resolve_integration_site_id(
    sites: Sequence[Mapping[str, Any]],
    configured: str,
) -> str | None:
    """Match configured site against Integration id, internalReference, or name."""
    needle = configured.strip().lower()
    if not needle:
        return None
    for site in sites:
        candidates = (
            site.get("id"),
            site.get("internalReference"),
            site.get("name"),
        )
        for value in candidates:
            if value is not None and str(value).strip().lower() == needle:
                site_id = site.get("id")
                return str(site_id) if site_id else None
    return None


class UnifiClient:
    """httpx client for UniFi reads plus client block-sta / unblock-sta only."""

    def __init__(
        self,
        cfg: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cfg = cfg or settings
        self._owns_client = client is None
        base_url = self._cfg.unifi_url.rstrip("/")
        # UniFi OS consoles serve the API over HTTPS; http often 401s
        # or redirects oddly.
        if base_url.startswith("http://"):
            https_url = "https://" + base_url.removeprefix("http://")
            logger.info("UniFi URL used http://; upgrading to %s", https_url)
            base_url = https_url
        self._http = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=30.0,
            verify=self._cfg.unifi_verify_tls,
            follow_redirects=True,
        )
        self._authenticated = False
        # After a successful UniFi OS path retry, prefer proxy paths for later GETs.
        self._prefer_unifi_os_paths = False
        self._integration_site_id: str | None = None
        # UniFi OS POSTs require X-CSRF-Token; GETs work with the session cookie alone.
        self._csrf_token: str | None = None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> UnifiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def _uses_integration_api(self) -> bool:
        return self._cfg.unifi_auth_method.strip().lower() == "token"

    def _site_path(self, template: str) -> str:
        path = template.replace("{site}", self._cfg.unifi_site)
        if path.startswith(("http://", "https://")):
            return path
        return path if path.startswith("/") else f"/{path}"

    def _resolve_get_path(self, path_template: str) -> str:
        path = self._site_path(path_template)
        if self._prefer_unifi_os_paths:
            proxied = unifi_os_network_path(path)
            if proxied is not None:
                return proxied
        return path

    def _candidate_paths(self, path: str) -> list[str]:
        """Classic path plus UniFi OS /proxy/network variant when applicable."""
        paths = [path]
        proxied = unifi_os_network_path(path)
        if proxied is not None:
            paths.append(proxied)
        return paths

    def _session_origin(self) -> str | None:
        method = self._cfg.unifi_auth_method.strip().lower()
        if method not in {"session", "password"}:
            return None
        base = str(self._http.base_url).rstrip("/") or self._cfg.unifi_url.rstrip("/")
        if base.startswith("http://"):
            base = "https://" + base.removeprefix("http://")
        return base or None

    def _csrf_from_cookie_jar(self) -> str | None:
        for name in _CSRF_COOKIE_NAMES:
            value = self._http.cookies.get(name)
            if value and str(value).strip():
                return str(value).strip()
        token = self._http.cookies.get("TOKEN")
        if token:
            return csrf_token_from_jwt(token)
        return None

    def _remember_csrf(self, response: httpx.Response) -> None:
        captured = csrf_token_from_response(response)
        if captured:
            self._csrf_token = captured
            return
        if self._csrf_token:
            return
        jar_csrf = self._csrf_from_cookie_jar()
        if jar_csrf:
            self._csrf_token = jar_csrf

    def _auth_headers(self) -> dict[str, str]:
        method = self._cfg.unifi_auth_method.strip().lower()
        headers: dict[str, str] = {"Accept": "application/json"}
        if method == "token":
            token = self._cfg.unifi_token.strip()
            if token:
                # Integration API keys use X-API-KEY only (not classic session cookies).
                if token.lower().startswith("bearer "):
                    headers["Authorization"] = token
                else:
                    headers["X-API-KEY"] = token
        csrf = self._csrf_token or self._csrf_from_cookie_jar()
        if csrf:
            headers["X-CSRF-Token"] = csrf
        origin = self._session_origin()
        if origin:
            headers.setdefault("Origin", origin)
            headers.setdefault("Referer", f"{origin}/")
        return headers

    async def _send(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        headers = dict(self._auth_headers())
        if extra_headers:
            headers.update(extra_headers)
        kwargs: dict[str, Any] = {"headers": headers}
        if params is not None:
            kwargs["params"] = params
        if json_body is not None:
            kwargs["json"] = json_body
        response = await self._http.request(method, url, **kwargs)
        self._remember_csrf(response)
        return response

    async def authenticate(self) -> None:
        method = self._cfg.unifi_auth_method.strip().lower()
        if method in {"none", ""}:
            self._authenticated = True
            return
        if method == "token":
            if not self._cfg.unifi_token.strip():
                raise UnifiClientError("UNIFI_AUTH_METHOD=token requires UNIFI_TOKEN")
            await self._resolve_integration_site()
            self._authenticated = True
            return
        if method in {"session", "password"}:
            if not self._cfg.unifi_username or not self._cfg.unifi_password:
                raise UnifiClientError(
                    "UNIFI_AUTH_METHOD=session requires UNIFI_USERNAME and "
                    "UNIFI_PASSWORD"
                )
            login_path = self._site_path(self._cfg.unifi_login_path)
            payload = {
                "username": self._cfg.unifi_username,
                "password": self._cfg.unifi_password,
            }
            response = await self._send("POST", login_path, json_body=payload)
            if (
                response.status_code in _UNIFI_OS_RETRY_STATUSES
                and login_path.rstrip("/") == _CLASSIC_LOGIN_PATH
            ):
                logger.info(
                    "UniFi classic login returned HTTP %s; retrying UniFi OS login",
                    response.status_code,
                )
                response = await self._send(
                    "POST", _UNIFI_OS_LOGIN_PATH, json_body=payload
                )
                if response.status_code < 400:
                    self._prefer_unifi_os_paths = True
            if response.status_code >= 400:
                raise UnifiClientError(
                    format_unifi_http_error("UniFi login failed", response)
                )
            self._authenticated = True
            return
        raise UnifiClientError(f"Unknown UNIFI_AUTH_METHOD: {method!r}")

    async def _resolve_integration_site(self) -> str:
        """Validate API key and resolve site UUID from id / internalReference / name."""
        if self._integration_site_id:
            return self._integration_site_id
        sites = await self._integration_get_all(f"{_INTEGRATION_API_PREFIX}/sites")
        if not sites:
            raise UnifiClientError(
                "UniFi Integration API returned no sites — check the API key"
            )
        configured = (self._cfg.unifi_site or "default").strip()
        site_id = resolve_integration_site_id(sites, configured)
        if site_id is None and len(sites) == 1:
            only = sites[0].get("id")
            site_id = str(only) if only else None
            logger.info(
                "UniFi site %r not matched; using sole site id %s",
                configured,
                site_id,
            )
        if site_id is None:
            labels = [
                f"{s.get('name')} ({s.get('internalReference')})" for s in sites[:8]
            ]
            raise UnifiClientError(
                f"UniFi site {configured!r} not found. Available: {', '.join(labels)}"
            )
        self._integration_site_id = site_id
        return site_id

    async def _integration_get_all(self, path: str) -> list[dict[str, Any]]:
        """Paginate Integration API list endpoints (`data` + `totalCount`)."""
        offset = 0
        items: list[dict[str, Any]] = []
        while True:
            response = await self._send(
                "GET",
                path,
                params={"offset": offset, "limit": _INTEGRATION_PAGE_LIMIT},
            )
            if response.status_code >= 400:
                raise UnifiClientError(
                    format_unifi_http_error(
                        f"UniFi Integration GET {path} failed", response
                    )
                )
            body = response.json()
            if isinstance(body, list):
                return [item for item in body if isinstance(item, dict)]
            if not isinstance(body, Mapping):
                raise UnifiClientError("Unexpected UniFi Integration payload shape")
            page = body.get("data")
            if not isinstance(page, list):
                raise UnifiClientError("Unexpected UniFi Integration payload shape")
            page_dicts = [item for item in page if isinstance(item, dict)]
            items.extend(page_dicts)
            total = body.get("totalCount")
            offset += len(page_dicts)
            if not page_dicts:
                break
            if isinstance(total, int) and offset >= total:
                break
            if len(page_dicts) < _INTEGRATION_PAGE_LIMIT:
                break
        return items

    async def _get_data(self, path_template: str) -> list[dict[str, Any]]:
        if not self._authenticated:
            await self.authenticate()
        path = self._resolve_get_path(path_template)
        response = await self._send("GET", path)
        if response.status_code in _UNIFI_OS_RETRY_STATUSES:
            proxied = unifi_os_network_path(path)
            if proxied is not None:
                logger.info(
                    "UniFi GET %s returned HTTP %s; retrying %s",
                    path,
                    response.status_code,
                    proxied,
                )
                response = await self._send("GET", proxied)
                if response.status_code < 400:
                    self._prefer_unifi_os_paths = True
        if response.status_code >= 400:
            raise UnifiClientError(
                format_unifi_http_error(
                    f"UniFi GET {path_template} failed", response
                )
            )
        return extract_data_list(response.json())

    async def fetch_clients(self) -> list[dict[str, Any]]:
        """GET connected clients/stations. Read-only."""
        if self._uses_integration_api():
            if not self._authenticated:
                await self.authenticate()
            site_id = await self._resolve_integration_site()
            rows = await self._integration_get_all(
                f"{_INTEGRATION_API_PREFIX}/sites/{site_id}/clients"
            )
            mapped = [map_integration_client(row) for row in rows]
            return [row for row in mapped if row is not None]
        return await self._get_data(self._cfg.unifi_clients_path)

    async def fetch_devices(self) -> list[dict[str, Any]]:
        """GET UniFi infrastructure devices (APs/switches/gateways). Read-only."""
        if self._uses_integration_api():
            if not self._authenticated:
                await self.authenticate()
            site_id = await self._resolve_integration_site()
            rows = await self._integration_get_all(
                f"{_INTEGRATION_API_PREFIX}/sites/{site_id}/devices"
            )
            mapped = [map_integration_device(row) for row in rows]
            return [row for row in mapped if row is not None]
        return await self._get_data(self._cfg.unifi_devices_path)

    async def fetch_networks(self) -> list[dict[str, Any]]:
        """GET network configuration. Read-only."""
        if self._uses_integration_api():
            if not self._authenticated:
                await self.authenticate()
            site_id = await self._resolve_integration_site()
            rows = await self._integration_get_all(
                f"{_INTEGRATION_API_PREFIX}/sites/{site_id}/networks"
            )
            return [map_integration_network(row) for row in rows]
        return await self._get_data(self._cfg.unifi_networks_path)

    async def fetch_events(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Read recent controller events. Missing routes do not fail ingest.

        Classic GET ``/stat/event`` 404s on many UniFi Network 9/10 consoles.
        POST with a JSON body still works on some 9.x builds; Network 10.4+ has
        no events route at all. Syslog covers security events either way.
        """
        if self._uses_integration_api():
            # Integration API has no classic event feed; syslog covers security events.
            return []
        if not self._authenticated:
            await self.authenticate()
        event_limit = limit if limit is not None else self._cfg.unifi_events_limit
        params: dict[str, int] = {"_limit": event_limit}
        post_body = {"_limit": event_limit, "_sort": "-time"}
        path = self._resolve_get_path(self._cfg.unifi_events_path)
        candidates = self._candidate_paths(path)
        last: httpx.Response | None = None

        for url in candidates:
            response = await self._send("GET", url, params=params)
            last = response
            if response.status_code < 400:
                if url != path:
                    self._prefer_unifi_os_paths = True
                return extract_data_list(response.json())
            if (
                response.status_code not in _UNIFI_OS_RETRY_STATUSES
                and response.status_code not in _EVENTS_OPTIONAL_STATUSES
            ):
                raise UnifiClientError(
                    format_unifi_http_error("UniFi events failed", response)
                )

        if last is not None and last.status_code in _EVENTS_OPTIONAL_STATUSES:
            logger.info(
                "UniFi events GET returned HTTP %s; retrying POST %s",
                last.status_code,
                candidates,
            )
            post_headers = {"Content-Type": "application/json"}
            for url in candidates:
                response = await self._send(
                    "POST",
                    url,
                    json_body=post_body,
                    extra_headers=post_headers,
                )
                last = response
                if response.status_code < 400:
                    if url != path:
                        self._prefer_unifi_os_paths = True
                    return extract_data_list(response.json())
                if (
                    response.status_code not in _UNIFI_OS_RETRY_STATUSES
                    and response.status_code not in _EVENTS_OPTIONAL_STATUSES
                ):
                    raise UnifiClientError(
                        format_unifi_http_error("UniFi events failed", response)
                    )
            if last.status_code in _EVENTS_OPTIONAL_STATUSES:
                logger.warning(
                    "UniFi classic events API unavailable (HTTP %s); "
                    "continuing without events (syslog covers security events)",
                    last.status_code,
                )
                return []

        assert last is not None
        raise UnifiClientError(format_unifi_http_error("UniFi events failed", last))

    async def fetch_snapshot(self) -> UnifiSnapshot:
        """Pull clients, devices, networks, and events in one read-only cycle."""
        await self.authenticate()
        clients = await self.fetch_clients()
        devices = await self.fetch_devices()
        networks = await self.fetch_networks()
        events = await self.fetch_events()
        return UnifiSnapshot(
            clients=clients,
            devices=devices,
            networks=networks,
            events=events,
        )

    def _require_session_for_control(self) -> None:
        if self._uses_integration_api():
            raise UnifiControlUnsupportedError(
                "UniFi client block/unblock requires UNIFI_AUTH_METHOD=session "
                "(username/password). Token / Integrations API cannot issue stamgr."
            )

    async def _post_stamgr(self, *, cmd: str, mac: str) -> None:
        """POST classic /cmd/stamgr with UniFi OS /proxy/network retry."""
        self._require_session_for_control()
        try:
            normalized = normalize_mac(mac)
        except ValueError as exc:
            raise UnifiClientError(f"Invalid MAC for UniFi stamgr: {mac!r}") from exc
        if not self._authenticated:
            await self.authenticate()
        path = self._resolve_get_path(self._cfg.unifi_stamgr_path)
        payload = {"cmd": cmd, "mac": normalized}
        post_headers = {"Content-Type": "application/json"}
        response = await self._send(
            "POST", path, json_body=payload, extra_headers=post_headers
        )
        if response.status_code in _UNIFI_OS_RETRY_STATUSES:
            proxied = unifi_os_network_path(path)
            if proxied is not None:
                logger.info(
                    "UniFi POST %s returned HTTP %s; retrying %s",
                    path,
                    response.status_code,
                    proxied,
                )
                response = await self._send(
                    "POST",
                    proxied,
                    json_body=payload,
                    extra_headers=post_headers,
                )
                if response.status_code < 400:
                    self._prefer_unifi_os_paths = True
        if response.status_code >= 400:
            raise UnifiClientError(
                format_unifi_http_error(f"UniFi stamgr {cmd} failed", response)
            )
        # Classic API often returns HTTP 200 with meta.rc == "error".
        try:
            body = response.json()
        except ValueError:
            return
        if isinstance(body, Mapping):
            meta = body.get("meta")
            if isinstance(meta, Mapping) and str(meta.get("rc", "")).lower() == "error":
                msg = meta.get("msg") or meta.get("message") or "unknown error"
                raise UnifiClientError(f"UniFi stamgr {cmd} rejected: {msg}")

    async def block_client(self, mac: str) -> None:
        """Block a Wi‑Fi/LAN client by MAC (classic block-sta). Session auth only."""
        await self._post_stamgr(cmd="block-sta", mac=mac)

    async def unblock_client(self, mac: str) -> None:
        """Unblock a previously blocked client by MAC. Session auth only."""
        await self._post_stamgr(cmd="unblock-sta", mac=mac)


def extract_data_list(body: Any) -> list[dict[str, Any]]:
    """Accept a UniFi `{meta, data}` envelope or a bare list of objects."""
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, Mapping):
        data = body.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        clients = body.get("clients") or body.get("events")
        if isinstance(clients, list):
            return [item for item in clients if isinstance(item, dict)]
    raise UnifiClientError("Unexpected UniFi payload shape")


def load_fixture_payloads(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return extract_data_list(raw)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # UniFi uses unix seconds; reject absurd ms values by magnitude.
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if text.replace(".", "", 1).isdigit():
            return _parse_timestamp(float(text))
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(UTC)
    raise ValueError(f"Unsupported UniFi timestamp: {value!r}")


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_uplink(
    payload: Mapping[str, Any],
    *,
    devices_by_mac: Mapping[str, Mapping[str, Any]] | None = None,
) -> str | None:
    """Build a human-readable uplink label from client + optional device map."""
    parts: list[str] = []
    essid = _optional_str(payload.get("essid") or payload.get("ssid"))
    network = _optional_str(payload.get("network") or payload.get("network_name"))
    ap_mac_raw = _optional_str(payload.get("ap_mac"))
    sw_mac_raw = _optional_str(payload.get("sw_mac"))
    sw_port = payload.get("sw_port")

    if essid:
        parts.append(f"ssid={essid}")
    if network:
        parts.append(f"network={network}")

    if ap_mac_raw:
        try:
            ap_mac = normalize_mac(ap_mac_raw)
        except ValueError:
            ap_mac = ap_mac_raw.lower()
        ap_name = None
        if devices_by_mac and ap_mac in devices_by_mac:
            ap_name = _optional_str(
                devices_by_mac[ap_mac].get("name")
                or devices_by_mac[ap_mac].get("hostname")
            )
        parts.append(f"ap={ap_name or ap_mac}")

    if sw_mac_raw:
        try:
            sw_mac = normalize_mac(sw_mac_raw)
        except ValueError:
            sw_mac = sw_mac_raw.lower()
        sw_name = None
        if devices_by_mac and sw_mac in devices_by_mac:
            sw_name = _optional_str(
                devices_by_mac[sw_mac].get("name")
                or devices_by_mac[sw_mac].get("hostname")
            )
        port = f":{sw_port}" if sw_port not in (None, "") else ""
        parts.append(f"switch={sw_name or sw_mac}{port}")

    if not parts and payload.get("is_wired") is True:
        return "wired"
    return ", ".join(parts) if parts else None


def normalize_client(
    payload: Mapping[str, Any],
    *,
    devices_by_mac: Mapping[str, Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> NormalizedClient:
    """Pure normalization — unit-testable without I/O. Identity key is MAC."""
    now = now or datetime.now(UTC)
    mac_raw = payload.get("mac")
    if not mac_raw:
        raise ValueError("UniFi client missing mac")
    mac = normalize_mac(str(mac_raw))

    unifi_id = _optional_str(payload.get("_id") or payload.get("user_id"))
    hostname = _optional_str(payload.get("hostname") or payload.get("name"))
    ip = _optional_str(payload.get("ip") or payload.get("last_ip"))
    first = _parse_timestamp(payload.get("first_seen")) or now
    last = _parse_timestamp(payload.get("last_seen")) or now
    if last < first:
        first, last = last, first

    return NormalizedClient(
        mac=mac,
        unifi_client_id=unifi_id,
        hostname=hostname,
        ip=ip,
        uplink=resolve_uplink(payload, devices_by_mac=devices_by_mac),
        first_seen=first,
        last_seen=last,
        tx_bytes=_optional_int(payload.get("tx_bytes")),
        rx_bytes=_optional_int(payload.get("rx_bytes")),
        payload=dict(payload),
    )


def _device_mac_index(
    devices: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for device in devices:
        raw_mac = device.get("mac")
        if not raw_mac:
            continue
        try:
            out[normalize_mac(str(raw_mac))] = device
        except ValueError:
            continue
    return out


def observation_from_unifi_client(client: NormalizedClient) -> ClientObservation:
    """Map a normalized UniFi client into an identity observation."""
    return ClientObservation(
        observed_at=client.last_seen,
        source=IP_ASSIGNMENT_SOURCE,
        first_seen=client.first_seen,
        mac=client.mac,
        unifi_client_id=client.unifi_client_id,
        hostname=client.hostname,
        ip=client.ip,
    )


async def upsert_device_from_client(
    session: AsyncSession,
    client: NormalizedClient,
) -> Device:
    """Resolve durable device via identity resolver (MAC / UniFi id — never IP)."""
    return await resolve_observation(session, observation_from_unifi_client(client))


async def persist_snapshot(
    session: AsyncSession,
    snapshot: UnifiSnapshot,
    *,
    cfg: Settings | None = None,
    now: datetime | None = None,
) -> IngestBatch:
    """Write raw clients/events + normalize devices; update source_health."""
    cfg = cfg or settings
    now = now or datetime.now(UTC)
    source = IngestSource.UNIFI_API

    await record_attempt(session, source, now=now, cfg=cfg)

    batch = IngestBatch(
        source=source,
        started_at=now,
        status=IngestBatchStatus.RUNNING,
        record_count=0,
    )
    session.add(batch)
    await session.flush()

    try:
        devices_by_mac = _device_mac_index(snapshot.devices)
        # Device/network payloads are fetched for uplink enrichment only;
        # durable storage is raw clients + events (schema has no raw device table).
        _ = snapshot.networks

        normalized = [
            normalize_client(payload, devices_by_mac=devices_by_mac, now=now)
            for payload in snapshot.clients
        ]
        for row in normalized:
            session.add(
                RawUnifiClient(
                    payload=row.payload,
                    ingest_batch_id=batch.id,
                )
            )
            await upsert_device_from_client(session, row)

        for event_payload in snapshot.events:
            session.add(
                RawUnifiEvent(
                    payload=dict(event_payload),
                    ingest_batch_id=batch.id,
                )
            )

        finished = datetime.now(UTC)
        batch.record_count = len(normalized) + len(snapshot.events)
        batch.status = IngestBatchStatus.SUCCEEDED
        batch.finished_at = finished
        batch.error = None
        await record_success(
            session,
            source,
            detail=(
                f"Ingested {len(normalized)} clients, "
                f"{len(snapshot.events)} events "
                f"({len(snapshot.devices)} devices, "
                f"{len(snapshot.networks)} networks read)"
            ),
            now=finished,
            cfg=cfg,
        )
        await session.flush()
        return batch
    except Exception as exc:
        finished = datetime.now(UTC)
        batch.status = IngestBatchStatus.FAILED
        batch.finished_at = finished
        batch.error = str(exc)
        await record_failure(
            session,
            source,
            detail=str(exc),
            now=finished,
            cfg=cfg,
        )
        await session.flush()
        raise


async def ingest_from_snapshot(
    session: AsyncSession,
    snapshot: UnifiSnapshot,
    *,
    cfg: Settings | None = None,
    commit: bool = True,
) -> IngestBatch:
    try:
        batch = await persist_snapshot(session, snapshot, cfg=cfg)
    except Exception:
        if commit:
            await session.commit()
        raise
    if commit:
        await session.commit()
    return batch


async def _record_fetch_failure(
    session: AsyncSession,
    exc: BaseException,
    *,
    cfg: Settings,
    commit: bool,
) -> IngestBatch:
    now = datetime.now(UTC)
    await record_attempt(session, IngestSource.UNIFI_API, now=now, cfg=cfg)
    batch = IngestBatch(
        source=IngestSource.UNIFI_API,
        started_at=now,
        finished_at=now,
        status=IngestBatchStatus.FAILED,
        record_count=0,
        error=str(exc),
    )
    session.add(batch)
    await record_failure(
        session,
        IngestSource.UNIFI_API,
        detail=str(exc),
        now=now,
        cfg=cfg,
    )
    if commit:
        await session.commit()
    else:
        await session.flush()
    return batch


async def ingest_live(
    session: AsyncSession,
    *,
    cfg: Settings | None = None,
    client: UnifiClient | None = None,
    commit: bool = True,
) -> IngestBatch:
    cfg = cfg or settings
    owns = client is None
    unifi = client or UnifiClient(cfg)
    try:
        try:
            snapshot = await unifi.fetch_snapshot()
        except Exception as exc:
            await _record_fetch_failure(session, exc, cfg=cfg, commit=commit)
            raise
        return await ingest_from_snapshot(
            session, snapshot, cfg=cfg, commit=commit
        )
    finally:
        if owns:
            await unifi.aclose()


def resolve_replay_paths(path: Path) -> tuple[Path, Path]:
    """Resolve clients + events fixture paths from a file or directory."""
    if path.is_dir():
        clients = path / "unifi_clients_sample.json"
        events = path / "unifi_events_sample.json"
    elif path.is_file():
        clients = path
        events = path.parent / "unifi_events_sample.json"
    else:
        raise FileNotFoundError(f"Replay path not found: {path}")
    if not clients.is_file():
        raise FileNotFoundError(f"Clients fixture not found: {clients}")
    if not events.is_file():
        raise FileNotFoundError(f"Events fixture not found: {events}")
    return clients, events


async def replay_fixture(
    path: Path,
    *,
    cfg: Settings | None = None,
    session: AsyncSession | None = None,
    devices: Sequence[Mapping[str, Any]] | None = None,
    networks: Sequence[Mapping[str, Any]] | None = None,
) -> IngestBatch:
    """Ingest fixture files without contacting a live UniFi controller."""
    clients_path, events_path = resolve_replay_paths(path)
    snapshot = UnifiSnapshot(
        clients=load_fixture_payloads(clients_path),
        devices=[dict(d) for d in devices] if devices else [],
        networks=[dict(n) for n in networks] if networks else [],
        events=load_fixture_payloads(events_path),
    )
    if session is not None:
        return await ingest_from_snapshot(session, snapshot, cfg=cfg, commit=True)

    async with AsyncSessionLocal() as owned:
        try:
            return await ingest_from_snapshot(owned, snapshot, cfg=cfg, commit=True)
        except Exception:
            await owned.rollback()
            raise


async def run_poll_once(*, cfg: Settings | None = None) -> IngestBatch:
    cfg = cfg or settings
    async with AsyncSessionLocal() as session:
        try:
            return await ingest_live(session, cfg=cfg, commit=True)
        except Exception:
            await session.rollback()
            raise


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UniFi read-only ingest (live or fixture replay)",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        metavar="PATH",
        help=(
            "Ingest from fixtures instead of contacting UniFi. "
            "Pass a directory containing unifi_clients_sample.json and "
            "unifi_events_sample.json, or the clients fixture file path."
        ),
    )
    return parser


async def _async_main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [unifi-ingest] %(message)s",
    )
    try:
        if args.replay is not None:
            try:
                batch = await replay_fixture(args.replay)
            except FileNotFoundError as exc:
                logger.error("%s", exc)
                return 1
            logger.info(
                "replay ok batch_id=%s records=%s status=%s",
                batch.id,
                batch.record_count,
                batch.status.value,
            )
            return 0

        batch = await run_poll_once()
        logger.info(
            "poll ok batch_id=%s records=%s status=%s",
            batch.id,
            batch.record_count,
            batch.status.value,
        )
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_async_main(argv)))


if __name__ == "__main__":
    main()
