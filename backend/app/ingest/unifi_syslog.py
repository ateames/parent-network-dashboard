"""Read-only UniFi syslog ingestion (UDP/TCP listener + offline fixture replay).

The controller pushes syslog one-way to this host. We never write back to UniFi.
Every raw line is appended to ``raw_unifi_syslog``; known formats fill ``parsed``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.db import AsyncSessionLocal, engine
from app.health.source_health import (
    get_source_health,
    record_attempt,
    record_failure,
    record_success,
)
from app.ingest.unifi import normalize_mac
from app.models.enums import IngestBatchStatus, IngestSource
from app.models.raw import IngestBatch, RawUnifiSyslog

logger = logging.getLogger(__name__)

LOGIC_VERSION = "unifi_syslog.v1"

# Optional syslog PRI + classic header before the message body.
_SYSLOG_PREFIX_RE = re.compile(
    r"""
    ^
    (?:<(?P<pri>\d{1,3})>)?
    (?:
        (?P<header>
            (?:[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})   # RFC3164 timestamp
            \s+
            \S+                                               # hostname
            \s+
        )
    )?
    (?P<body>.*)
    $
    """,
    re.VERBOSE | re.DOTALL,
)

_CEF_RE = re.compile(
    r"CEF:(?P<version>\d+)\|(?P<header>[^|]+(?:\|[^|]+){5})\|(?P<extensions>.*)$",
    re.DOTALL,
)

# key=value pairs; values may be quoted or unquoted until next key=.
_CEF_EXT_RE = re.compile(
    r"(?P<key>[A-Za-z0-9._]+)=(?P<value>(?:\\.|[^=])*?)(?=\s+[A-Za-z0-9._]+=|$)",
    re.DOTALL,
)

# Classic UniFi / USG firewall-style security lines (rule token in brackets).
_FIREWALL_RULE_RE = re.compile(r"\[(?P<rule>[A-Za-z0-9_-]+)\]")
_FIREWALL_DESCR_RE = re.compile(r'DESCR="(?P<descr>[^"]*)"', re.IGNORECASE)
_FIREWALL_SRC_RE = re.compile(r"\bSRC=(?P<src>\S+)", re.IGNORECASE)
_FIREWALL_DST_RE = re.compile(r"\bDST=(?P<dst>\S+)", re.IGNORECASE)
_FIREWALL_PROTO_RE = re.compile(r"\bPROTO=(?P<proto>\S+)", re.IGNORECASE)

# Event-style bodies: User[mac] ... SSID[name] / AP[mac]
_EVENT_USER_RE = re.compile(
    r"User\[(?P<mac>[0-9A-Fa-f:.-]{11,17})\]",
    re.IGNORECASE,
)
_EVENT_SSID_RE = re.compile(
    r"(?:SSID|essid)\[(?P<ssid>[^\]]+)\]",
    re.IGNORECASE,
)
_EVENT_AP_RE = re.compile(
    r"\bAP\[(?P<ap>[0-9A-Fa-f:.-]{11,17})\]",
    re.IGNORECASE,
)
_EVENT_KEY_RE = re.compile(r"\b(EVT_[A-Za-z0-9_]+)\b")

_MAC_FIELD_KEYS = frozenset(
    {
        "unificlientmac",
        "mac",
        "srcmac",
        "dstmac",
        "unifilastconnectedtodevicemac",
    }
)


@dataclass(frozen=True, slots=True)
class ParsedSyslogResult:
    """Outcome of attempting to structure one syslog line."""

    raw_line: str
    parsed: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class SyslogIngestResult:
    """Persist outcome for one or more lines."""

    batch: IngestBatch
    line_count: int
    parsed_count: int
    unparsed_count: int


def syslog_health_settings(cfg: Settings | None = None) -> Settings:
    """Settings copy using the syslog-specific stale window for health checks."""
    base = cfg or settings
    return base.model_copy(
        update={"source_health_stale_seconds": base.unifi_syslog_stale_seconds}
    )


def strip_syslog_envelope(line: str) -> tuple[str, dict[str, Any]]:
    """Remove optional PRI / RFC3164 header; return body + envelope metadata."""
    text = line.rstrip("\r\n")
    match = _SYSLOG_PREFIX_RE.match(text)
    if match is None:
        return text, {}
    meta: dict[str, Any] = {}
    pri = match.group("pri")
    if pri is not None:
        meta["pri"] = int(pri)
    header = match.group("header")
    if header:
        meta["syslog_header"] = header.strip()
    body = (match.group("body") or "").strip()
    return body or text, meta


def _unescape_cef(value: str) -> str:
    return (
        value.replace("\\\\", "\\")
        .replace("\\|", "|")
        .replace("\\=", "=")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
    )


def _parse_cef_extensions(extensions: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in _CEF_EXT_RE.finditer(extensions.strip()):
        key = match.group("key")
        value = _unescape_cef(match.group("value").strip())
        out[key] = value
    return out


def _optional_mac(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return normalize_mac(value)
    except ValueError:
        return value.strip().lower() or None


def _mac_from_extensions(ext: dict[str, str]) -> str | None:
    for key, value in ext.items():
        if key.lower().replace("_", "") in _MAC_FIELD_KEYS or key.lower().endswith(
            "mac"
        ):
            mac = _optional_mac(value)
            if mac:
                return mac
    return None


def parse_cef(
    body: str,
    *,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Parse a UniFi CEF (Common Event Format) message body."""
    match = _CEF_RE.search(body)
    if match is None:
        return None
    header_parts = match.group("header").split("|")
    if len(header_parts) != 6:
        return None
    vendor, product, device_version, event_class, name, severity_raw = header_parts
    if "ubiquiti" not in vendor.lower() and "unifi" not in product.lower():
        # Still accept if CEF structure matched — UniFi sometimes varies vendor text.
        pass
    try:
        severity = int(severity_raw)
    except ValueError:
        severity = severity_raw
    extensions = _parse_cef_extensions(match.group("extensions"))
    category = extensions.get("UNIFIcategory") or extensions.get("category")
    sub_category = extensions.get("UNIFIsubCategory") or extensions.get("subCategory")
    msg = extensions.get("msg")
    client_ip = (
        extensions.get("UNIFIclientIp")
        or extensions.get("src")
        or extensions.get("dst")
    )
    ssid = (
        extensions.get("UNIFIwifiName")
        or extensions.get("UNIFIssid")
        or extensions.get("ssid")
    )
    hostname = extensions.get("UNIFIclientHostname") or extensions.get(
        "UNIFIclientName"
    )
    parsed: dict[str, Any] = {
        "logic_version": LOGIC_VERSION,
        "format": "cef",
        "cef_version": match.group("version"),
        "vendor": vendor,
        "product": product,
        "device_version": device_version,
        "event_class_id": event_class,
        "event_name": name,
        "severity": severity,
        "category": category,
        "sub_category": sub_category,
        "mac": _mac_from_extensions(extensions),
        "client_ip": client_ip,
        "ssid": ssid,
        "hostname": hostname,
        "msg": msg,
        "extensions": extensions,
    }
    if envelope:
        parsed["envelope"] = envelope
    return parsed


