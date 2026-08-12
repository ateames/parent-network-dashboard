"""UniFi stamgr block/unblock client command coverage."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.config import Settings
from app.ingest.unifi import (
    UnifiClient,
    UnifiClientError,
    UnifiControlUnsupportedError,
)


def _unifi_os_token_jwt(*, csrf: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"csrfToken": csrf}).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}.sig"


@pytest.mark.asyncio
async def test_block_client_posts_stamgr_with_session_auth() -> None:
    posts: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/login":
            return httpx.Response(200, json={"meta": {"rc": "ok"}})
        if request.method == "POST" and request.url.path.endswith("/cmd/stamgr"):
            body = json.loads(request.content.decode())
            posts.append((request.url.path, body))
            return httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
        return httpx.Response(500, json={"error": "unexpected"})

    cfg = Settings(
        unifi_url="https://192.168.1.1",
        unifi_auth_method="session",
        unifi_username="admin",
        unifi_password="secret",
        unifi_site="default",
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=cfg.unifi_url,
    ) as http:
        client = UnifiClient(cfg, client=http)
        await client.block_client("AA-BB-CC-DD-EE-01")
        await client.unblock_client("aa:bb:cc:dd:ee:01")

    assert posts == [
        ("/api/s/default/cmd/stamgr", {"cmd": "block-sta", "mac": "aa:bb:cc:dd:ee:01"}),
        (
            "/api/s/default/cmd/stamgr",
            {"cmd": "unblock-sta", "mac": "aa:bb:cc:dd:ee:01"},
        ),
    ]


@pytest.mark.asyncio
async def test_block_client_retries_unifi_os_proxy_path() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/login":
            return httpx.Response(200, json={"meta": {"rc": "ok"}})
        paths.append(request.url.path)
        if request.url.path == "/api/s/default/cmd/stamgr":
            return httpx.Response(404, json={"error": "not found"})
        if request.url.path == "/proxy/network/api/s/default/cmd/stamgr":
            return httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
        return httpx.Response(500, json={})

    cfg = Settings(
        unifi_url="https://192.168.1.1",
        unifi_auth_method="session",
        unifi_username="admin",
        unifi_password="secret",
        unifi_site="default",
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=cfg.unifi_url,
    ) as http:
        client = UnifiClient(cfg, client=http)
        await client.block_client("aa:bb:cc:dd:ee:02")

    assert "/api/s/default/cmd/stamgr" in paths
    assert "/proxy/network/api/s/default/cmd/stamgr" in paths


@pytest.mark.asyncio
async def test_block_client_rejects_token_mode() -> None:
    cfg = Settings(
        unifi_url="https://192.168.1.1",
        unifi_auth_method="token",
        unifi_token="api-key",
        unifi_site="default",
    )
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    async with httpx.AsyncClient(
        transport=transport,
        base_url=cfg.unifi_url,
    ) as http:
        client = UnifiClient(cfg, client=http)
        with pytest.raises(UnifiControlUnsupportedError, match="session"):
            await client.block_client("aa:bb:cc:dd:ee:03")


@pytest.mark.asyncio
async def test_block_client_sends_csrf_from_login_header() -> None:
    csrf = "csrf-from-login"
    stamgr_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/login":
            return httpx.Response(401, json={"error": "Unauthorized"})
        if request.method == "POST" and request.url.path == "/api/auth/login":
            return httpx.Response(
                200,
                json={"meta": {"rc": "ok"}},
                headers={"x-csrf-token": csrf},
            )
        if request.method == "POST" and request.url.path.endswith("/cmd/stamgr"):
            stamgr_headers.append(request.headers.get("X-CSRF-Token"))
            assert request.headers.get("Origin") == "https://192.168.1.1"
            return httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
        return httpx.Response(
            500, json={"error": "unexpected", "path": request.url.path}
        )

    cfg = Settings(
        unifi_url="https://192.168.1.1",
        unifi_auth_method="session",
        unifi_username="admin",
        unifi_password="secret",
        unifi_site="default",
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=cfg.unifi_url,
    ) as http:
        client = UnifiClient(cfg, client=http)
        await client.block_client("aa:bb:cc:dd:ee:05")

    assert stamgr_headers == [csrf]
    assert client._csrf_token == csrf


@pytest.mark.asyncio
async def test_block_client_sends_csrf_from_token_jwt() -> None:
    jwt_csrf = "csrf-from-jwt"
    token = _unifi_os_token_jwt(csrf=jwt_csrf)
    stamgr_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/login":
            return httpx.Response(
                200,
                json={"meta": {"rc": "ok"}},
                headers={"set-cookie": f"TOKEN={token}; Path=/; HttpOnly"},
            )
        if request.method == "POST" and request.url.path.endswith("/cmd/stamgr"):
            stamgr_headers.append(request.headers.get("X-CSRF-Token"))
            return httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
        return httpx.Response(500, json={"error": "unexpected"})

    cfg = Settings(
        unifi_url="https://192.168.1.1",
        unifi_auth_method="session",
        unifi_username="admin",
        unifi_password="secret",
        unifi_site="default",
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=cfg.unifi_url,
    ) as http:
        client = UnifiClient(cfg, client=http)
        await client.block_client("aa:bb:cc:dd:ee:06")

    assert stamgr_headers == [jwt_csrf]


@pytest.mark.asyncio
async def test_block_client_raises_on_meta_rc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/login":
            return httpx.Response(200, json={"meta": {"rc": "ok"}})
        return httpx.Response(
            200,
            json={"meta": {"rc": "error", "msg": "api.err.Invalid"}},
        )

    cfg = Settings(
        unifi_url="https://192.168.1.1",
        unifi_auth_method="session",
        unifi_username="admin",
        unifi_password="secret",
        unifi_site="default",
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=cfg.unifi_url,
    ) as http:
        client = UnifiClient(cfg, client=http)
        with pytest.raises(UnifiClientError, match="api.err.Invalid"):
            await client.block_client("aa:bb:cc:dd:ee:04")
