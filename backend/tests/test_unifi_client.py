"""Unit tests for UnifiClient UniFi OS + Integration API token auth."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.ingest.unifi import (
    UnifiClient,
    UnifiClientError,
    format_unifi_http_error,
    map_integration_client,
    resolve_integration_site_id,
    unifi_os_network_path,
)


def test_unifi_os_network_path_rewrites_classic_api() -> None:
    assert (
        unifi_os_network_path("/api/s/default/stat/sta")
        == "/proxy/network/api/s/default/stat/sta"
    )
    assert unifi_os_network_path("api/s/default/stat/sta") == (
        "/proxy/network/api/s/default/stat/sta"
    )


def test_unifi_os_network_path_skips_already_proxied_and_absolute() -> None:
    assert unifi_os_network_path("/proxy/network/api/s/default/stat/sta") is None
    assert unifi_os_network_path("https://192.168.1.1/api/s/default/stat/sta") is None
    assert unifi_os_network_path("/other/path") is None


def test_resolve_integration_site_id_matches_name_and_internal() -> None:
    sites = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "internalReference": "default",
            "name": "Teames-house",
        }
    ]
    assert (
        resolve_integration_site_id(sites, "Teames-house")
        == "11111111-1111-1111-1111-111111111111"
    )
    assert (
        resolve_integration_site_id(sites, "default")
        == "11111111-1111-1111-1111-111111111111"
    )
    assert resolve_integration_site_id(sites, "missing") is None


def test_format_unifi_http_error_includes_body() -> None:
    response = httpx.Response(
        401,
        json={"code": "unauthorized", "message": "unauthorized"},
    )
    message = format_unifi_http_error("UniFi Integration GET /sites failed", response)
    assert "HTTP 401" in message
    assert "unauthorized" in message


def test_map_integration_client_to_classic_shape() -> None:
    mapped = map_integration_client(
        {
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "name": "ipad-child",
            "macAddress": "AA:BB:CC:DD:EE:01",
            "ipAddress": "192.168.1.50",
            "connectedAt": "2026-08-10T12:00:00Z",
            "type": "WIRELESS",
        }
    )
    assert mapped is not None
    assert mapped["mac"] == "AA:BB:CC:DD:EE:01"
    assert mapped["ip"] == "192.168.1.50"
    assert mapped["hostname"] == "ipad-child"
    assert mapped["is_wired"] is False


@pytest.mark.asyncio
async def test_token_uses_integration_api_and_resolves_site_name() -> None:
    site_id = "11111111-1111-1111-1111-111111111111"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers.get("X-API-KEY") == "test-api-key"
        assert request.headers.get("Accept") == "application/json"
        assert "Authorization" not in request.headers
        if request.url.path == "/proxy/network/integration/v1/sites":
            return httpx.Response(
                200,
                json={
                    "offset": 0,
                    "limit": 100,
                    "count": 1,
                    "totalCount": 1,
                    "data": [
                        {
                            "id": site_id,
                            "internalReference": "default",
                            "name": "Teames-house",
                        }
                    ],
                },
            )
        if request.url.path == f"/proxy/network/integration/v1/sites/{site_id}/clients":
            return httpx.Response(
                200,
                json={
                    "offset": 0,
                    "limit": 100,
                    "count": 1,
                    "totalCount": 1,
                    "data": [
                        {
                            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                            "name": "ipad-child",
                            "macAddress": "aa:bb:cc:dd:ee:01",
                            "ipAddress": "192.168.1.50",
                            "connectedAt": "2026-08-10T12:00:00Z",
                            "type": "WIRELESS",
                            "access": {"type": "DEFAULT"},
                            "uplinkDeviceId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                        }
                    ],
                },
            )
        return httpx.Response(500, json={"error": "unexpected", "path": request.url.path})

    transport = httpx.MockTransport(handler)
    cfg = Settings(
        unifi_url="https://192.168.1.1",
        unifi_auth_method="token",
        unifi_token="test-api-key",
        unifi_site="Teames-house",
        unifi_verify_tls=False,
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url=cfg.unifi_url,
    ) as http:
        client = UnifiClient(cfg, client=http)
        clients = await client.fetch_clients()

    assert len(clients) == 1
    assert clients[0]["mac"] == "aa:bb:cc:dd:ee:01"
    assert clients[0]["hostname"] == "ipad-child"
    assert calls == [
        "/proxy/network/integration/v1/sites",
        f"/proxy/network/integration/v1/sites/{site_id}/clients",
    ]


@pytest.mark.asyncio
async def test_token_401_surfaces_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Accept") == "application/json"
        return httpx.Response(
            401,
            json={"code": "unauthorized", "httpStatusCode": 401, "message": "unauthorized"},
        )

    transport = httpx.MockTransport(handler)
    cfg = Settings(
        unifi_url="https://192.168.1.1",
        unifi_auth_method="token",
        unifi_token="bad-key",
        unifi_site="default",
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url=cfg.unifi_url,
    ) as http:
        client = UnifiClient(cfg, client=http)
        with pytest.raises(UnifiClientError, match="unauthorized") as exc_info:
            await client.authenticate()
    assert "HTTP 401" in str(exc_info.value)


@pytest.mark.asyncio
async def test_token_unknown_site_lists_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/proxy/network/integration/v1/sites":
            return httpx.Response(
                200,
                json={
                    "offset": 0,
                    "limit": 100,
                    "count": 2,
                    "totalCount": 2,
                    "data": [
                        {
                            "id": "11111111-1111-1111-1111-111111111111",
                            "internalReference": "default",
                            "name": "Teames-house",
                        },
                        {
                            "id": "22222222-2222-2222-2222-222222222222",
                            "internalReference": "lab",
                            "name": "Lab",
                        },
                    ],
                },
            )
        return httpx.Response(500, json={})

    # Force two sites so sole-site fallback does not apply.
    transport = httpx.MockTransport(handler)
    cfg = Settings(
        unifi_url="https://192.168.1.1",
        unifi_auth_method="token",
        unifi_token="test-api-key",
        unifi_site="wrong-name",
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url=cfg.unifi_url,
    ) as http:
        client = UnifiClient(cfg, client=http)
        with pytest.raises(UnifiClientError, match="not found"):
            await client.authenticate()


@pytest.mark.asyncio
async def test_session_login_retries_unifi_os_auth_login() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/api/login":
            return httpx.Response(401, json={"error": "Unauthorized"})
        if request.method == "POST" and request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"meta": {"rc": "ok"}})
        if request.method == "GET" and request.url.path.startswith("/proxy/network/"):
            return httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
        if request.method == "GET" and request.url.path.startswith("/api/s/"):
            return httpx.Response(401, json={})
        return httpx.Response(500, json={})

    transport = httpx.MockTransport(handler)
    cfg = Settings(
        unifi_url="https://192.168.1.1",
        unifi_auth_method="session",
        unifi_username="admin",
        unifi_password="secret",
        unifi_login_path="/api/login",
        unifi_site="default",
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url=cfg.unifi_url,
    ) as http:
        client = UnifiClient(cfg, client=http)
        await client.authenticate()
        await client.fetch_clients()

    assert ("POST", "/api/login") in calls
    assert ("POST", "/api/auth/login") in calls
    assert client._prefer_unifi_os_paths is True
    assert ("GET", "/proxy/network/api/s/default/stat/sta") in calls


@pytest.mark.asyncio
async def test_token_missing_raises() -> None:
    cfg = Settings(unifi_auth_method="token", unifi_token="")
    client = UnifiClient(cfg, client=httpx.AsyncClient())
    with pytest.raises(UnifiClientError, match="UNIFI_TOKEN"):
        await client.authenticate()
    await client.aclose()
