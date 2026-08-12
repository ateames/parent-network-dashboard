"""Unit tests for PiholeClient SID reuse / logout (no live Pi-hole)."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.ingest.pihole import PiholeClient, PiholeClientError, pihole_connection_key


def _password_cfg(**overrides: object) -> Settings:
    base = {
        "pihole_url": "http://pihole.test",
        "pihole_auth_method": "password",
        "pihole_password": "secret",
        "pihole_queries_path": "/api/queries",
        "pihole_auth_path": "/api/auth",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_password_auth_reuses_sid_across_fetches() -> None:
    auth_posts = 0
    query_gets = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_posts, query_gets
        if request.method == "POST" and request.url.path == "/api/auth":
            auth_posts += 1
            return httpx.Response(
                200,
                json={
                    "session": {
                        "valid": True,
                        "sid": "test-sid-1",
                        "csrf": "csrf",
                        "validity": 300,
                    }
                },
            )
        if request.method == "GET" and request.url.path == "/api/queries":
            query_gets += 1
            assert request.headers.get("X-FTL-SID") == "test-sid-1"
            return httpx.Response(200, json={"queries": []})
        if request.method == "DELETE" and request.url.path == "/api/auth":
            return httpx.Response(204)
        return httpx.Response(500, json={"error": "unexpected"})

    cfg = _password_cfg()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=cfg.pihole_url) as http:
        client = PiholeClient(cfg, client=http)
        await client.fetch_queries(length=1)
        await client.fetch_queries(length=1)
        await client.fetch_queries(length=1)
        assert auth_posts == 1
        assert query_gets == 3
        assert client.sid == "test-sid-1"
        await client.logout()
        assert client.sid is None


@pytest.mark.asyncio
async def test_queries_401_reauthenticates_once() -> None:
    auth_posts = 0
    query_sids: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_posts
        if request.method == "POST" and request.url.path == "/api/auth":
            auth_posts += 1
            sid = f"sid-{auth_posts}"
            return httpx.Response(
                200,
                json={"session": {"valid": True, "sid": sid, "validity": 300}},
            )
        if request.method == "GET" and request.url.path == "/api/queries":
            sid = request.headers.get("X-FTL-SID")
            query_sids.append(sid)
            if sid == "sid-1":
                return httpx.Response(401, json={"error": {"key": "unauthorized"}})
            return httpx.Response(200, json={"queries": [{"domain": "example.com"}]})
        if request.method == "DELETE" and request.url.path == "/api/auth":
            return httpx.Response(204)
        return httpx.Response(500, json={})

    cfg = _password_cfg()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=cfg.pihole_url) as http:
        client = PiholeClient(cfg, client=http)
        rows = await client.fetch_queries(length=1)
        assert len(rows) == 1
        assert auth_posts == 2
        assert query_sids == ["sid-1", "sid-2"]
        assert client.sid == "sid-2"


@pytest.mark.asyncio
async def test_aclose_logs_out_and_frees_sid() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST" and request.url.path == "/api/auth":
            return httpx.Response(
                200,
                json={"session": {"valid": True, "sid": "close-me", "validity": 300}},
            )
        if request.method == "GET" and request.url.path == "/api/queries":
            return httpx.Response(200, json={"queries": []})
        if request.method == "DELETE" and request.url.path == "/api/auth":
            assert request.headers.get("X-FTL-SID") == "close-me"
            return httpx.Response(204)
        return httpx.Response(500, json={})

    cfg = _password_cfg()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=cfg.pihole_url) as http:
        client = PiholeClient(cfg, client=http)
        await client.fetch_queries(length=1)
        await client.aclose()
        assert client.sid is None
        assert methods == ["POST", "GET", "DELETE"]


@pytest.mark.asyncio
async def test_auth_429_surfaces_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"key": "api_seats_exceeded"}})

    cfg = _password_cfg()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=cfg.pihole_url) as http:
        client = PiholeClient(cfg, client=http)
        with pytest.raises(PiholeClientError, match="HTTP 429"):
            await client.fetch_queries(length=1)


def test_pihole_connection_key_changes_with_credentials() -> None:
    a = _password_cfg(pihole_password="one")
    b = _password_cfg(pihole_password="two")
    c = _password_cfg(pihole_password="one", pihole_url="http://other.test")
    assert pihole_connection_key(a) == pihole_connection_key(
        _password_cfg(pihole_password="one")
    )
    assert pihole_connection_key(a) != pihole_connection_key(b)
    assert pihole_connection_key(a) != pihole_connection_key(c)