def parse_firewall(
    body: str,
    *,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Parse classic UniFi/USG iptables-style security lines."""
    rule_match = _FIREWALL_RULE_RE.search(body)
    if rule_match is None:
        return None
    upper = body.upper()
    # Require a recognizable security/firewall token so we don't over-match.
    if not any(
        token in upper
        for token in ("SRC=", "DST=", "LAN_LOCAL", "WAN_LOCAL", "WAN_IN", "LAN_IN")
    ):
        return None
    descr_m = _FIREWALL_DESCR_RE.search(body)
    src_m = _FIREWALL_SRC_RE.search(body)
    dst_m = _FIREWALL_DST_RE.search(body)
    proto_m = _FIREWALL_PROTO_RE.search(body)
    parsed: dict[str, Any] = {
        "logic_version": LOGIC_VERSION,
        "format": "firewall",
        "event_name": rule_match.group("rule"),
        "category": "Security",
        "sub_category": "Firewall",
        "msg": (descr_m.group("descr") if descr_m else body).strip(),
        "client_ip": src_m.group("src") if src_m else None,
        "dst_ip": dst_m.group("dst") if dst_m else None,
        "proto": proto_m.group("proto") if proto_m else None,
        "mac": None,
        "ssid": None,
        "hostname": None,
    }
    if envelope:
        parsed["envelope"] = envelope
    return parsed


def parse_event(
    body: str,
    *,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Parse User[mac] / EVT_* style UniFi event lines."""
    user = _EVENT_USER_RE.search(body)
    evt = _EVENT_KEY_RE.search(body)
    if user is None and evt is None:
        return None
    ssid_m = _EVENT_SSID_RE.search(body)
    ap_m = _EVENT_AP_RE.search(body)
    event_name = evt.group(1) if evt else "unifi_event"
    lower = body.lower()
    if "disconnect" in lower:
        category = "Monitoring"
        sub = "WiFi" if "wifi" in lower or "ssid" in lower or ssid_m else "Wired"
    elif "connect" in lower or "associat" in lower:
        category = "Monitoring"
        sub = "WiFi" if ssid_m or "ssid" in lower else "Wired"
    elif "blocked" in lower or "threat" in lower or "firewall" in lower:
        category = "Security"
        sub = "Threat"
    else:
        category = "System"
        sub = "Event"
    parsed: dict[str, Any] = {
        "logic_version": LOGIC_VERSION,
        "format": "event",
        "event_name": event_name,
        "category": category,
        "sub_category": sub,
        "mac": _optional_mac(user.group("mac") if user else None),
        "ssid": ssid_m.group("ssid").strip() if ssid_m else None,
        "ap_mac": _optional_mac(ap_m.group("ap") if ap_m else None),
        "client_ip": None,
        "hostname": None,
        "msg": body.strip(),
    }
    if envelope:
        parsed["envelope"] = envelope
    return parsed


def parse_syslog_line(line: str) -> ParsedSyslogResult:
    """Pure parser — returns structured fields or ``parsed=None`` (never drops)."""
    raw = line.rstrip("\r\n")
    if not raw.strip():
        return ParsedSyslogResult(raw_line=raw, parsed=None)
    body, envelope = strip_syslog_envelope(raw)
    for parser in (parse_cef, parse_firewall, parse_event):
        parsed = parser(body, envelope=envelope or None)
        if parsed is not None:
            return ParsedSyslogResult(raw_line=raw, parsed=parsed)
    return ParsedSyslogResult(raw_line=raw, parsed=None)


def load_fixture_lines(path: Path) -> list[str]:
    """Load non-empty, non-comment lines from a syslog fixture file."""
    text = path.read_text(encoding="utf-8")
    lines: list[str] = []
    for ln in text.splitlines():
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(ln.rstrip("\r\n"))
    return lines


async def persist_lines(
    session: AsyncSession,
    lines: Sequence[str],
    *,
    cfg: Settings | None = None,
    now: datetime | None = None,
) -> SyslogIngestResult:
    """Append raw lines (+ optional parsed JSON) and mark unifi_syslog healthy."""
    cfg = cfg or settings
    health_cfg = syslog_health_settings(cfg)
    now = now or datetime.now(UTC)
    source = IngestSource.UNIFI_SYSLOG

    await record_attempt(session, source, now=now, cfg=health_cfg)

    batch = IngestBatch(
        source=source,
        started_at=now,
        status=IngestBatchStatus.RUNNING,
        record_count=0,
    )
    session.add(batch)
    await session.flush()

    parsed_count = 0
    unparsed_count = 0
    stored = 0
    try:
        for line in lines:
            if not line.strip():
                continue
            result = parse_syslog_line(line)
            if result.parsed is None:
                unparsed_count += 1
            else:
                parsed_count += 1
            session.add(
                RawUnifiSyslog(
                    raw_line=result.raw_line,
                    parsed=result.parsed,
                    ingest_batch_id=batch.id,
                )
            )
            stored += 1

        finished = datetime.now(UTC)
        batch.record_count = stored
        batch.status = IngestBatchStatus.SUCCEEDED
        batch.finished_at = finished
        batch.error = None
        detail = (
            f"Ingested {stored} syslog line(s) "
            f"({parsed_count} parsed, {unparsed_count} unparsed)"
        )
        await record_success(
            session,
            source,
            detail=detail,
            now=finished,
            cfg=health_cfg,
        )
        await session.flush()
        return SyslogIngestResult(
            batch=batch,
            line_count=stored,
            parsed_count=parsed_count,
            unparsed_count=unparsed_count,
        )
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
            cfg=health_cfg,
        )
        await session.flush()
        raise


