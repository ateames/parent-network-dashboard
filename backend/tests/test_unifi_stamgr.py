"""UniFi stamgr block/unblock client command coverage."""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.ingest.unifi import (
    UnifiClient,
    UnifiClientError,
    UnifiControlUnsupportedError,
)


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
        ("/api/s/default/cmd/stamgr", {"cmd": "unblock-sta", "mac": "aa:bb:cc:dd:ee:01"}),
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
