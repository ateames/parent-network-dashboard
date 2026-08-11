# Parent Network Dashboard

A LAN-only family network visibility platform that ingests **read-only** data from Pi-hole and UniFi and presents a parent-focused dashboard. Designed to run on a dedicated **Raspberry Pi (arm64)** via Docker Compose.

Household data stays on your local network. Nothing in this project writes to Pi-hole or UniFi.

## What runs on the Pi

| Service | Role | Host ports (defaults) |
|---------|------|------------------------|
| `frontend` | Next.js dashboard (local login + server-side API proxy) | **3000** |
| `api` | FastAPI (migrations on start, health/version endpoints) | **8000** |
| `worker` | Pi-hole / UniFi API polling + UniFi syslog listener | **5514** UDP/TCP |
| `db` | PostgreSQL 16 (named volume `parent-network-pgdata`) | **5432** (optional; local tooling) |

Use the dashboard on port **3000**. Prefer not exposing `8000` / `5432` beyond the Pi itself once the stack is healthy.

## Hardware & OS

- **Raspberry Pi 4 or 5** (64-bit / arm64), ideally **4 GB+ RAM**
- **microSD** (or USB SSD) with enough free space for images + Postgres data (16 GB+ recommended)
- **Raspberry Pi OS (64-bit)** or another arm64 Linux with Docker
- Static or DHCP-reserved **LAN IP** for the Pi (needed for UniFi syslog and browser access)

Confirm architecture before installing:

```bash
uname -m   # expect aarch64
```

## Install Docker on the Pi

1. Update packages and install prerequisites:

   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y git curl ca-certificates
   ```

2. Install Docker Engine + Compose plugin (official convenience script, or follow [Docker’s Debian/Raspberry Pi OS docs](https://docs.docker.com/engine/install/)):

   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker "$USER"
   ```

3. Log out and back in (or reboot) so the `docker` group applies, then verify:

   ```bash
   docker --version
   docker compose version
   ```

4. Optional but recommended — start Docker on boot and reduce SD-card wear later with a USB SSD for `/var/lib/docker` if you run the stack long-term.

## Install (recommended)

On the Pi, after Docker is available (see above):

```bash
git clone https://github.com/ateames/parent-network-dashboard.git parent-network-dashboard
cd parent-network-dashboard
./scripts/install.sh
```

The script generates secrets in `infra/.env`, builds the stack, and prints:

- Setup wizard URL: `http://<pi-lan-ip>:3000/setup`
- Initial dashboard username/password (shown once)

Open the wizard on another device on your LAN. It walks through Pi-hole and UniFi credentials (stored encrypted in Postgres) and UniFi syslog instructions. You do **not** need to hand-edit Pi-hole/UniFi passwords in `.env` for a normal install.

First build on a Pi can take several minutes (arm64 image builds from source).

### Advanced / manual configure

If you prefer not to use `install.sh`:

```bash
cp infra/.env.example infra/.env
nano infra/.env   # set secrets; leave Pi-hole/UniFi blank for the wizard
make up
```

Required infrastructure secrets in `infra/.env`:

```env
POSTGRES_PASSWORD=<strong-db-password>
DATABASE_URL=postgresql+asyncpg://parent:<strong-db-password>@db:5432/parent_network
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong-password>
ADMIN_TOKEN=<long-random-token>
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=<strong-password>
DASHBOARD_SESSION_SECRET=<long-random-string>
DASHBOARD_COOKIE_SECURE=false
CONNECTIONS_SECRET=<long-random-string>
```

Generate random values:

```bash
openssl rand -hex 32
```

Details: [`docs/local-auth.md`](docs/local-auth.md).

Optional env fallbacks for ingest (wizard/DB overrides these when set):

```env
PIHOLE_URL=http://<pihole-lan-ip>
PIHOLE_AUTH_METHOD=password
PIHOLE_PASSWORD=
UNIFI_URL=https://<unifi-lan-ip>
UNIFI_AUTH_METHOD=session
UNIFI_USERNAME=
UNIFI_PASSWORD=
UNIFI_SITE=default
UNIFI_VERIFY_TLS=false
```

Use LAN IPs if `.local` mDNS is unreliable from Docker. The worker only **reads** these APIs.

### UniFi syslog (controller → Pi)

Keep the listener enabled so UniFi can push security/event logs one-way to this host:

```env
UNIFI_SYSLOG_ENABLED=true
UNIFI_SYSLOG_HOST=0.0.0.0
UNIFI_SYSLOG_PORT=5514
UNIFI_SYSLOG_PROTOCOLS=udp,tcp
```

In the UniFi UI, set remote syslog / SIEM destination to **this Pi’s LAN IP** and port **5514**. The setup wizard also covers this. Step-by-step: [`docs/unifi-syslog.md`](docs/unifi-syslog.md).

### Published ports

| Variable | Default | Purpose |
|----------|---------|---------|
| `FRONTEND_PORT` | `3000` | Dashboard (browse from other devices) |
| `API_PORT` | `8000` | FastAPI (health checks / optional direct access) |
| `UNIFI_SYSLOG_PORT` | `5514` | Syslog from UniFi gateway/controller |
| `POSTGRES_PORT` | `5432` | Postgres on the host (optional) |

