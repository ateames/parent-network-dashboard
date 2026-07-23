"""Read-only Pi-hole query ingestion (live poll + offline fixture replay)."""

from __future__ import annotations

import argparse
import asyncio
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
from app.identity.resolver import ClientObservation, resolve_observation
from app.models.dns import DnsQuery
from app.models.enums import DnsQueryStatus, IngestBatchStatus, IngestSource
from app.models.raw import IngestBatch, RawPiholeEvent

logger = logging.getLogger(__name__)

LOGIC_VERSION = "dns_query.v1"

# Pi-hole FTL status strings → normalized allowed / blocked / cached.
_BLOCKED_STATUSES = frozenset(
    {
        "GRAVITY",
        "REGEX",
        "DENYLIST",
        "EXTERNAL_BLOCKED_IP",
        "EXTERNAL_BLOCKED_NULL",
        "EXTERNAL_BLOCKED_NXRA",
        "EXTERNAL_BLOCKED_EDE15",
        "GRAVITY_CNAME",
        "REGEX_CNAME",
        "DENYLIST_CNAME",
        "DBBUSY",
        "SPECIAL_DOMAIN",
    }
)
_CACHED_STATUSES = frozenset({"CACHE", "CACHE_STALE"})


@dataclass(frozen=True, slots=True)
class NormalizedQuery:
    """Structured fields extracted from one Pi-hole query payload."""

    queried_at: datetime
    client_identifier: str
    client_ip: str | None
    domain: str
    query_type: str
    status: DnsQueryStatus
    upstream: str | None
    pihole_query_id: str | None
    payload: dict[str, Any]


class PiholeClientError(RuntimeError):
    """Raised when a read-only Pi-hole API call fails."""


