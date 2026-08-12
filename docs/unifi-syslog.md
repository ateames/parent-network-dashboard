# UniFi syslog → Parent Network Dashboard

This stack **only receives** syslog from your UniFi Network Application / gateway. The syslog path never acknowledges events back to the controller and never opens a management session for logging — traffic is **one-directional**: UniFi → this Pi’s listener. (Separate from syslog: parent **Disable Internet** actions may call UniFi `block-sta` / `unblock-sta` over the session API.)

## What you get

The worker binds a syslog listener (UDP and/or TCP) and appends every received line to PostgreSQL (`raw_unifi_syslog`). Known UniFi security/event formats (CEF, classic firewall lines, `User[mac]` / `EVT_*` messages) are also parsed into the `parsed` JSONB column. Unknown lines are kept raw and counted — never dropped.

## Point UniFi at this Pi

1. Note this host’s **LAN IP** (the Raspberry Pi running Docker Compose) and the listener port (default **5514**).
2. In the UniFi Network Application UI, open **Settings → System → Advanced** (on UniFi OS / recent Network apps this may appear under **Control Plane → Integrations** or **System Logs / SIEM**).
3. Enable **remote logging / syslog / SIEM export**.
4. Set the **server / destination** to the Pi’s LAN IP and port **5514**.
5. Prefer **UDP** for classic syslog; enable **TCP** if your controller UI offers it and you set `UNIFI_SYSLOG_PROTOCOLS` accordingly. Do **not** enable any option that would require this dashboard to authenticate to UniFi for logging.
6. Save. Generate a known event (e.g. connect a Wi‑Fi client) and confirm the worker logs activity / `unifi_syslog` source health becomes **ok**.

Exact menu labels vary by UniFi Network / UniFi OS version. If you cannot find syslog export, search the controller help for “syslog”, “SIEM”, or “system logs”.

## Docker / env

| Variable | Default | Meaning |
|----------|---------|---------|
| `UNIFI_SYSLOG_ENABLED` | `true` | Bind the listener in the worker |
| `UNIFI_SYSLOG_HOST` | `0.0.0.0` | Bind address inside the container |
| `UNIFI_SYSLOG_PORT` | `5514` | UDP/TCP port (published on the host) |
| `UNIFI_SYSLOG_PROTOCOLS` | `udp,tcp` | `udp`, `tcp`, or both |
| `UNIFI_SYSLOG_STALE_SECONDS` | `300` | No lines in this window → `unifi_syslog` **degraded** |
| `UNIFI_SYSLOG_HEALTH_CHECK_SECONDS` | `60` | How often the worker re-checks staleness |

The Compose `worker` service publishes `${UNIFI_SYSLOG_PORT}:5514` for both UDP and TCP so the controller can reach the listener on the LAN.

Firewall note: allow inbound UDP/TCP **5514** (or your chosen port) **from the UniFi gateway/controller only** if you tighten host firewall rules.

## Offline replay (no live UniFi)

```bash
python -m app.ingest.unifi_syslog --replay fixtures/unifi_syslog_sample.log
```

Tests use the same fixture and parser path (`make test`).