async def ingest_lines(
    session: AsyncSession,
    lines: Sequence[str],
    *,
    cfg: Settings | None = None,
    commit: bool = True,
) -> SyslogIngestResult:
    result = await persist_lines(session, lines, cfg=cfg)
    if commit:
        await session.commit()
    return result


async def ingest_line(
    line: str,
    *,
    cfg: Settings | None = None,
    session: AsyncSession | None = None,
) -> SyslogIngestResult:
    """Persist a single received syslog line immediately."""
    if session is not None:
        return await ingest_lines(session, [line], cfg=cfg, commit=True)

    async with AsyncSessionLocal() as owned:
        try:
            return await ingest_lines(owned, [line], cfg=cfg, commit=True)
        except Exception:
            await owned.rollback()
            raise


async def replay_fixture(
    path: Path,
    *,
    cfg: Settings | None = None,
    session: AsyncSession | None = None,
) -> SyslogIngestResult:
    """Feed fixture lines through the same parser/persist path (no live socket)."""
    if not path.is_file():
        raise FileNotFoundError(f"Syslog fixture not found: {path}")
    lines = load_fixture_lines(path)
    if session is not None:
        return await ingest_lines(session, lines, cfg=cfg, commit=True)

    async with AsyncSessionLocal() as owned:
        try:
            return await ingest_lines(owned, lines, cfg=cfg, commit=True)
        except Exception:
            await owned.rollback()
            raise