class PiholeClient:
    """httpx client for Pi-hole query reads only — never writes config."""

    def __init__(
        self,
        cfg: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cfg = cfg or settings
        self._owns_client = client is None
        self._http = client or httpx.AsyncClient(
            base_url=self._cfg.pihole_url.rstrip("/"),
            timeout=30.0,
            verify=self._cfg.pihole_verify_tls,
        )
        self._sid: str | None = None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> PiholeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def _queries_url(self) -> str:
        path = self._cfg.pihole_queries_path
        if path.startswith(("http://", "https://")):
            return path
        return path if path.startswith("/") else f"/{path}"

    def _auth_url(self) -> str:
        path = self._cfg.pihole_auth_path
        if path.startswith(("http://", "https://")):
            return path
        return path if path.startswith("/") else f"/{path}"

    async def authenticate(self) -> None:
        method = self._cfg.pihole_auth_method.strip().lower()
        if method in {"none", ""}:
            self._sid = None
            return
        if method == "token":
            if not self._cfg.pihole_token:
                raise PiholeClientError(
                    "PIHOLE_AUTH_METHOD=token requires PIHOLE_TOKEN"
                )
            self._sid = None
            return
        if method == "password":
            if not self._cfg.pihole_password:
                # Open / passwordless Pi-hole — skip SID login.
                self._sid = None
                return
            response = await self._http.post(
                self._auth_url(),
                json={"password": self._cfg.pihole_password},
            )
            if response.status_code >= 400:
                raise PiholeClientError(
                    f"Pi-hole auth failed: HTTP {response.status_code}"
                )
            body = response.json()
            session = body.get("session") if isinstance(body, dict) else None
            sid = None
            if isinstance(session, dict):
                sid = session.get("sid")
            if not sid and isinstance(body, dict):
                sid = body.get("sid")
            if not sid:
                raise PiholeClientError("Pi-hole auth response missing session sid")
            self._sid = str(sid)
            return
        raise PiholeClientError(f"Unknown PIHOLE_AUTH_METHOD: {method!r}")

    def _auth_params(self) -> dict[str, str]:
        method = self._cfg.pihole_auth_method.strip().lower()
        if method == "token":
            return {"auth": self._cfg.pihole_token}
        return {}

    def _auth_headers(self) -> dict[str, str]:
        if self._sid:
            return {"X-FTL-SID": self._sid, "sid": self._sid}
        return {}

    async def fetch_queries(
        self,
        *,
        length: int | None = None,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        """GET recent queries. Read-only — never mutates Pi-hole config."""
        await self.authenticate()
        params: dict[str, str | int | float] = {
            "length": length if length is not None else self._cfg.pihole_query_length,
        }
        params.update(self._auth_params())
        if since is not None:
            params["from"] = since

        response = await self._http.get(
            self._queries_url(),
            params=params,
            headers=self._auth_headers(),
        )
        if response.status_code >= 400:
            raise PiholeClientError(
                f"Pi-hole queries failed: HTTP {response.status_code}"
            )
        body = response.json()
        return extract_query_payloads(body)


def extract_query_payloads(body: Any) -> list[dict[str, Any]]:
    """Accept a full API envelope or a bare list of query objects."""
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, Mapping):
        queries = body.get("queries")
        if isinstance(queries, list):
            return [item for item in queries if isinstance(item, dict)]
        data = body.get("data")
        if isinstance(data, list):
            # Legacy getAllQueries rows are arrays; wrap for raw preservation.
            out: list[dict[str, Any]] = []
            for row in data:
                if isinstance(row, dict):
                    out.append(row)
                elif isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
                    out.append({"legacy_row": list(row)})
            return out
    raise PiholeClientError("Unexpected Pi-hole queries payload shape")


def load_fixture_queries(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return extract_query_payloads(raw)


def map_pihole_status(raw_status: str | None) -> DnsQueryStatus:
    if not raw_status:
        return DnsQueryStatus.ALLOWED
    key = raw_status.strip().upper()
    if key in _CACHED_STATUSES:
        return DnsQueryStatus.CACHED
    if key in _BLOCKED_STATUSES:
        return DnsQueryStatus.BLOCKED
    return DnsQueryStatus.ALLOWED


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if text.replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(float(text), tz=UTC)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(UTC)
    raise ValueError(f"Unsupported Pi-hole timestamp: {value!r}")


def _client_fields(payload: Mapping[str, Any]) -> tuple[str, str | None]:
    client = payload.get("client")
    ip: str | None = None
    name: str | None = None
    if isinstance(client, Mapping):
        raw_ip = client.get("ip")
        raw_name = client.get("name")
        ip = str(raw_ip).strip() if raw_ip not in (None, "") else None
        name = str(raw_name).strip() if raw_name not in (None, "") else None
    elif isinstance(client, str) and client.strip():
        ip = client.strip()
    else:
        for key in ("client_ip", "ip"):
            raw = payload.get(key)
            if raw not in (None, ""):
                ip = str(raw).strip()
                break
        raw_name = payload.get("client_name") or payload.get("name")
        if raw_name not in (None, ""):
            name = str(raw_name).strip()

    identifier = name or ip
    if not identifier:
        raise ValueError("Pi-hole query missing client identifier")
    return identifier, ip


def normalize_query(payload: Mapping[str, Any]) -> NormalizedQuery:
    """Pure normalization — unit-testable without I/O."""
    if "legacy_row" in payload:
        raise ValueError("Legacy array rows are not supported; use v6 query objects")

    time_value = payload.get("time", payload.get("timestamp"))
    if time_value is None:
        raise ValueError("Pi-hole query missing timestamp")
    queried_at = _parse_timestamp(time_value)

    domain_raw = payload.get("domain")
    if not domain_raw:
        raise ValueError("Pi-hole query missing domain")
    domain = str(domain_raw).strip()

    query_type_raw = payload.get("type") or payload.get("query_type") or "UNKNOWN"
    query_type = str(query_type_raw).strip() or "UNKNOWN"

    status_raw = payload.get("status")
    status = map_pihole_status(str(status_raw) if status_raw is not None else None)

    upstream_raw = payload.get("upstream")
    upstream = (
        str(upstream_raw).strip()
        if upstream_raw not in (None, "")
        else None
    )

    client_identifier, client_ip = _client_fields(payload)

    qid = payload.get("id")
    pihole_query_id = str(qid) if qid is not None else None

    return NormalizedQuery(
        queried_at=queried_at,
        client_identifier=client_identifier,
        client_ip=client_ip,
        domain=domain,
        query_type=query_type,
        status=status,
        upstream=upstream,
        pihole_query_id=pihole_query_id,
        payload=dict(payload),
    )


async def persist_queries(
    session: AsyncSession,
    payloads: Sequence[Mapping[str, Any]],
    *,
    cfg: Settings | None = None,
    now: datetime | None = None,
) -> IngestBatch:
    """Write raw + normalized rows for one batch; update source_health."""
    cfg = cfg or settings
    now = now or datetime.now(UTC)
    source = IngestSource.PIHOLE_API

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
        normalized_rows = [normalize_query(payload) for payload in payloads]
        for row in normalized_rows:
            raw = RawPiholeEvent(
                source_ts=row.queried_at,
                payload=row.payload,
                ingest_batch_id=batch.id,
            )
            session.add(raw)
            await session.flush()
            session.add(
                DnsQuery(
                    logic_version=LOGIC_VERSION,
                    queried_at=row.queried_at,
                    client_identifier=row.client_identifier,
                    client_ip=row.client_ip,
                    domain=row.domain,
                    query_type=row.query_type,
                    status=row.status,
                    upstream=row.upstream,
                    pihole_query_id=row.pihole_query_id,
                    raw_pihole_event_id=raw.id,
                    ingest_batch_id=batch.id,
                )
            )
            # Durable identity: Pi-hole client name is weak/unknown without MAC.
            # Never merge into an existing device on shared IP alone.
            pihole_client = (
                row.client_identifier
                if row.client_ip is None or row.client_identifier != row.client_ip
                else None
            )
            await resolve_observation(
                session,
                ClientObservation(
                    observed_at=row.queried_at,
                    source="pihole_api",
                    first_seen=row.queried_at,
                    pihole_client=pihole_client,
                    ip=row.client_ip,
                ),
            )

        finished = datetime.now(UTC)
        batch.record_count = len(normalized_rows)
        batch.status = IngestBatchStatus.SUCCEEDED
        batch.finished_at = finished
        batch.error = None
        await record_success(
            session,
            source,
            detail=f"Ingested {batch.record_count} queries",
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


async def ingest_from_payloads(
    session: AsyncSession,
    payloads: Sequence[Mapping[str, Any]],
    *,
    cfg: Settings | None = None,
    commit: bool = True,
) -> IngestBatch:
    try:
        batch = await persist_queries(session, payloads, cfg=cfg)
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
    await record_attempt(session, IngestSource.PIHOLE_API, now=now, cfg=cfg)
    batch = IngestBatch(
        source=IngestSource.PIHOLE_API,
        started_at=now,
        finished_at=now,
        status=IngestBatchStatus.FAILED,
        record_count=0,
        error=str(exc),
    )
    session.add(batch)
    await record_failure(
        session,
        IngestSource.PIHOLE_API,
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
    client: PiholeClient | None = None,
    since: float | None = None,
    commit: bool = True,
) -> IngestBatch:
    cfg = cfg or settings
    owns = client is None
    pihole = client or PiholeClient(cfg)
    try:
        try:
            payloads = await pihole.fetch_queries(since=since)
        except Exception as exc:
            await _record_fetch_failure(session, exc, cfg=cfg, commit=commit)
            raise
        return await ingest_from_payloads(
            session, payloads, cfg=cfg, commit=commit
        )
    finally:
        if owns:
            await pihole.aclose()


async def replay_fixture(
    path: Path,
    *,
    cfg: Settings | None = None,
    session: AsyncSession | None = None,
) -> IngestBatch:
    """Ingest a fixture file without contacting a live Pi-hole."""
    payloads = load_fixture_queries(path)
    if session is not None:
        return await ingest_from_payloads(session, payloads, cfg=cfg, commit=True)

    async with AsyncSessionLocal() as owned:
        try:
            batch = await ingest_from_payloads(owned, payloads, cfg=cfg, commit=True)
            return batch
        except Exception:
            await owned.rollback()
            raise


async def run_poll_once(
    *,
    cfg: Settings | None = None,
    since: float | None = None,
) -> IngestBatch:
    cfg = cfg or settings
    async with AsyncSessionLocal() as session:
        try:
            return await ingest_live(session, cfg=cfg, since=since, commit=True)
        except Exception:
            await session.rollback()
            raise


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pi-hole read-only ingest (live or fixture replay)",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        metavar="FIXTURE",
        help="Ingest queries from a JSON fixture instead of contacting Pi-hole",
    )
    return parser


async def _async_main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [pihole-ingest] %(message)s",
    )
    try:
        if args.replay is not None:
            path = args.replay
            if not path.is_file():
                logger.error("Fixture not found: %s", path)
                return 1
            batch = await replay_fixture(path)
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
