"""Read-only UniFi controller ingestion (live poll + offline fixture replay)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.db import AsyncSessionLocal, engine
from app.health.source_health import record_attempt, record_failure, record_success
from app.models.enums import (
    IdentifierKind,
    IngestBatchStatus,
    IngestSource,
)
from app.models.identity import Device, DeviceIdentifier, IpAssignment
from app.models.raw import IngestBatch, RawUnifiClient, RawUnifiEvent

logger = logging.getLogger(__name__)

LOGIC_VERSION = "unifi_device.v1"
IP_ASSIGNMENT_SOURCE = "unifi_api"

_MAC_RE = re.compile(r"[^0-9a-fA-F]")
_CONFIDENCE_MAC = Decimal("1.0000")
_CONFIDENCE_UNIFI_ID = Decimal("1.0000")
_CONFIDENCE_HOSTNAME = Decimal("0.8000")


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
    """Raised when a read-only UniFi API call fails."""


class UnifiClient:
    """httpx client for UniFi controller reads only — never writes config."""

    def __init__(
        self,
        cfg: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cfg = cfg or settings
        self._owns_client = client is None
        self._http = client or httpx.AsyncClient(
            base_url=self._cfg.unifi_url.rstrip("/"),
            timeout=30.0,
            verify=self._cfg.unifi_verify_tls,
            follow_redirects=True,
        )
        self._authenticated = False

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> UnifiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def _site_path(self, template: str) -> str:
        path = template.replace("{site}", self._cfg.unifi_site)
        if path.startswith(("http://", "https://")):
            return path
        return path if path.startswith("/") else f"/{path}"

    def _auth_headers(self) -> dict[str, str]:
        method = self._cfg.unifi_auth_method.strip().lower()
        headers: dict[str, str] = {}
        if method == "token":
            token = self._cfg.unifi_token.strip()
            if token:
                # UniFi OS API key or bearer-style token.
                if token.lower().startswith("bearer "):
                    headers["Authorization"] = token
                else:
                    headers["X-API-KEY"] = token
                    headers["Authorization"] = f"Bearer {token}"
        # Classic controllers may require CSRF from the cookie jar.
        csrf = self._http.cookies.get("csrf_token") or self._http.cookies.get(
            "X-CSRF-Token"
        )
        if csrf:
            headers["X-CSRF-Token"] = csrf
        return headers

    async def authenticate(self) -> None:
        method = self._cfg.unifi_auth_method.strip().lower()
        if method in {"none", ""}:
            self._authenticated = True
            return
        if method == "token":
            if not self._cfg.unifi_token.strip():
                raise UnifiClientError("UNIFI_AUTH_METHOD=token requires UNIFI_TOKEN")
            self._authenticated = True
            return
        if method in {"session", "password"}:
            if not self._cfg.unifi_username or not self._cfg.unifi_password:
                raise UnifiClientError(
                    "UNIFI_AUTH_METHOD=session requires UNIFI_USERNAME and "
                    "UNIFI_PASSWORD"
                )
            login_path = self._site_path(self._cfg.unifi_login_path)
            response = await self._http.post(
                login_path,
                json={
                    "username": self._cfg.unifi_username,
                    "password": self._cfg.unifi_password,
                },
                headers=self._auth_headers(),
            )
            if response.status_code >= 400:
                raise UnifiClientError(
                    f"UniFi login failed: HTTP {response.status_code}"
                )
            self._authenticated = True
            return
        raise UnifiClientError(f"Unknown UNIFI_AUTH_METHOD: {method!r}")

    async def _get_data(self, path_template: str) -> list[dict[str, Any]]:
        if not self._authenticated:
            await self.authenticate()
        response = await self._http.get(
            self._site_path(path_template),
            headers=self._auth_headers(),
        )
        if response.status_code >= 400:
            raise UnifiClientError(
                f"UniFi GET {path_template} failed: HTTP {response.status_code}"
            )
        return extract_data_list(response.json())

    async def fetch_clients(self) -> list[dict[str, Any]]:
        """GET connected clients/stations. Read-only."""
        return await self._get_data(self._cfg.unifi_clients_path)

    async def fetch_devices(self) -> list[dict[str, Any]]:
        """GET UniFi infrastructure devices (APs/switches/gateways). Read-only."""
        return await self._get_data(self._cfg.unifi_devices_path)

    async def fetch_networks(self) -> list[dict[str, Any]]:
        """GET network configuration. Read-only."""
        return await self._get_data(self._cfg.unifi_networks_path)

    async def fetch_events(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """GET recent controller events. Read-only."""
        if not self._authenticated:
            await self.authenticate()
        params: dict[str, int] = {
            "_limit": limit if limit is not None else self._cfg.unifi_events_limit,
        }
        response = await self._http.get(
            self._site_path(self._cfg.unifi_events_path),
            params=params,
            headers=self._auth_headers(),
        )
        if response.status_code >= 400:
            raise UnifiClientError(
                f"UniFi events failed: HTTP {response.status_code}"
            )
        return extract_data_list(response.json())

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


def normalize_mac(value: str) -> str:
    """Canonical durable MAC: lowercase colon-separated."""
    hex_only = _MAC_RE.sub("", value.strip()).lower()
    if len(hex_only) != 12:
        raise ValueError(f"Invalid MAC address: {value!r}")
    return ":".join(hex_only[i : i + 2] for i in range(0, 12, 2))


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


async def _find_device_by_identifier(
    session: AsyncSession,
    kind: IdentifierKind,
    value: str,
) -> Device | None:
    result = await session.execute(
        select(Device)
        .join(DeviceIdentifier, DeviceIdentifier.device_id == Device.id)
        .where(
            DeviceIdentifier.kind == kind,
            DeviceIdentifier.value == value,
        )
    )
    return result.scalars().first()


async def _upsert_identifier(
    session: AsyncSession,
    device: Device,
    *,
    kind: IdentifierKind,
    value: str,
    confidence: Decimal,
    first_seen: datetime,
    last_seen: datetime,
) -> None:
    result = await session.execute(
        select(DeviceIdentifier).where(
            DeviceIdentifier.kind == kind,
            DeviceIdentifier.value == value,
        )
    )
    existing = result.scalars().first()
    if existing is None:
        session.add(
            DeviceIdentifier(
                logic_version=LOGIC_VERSION,
                device_id=device.id,
                kind=kind,
                value=value,
                confidence=confidence,
                first_seen=first_seen,
                last_seen=last_seen,
            )
        )
        return
    if existing.device_id != device.id:
        # Conflicting evidence: leave the other binding; do not steal the key.
        logger.warning(
            "identifier conflict kind=%s value=%s existing_device=%s new_device=%s",
            kind.value,
            value,
            existing.device_id,
            device.id,
        )
        return
    if first_seen < existing.first_seen:
        existing.first_seen = first_seen
    if last_seen > existing.last_seen:
        existing.last_seen = last_seen
    existing.confidence = confidence
    existing.logic_version = LOGIC_VERSION


async def _update_ip_assignment(
    session: AsyncSession,
    device: Device,
    *,
    ip: str,
    observed_at: datetime,
) -> None:
    result = await session.execute(
        select(IpAssignment)
        .where(
            IpAssignment.device_id == device.id,
            IpAssignment.observed_to.is_(None),
        )
        .order_by(IpAssignment.observed_from.desc())
    )
    open_row = result.scalars().first()
    if open_row is not None and open_row.ip == ip:
        return
    if open_row is not None:
        open_row.observed_to = observed_at
    session.add(
        IpAssignment(
            logic_version=LOGIC_VERSION,
            device_id=device.id,
            ip=ip,
            observed_from=observed_at,
            observed_to=None,
            source=IP_ASSIGNMENT_SOURCE,
        )
    )


async def upsert_device_from_client(
    session: AsyncSession,
    client: NormalizedClient,
) -> Device:
    """Resolve durable device by MAC (preferred) or UniFi client id — never by IP."""
    device = await _find_device_by_identifier(
        session, IdentifierKind.MAC, client.mac
    )
    if device is None and client.unifi_client_id:
        device = await _find_device_by_identifier(
            session,
            IdentifierKind.UNIFI_CLIENT_ID,
            client.unifi_client_id,
        )

    if device is None:
        device = Device(
            logic_version=LOGIC_VERSION,
            first_seen=client.first_seen,
            last_seen=client.last_seen,
            display_name=client.hostname,
            is_unknown=True,
        )
        session.add(device)
        await session.flush()
    else:
        if client.first_seen < device.first_seen:
            device.first_seen = client.first_seen
        if client.last_seen > device.last_seen:
            device.last_seen = client.last_seen
        if client.hostname:
            device.display_name = client.hostname
        device.logic_version = LOGIC_VERSION

    await _upsert_identifier(
        session,
        device,
        kind=IdentifierKind.MAC,
        value=client.mac,
        confidence=_CONFIDENCE_MAC,
        first_seen=client.first_seen,
        last_seen=client.last_seen,
    )
    if client.unifi_client_id:
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.UNIFI_CLIENT_ID,
            value=client.unifi_client_id,
            confidence=_CONFIDENCE_UNIFI_ID,
            first_seen=client.first_seen,
            last_seen=client.last_seen,
        )
    if client.hostname:
        await _upsert_identifier(
            session,
            device,
            kind=IdentifierKind.HOSTNAME,
            value=client.hostname,
            confidence=_CONFIDENCE_HOSTNAME,
            first_seen=client.first_seen,
            last_seen=client.last_seen,
        )
    if client.ip:
        await _update_ip_assignment(
            session,
            device,
            ip=client.ip,
            observed_at=client.last_seen,
        )
    await session.flush()
    return device


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