async def refresh_syslog_health(*, cfg: Settings | None = None) -> None:
    """Re-evaluate unifi_syslog status (degraded when no lines in the window)."""
    health_cfg = syslog_health_settings(cfg)
    async with AsyncSessionLocal() as session:
        await get_source_health(
            session,
            IngestSource.UNIFI_SYSLOG,
            cfg=health_cfg,
            refresh=True,
        )
        await session.commit()


def _parse_protocols(value: str) -> set[str]:
    parts = {p.strip().lower() for p in value.split(",") if p.strip()}
    unknown = parts - {"udp", "tcp"}
    if unknown:
        raise ValueError(f"Unknown UNIFI_SYSLOG_PROTOCOLS: {sorted(unknown)}")
    if not parts:
        raise ValueError("UNIFI_SYSLOG_PROTOCOLS must include udp and/or tcp")
    return parts


class _SyslogUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[str]) -> None:
        self._queue = queue

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        text = data.decode("utf-8", errors="replace")
        for piece in text.splitlines():
            line = piece.strip()
            if line:
                self._queue.put_nowait(line)

    def error_received(self, exc: Exception) -> None:
        logger.warning("syslog UDP error: %s", exc)


async def _handle_tcp_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    queue: asyncio.Queue[str],
) -> None:
    peer = writer.get_extra_info("peername")
    try:
        while not reader.at_eof():
            raw = await reader.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                await queue.put(line)
    except Exception:
        logger.exception("syslog TCP client error peer=%s", peer)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _line_consumer(
    queue: asyncio.Queue[str],
    *,
    cfg: Settings,
    on_error: Callable[[BaseException], Awaitable[None]] | None = None,
) -> None:
    while True:
        line = await queue.get()
        try:
            result = await ingest_line(line, cfg=cfg)
            logger.debug(
                "syslog stored batch=%s parsed=%s unparsed=%s",
                result.batch.id,
                result.parsed_count,
                result.unparsed_count,
            )
        except Exception as exc:
            logger.exception("syslog ingest failed")
            if on_error is not None:
                await on_error(exc)
        finally:
            queue.task_done()