`BACKEND_URL=http://api:8000` is correct inside Compose — do not change it for normal Pi deploys.

## Start / update the stack

```bash
make up          # requires infra/.env; builds + starts db, api, worker, frontend
make logs        # follow all services
```

Migrations run automatically when the `api` container starts (`alembic upgrade head`). Manual run:

```bash
make migrate
```

| Target | What it does |
|--------|----------------|
| `make up` | Build and start `db`, `api`, `worker`, and `frontend` |
| `make down` | Stop containers (named volume kept) |
| `make logs` | Follow logs for all services |
| `make migrate` | Run `alembic upgrade head` in a one-off api container |
| `make test` | Run backend pytest in a one-off api container (starts `db`) |
| `make openapi` | Export OpenAPI schema and regenerate frontend TypeScript types |

## Access on the LAN

1. Find the Pi’s IPv4 address:

   ```bash
   hostname -I
   # example: 192.168.1.50
   ```

2. First boot — open the setup wizard from a phone/laptop on the **same LAN**:

   ```
   http://<pi-lan-ip>:3000/setup
   ```

3. After setup, sign in at:

   ```
   http://<pi-lan-ip>:3000/login
   ```

   Use the password printed by `install.sh`, or the family password you set in the wizard.

4. Optional checks from the Pi itself:

   ```bash
   curl -s http://localhost:8000/health
   curl -s http://localhost:8000/version
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8000/api/sources/health
   ```

Browser traffic should go through the dashboard only (`/api/proxy/*` and `/api/auth/*`). The admin API token stays on the Next.js server.

### Firewall (if enabled)

Allow LAN access to the dashboard and syslog. Example with `ufw` (adjust interface/subnet as needed):

```bash
sudo ufw allow from 192.168.1.0/24 to any port 3000 proto tcp comment 'PND dashboard'
sudo ufw allow from <unifi-controller-or-gateway-ip> to any port 5514 comment 'UniFi syslog'
# Prefer not publishing 8000/5432 to the whole LAN in production
sudo ufw enable
sudo ufw status
```

Give the Pi a **DHCP reservation** (or static IP) in your router so UniFi syslog and bookmarks keep working after reboot.

## Verify ingest

After login, check Source Health / System Health in the UI, or hit the API health endpoints above.

- **Pi-hole / UniFi API:** `ok` after successful polls (interval defaults to 60s).
- **UniFi syslog:** becomes healthy once the controller sends lines to port **5514**; generate a known event (e.g. a Wi‑Fi client connect) if needed.

Offline replay (dev / no live gear):

```bash
python -m app.ingest.pihole --replay fixtures/pihole_sample.json
python -m app.ingest.unifi --replay fixtures
python -m app.ingest.unifi_syslog --replay fixtures/unifi_syslog_sample.log
```

## Day-2 operations

```bash
cd ~/parent-network-dashboard   # or your clone path
git pull
make up                         # rebuild + recreate changed services
make logs
make down                       # stop; Postgres data kept in volume parent-network-pgdata
```

Reboot safety: Compose services use `restart: unless-stopped`, so the stack comes back after a Pi reboot as long as Docker is enabled.

## Repository layout

| Path | Purpose |
|------|---------|
| `backend/` | Python 3.11 / FastAPI API + worker (shared codebase, separate processes) |
| `frontend/` | Next.js (App Router), TypeScript, Tailwind, shadcn/ui |
| `infra/` | Docker Compose and environment templates |
| `fixtures/` | Sample Pi-hole / UniFi payloads for offline testing |
| `docs/` | Project documentation and conventions |

## Principles (summary)

- **Read-only ingestion** — never write to Pi-hole or UniFi
- **LAN-only** — household data stays on the local network
- **Versioned logic** — derived records store a `logic_version` for replay/compare
- **Raw payloads preserved** — append-only raw tables; never discard source data
- **Confidence-aware attribution** — better unattributed than wrong; keep conflicting evidence
- **Honest language** — DNS ≠ proof of content viewed
- **Durable device identity** — MAC / UniFi client id / hostname, not IP alone

Full conventions: [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) (also [`.cursor/rules/project.md`](.cursor/rules/project.md)).

## Tech stack (pinned)

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, PostgreSQL 16, httpx; worker via APScheduler or asyncio
- **Frontend:** Next.js App Router, React, TypeScript, Tailwind, shadcn/ui, TanStack Query, OpenAPI types, SSE
- **Orchestration:** Docker Compose, arm64-compatible slim images

## Related docs

| Doc | Topic |
|-----|--------|
| [`docs/local-auth.md`](docs/local-auth.md) | Dashboard login vs `ADMIN_TOKEN` |
| [`docs/unifi-syslog.md`](docs/unifi-syslog.md) | Point UniFi syslog at this Pi |
| [`frontend/README.md`](frontend/README.md) | Frontend proxy rules and local UI dev |
| [`backend/README.md`](backend/README.md) | Backend package / migrations |