async def run_syslog_listener(
    *,
    cfg: Settings | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Bind UDP and/or TCP syslog listeners and persist lines as they arrive."""
    cfg = cfg or settings
    if not cfg.unifi_syslog_enabled:
        logger.info("unifi syslog listener disabled")
        return

    protocols = _parse_protocols(cfg.unifi_syslog_protocols)
    host = cfg.unifi_syslog_host
    port = cfg.unifi_syslog_port
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=10_000)
    stop = stop_event or asyncio.Event()

    consumer = asyncio.create_task(
        _line_consumer(queue, cfg=cfg),
        name="syslog-consumer",
    )
    servers: list[Any] = []
    transport: asyncio.DatagramTransport | None = None

    loop = asyncio.get_running_loop()
    try:
        if "udp" in protocols:
            transport, _protocol = await loop.create_datagram_endpoint(
                lambda: _SyslogUDPProtocol(queue),
                local_addr=(host, port),
            )
            logger.info("unifi syslog UDP listening on %s:%s", host, port)

        if "tcp" in protocols:
            server = await asyncio.start_server(
                lambda r, w: _handle_tcp_client(r, w, queue),
                host=host,
                port=port,
            )
            servers.append(server)
            logger.info("unifi syslog TCP listening on %s:%s", host, port)

        await stop.wait()
    finally:
        if transport is not None:
            transport.close()
        for server in servers:
            server.close()
            await server.wait_closed()
        consumer.cancel()
        try:
            await consumer
        except asyncio.CancelledError:
            pass


async def syslog_health_loop(*, cfg: Settings | None = None) -> None:
    """Periodically refresh unifi_syslog health so silence becomes degraded."""
    cfg = cfg or settings
    interval = max(5, cfg.unifi_syslog_health_check_seconds)
    logger.info(
        "unifi syslog health check interval=%ss stale_after=%ss",
        interval,
        cfg.unifi_syslog_stale_seconds,
    )
    while True:
        try:
            await refresh_syslog_health(cfg=cfg)
        except Exception:
            logger.exception("unifi syslog health refresh failed")
        await asyncio.sleep(interval)


def resolve_fixture_path(path: Path) -> Path:
    if path.is_dir():
        candidate = path / "unifi_syslog_sample.log"
    else:
        candidate = path
    if not candidate.is_file():
        raise FileNotFoundError(f"Syslog fixture not found: {candidate}")
    return candidate


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UniFi syslog ingest (listener or fixture replay)",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        metavar="PATH",
        help=(
            "Ingest from a fixture file instead of binding sockets. "
            "Pass fixtures/unifi_syslog_sample.log or a directory containing it."
        ),
    )
    return parser


async def _async_main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [unifi-syslog] %(message)s",
    )
    try:
        if args.replay is not None:
            try:
                fixture = resolve_fixture_path(args.replay)
                result = await replay_fixture(fixture)
            except FileNotFoundError as exc:
                logger.error("%s", exc)
                return 1
            logger.info(
                "replay ok batch_id=%s lines=%s parsed=%s unparsed=%s status=%s",
                result.batch.id,
                result.line_count,
                result.parsed_count,
                result.unparsed_count,
                result.batch.status.value,
            )
            return 0

        stop = asyncio.Event()
        await run_syslog_listener(stop_event=stop)
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_async_main(argv)))


if __name__ == "__main__":
    main()
