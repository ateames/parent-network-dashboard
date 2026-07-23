# Parent Network Dashboard

A locally hosted family network visibility platform that ingests **read-only** data from Pi-hole and UniFi and presents a parent-focused dashboard. Designed to run on a dedicated Raspberry Pi (arm64) via Docker Compose.

## Status

Backend API + worker (Pi-hole + UniFi API ingest + UniFi syslog listener), Next.js frontend (server-side API proxy), Docker Compose stack, and PostgreSQL schema (Alembic) are in place.

## Quick start

```bash
cp infra/.env.example infra/.env
make up          # db + api + worker + frontend (api runs alembic upgrade head on start)
curl localhost:8000/health
open http://localhost:3000/health   # green when proxy → API works
make migrate     # apply migrations manually (optional; also runs on api start)
make logs        # follow all service logs
make test        # backend pytest
make down        # stop containers (volume kept)
```

| Target | What it does |
|--------|----------------|
| `make up` | Build and start `db`, `api`, `worker`, and `frontend` |
| `make down` | Stop containers (named volume kept) |
| `make logs` | Follow logs for all services |
| `make migrate` | Run `alembic upgrade head` in a one-off api container |
| `make test` | Run backend pytest in a one-off api container (starts `db`) |

API listens on port **8000** (`GET /health`, `GET /version`). Dashboard listens on port **3000** (browser calls `/api/proxy/*` only).

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

Full non-negotiable conventions live in [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) (mirrored for Cursor agents at [`.cursor/rules/project.md`](.cursor/rules/project.md)).

## Tech stack (pinned)

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, PostgreSQL 16, httpx; worker via APScheduler or asyncio
- **Frontend:** Next.js App Router, React, TypeScript, Tailwind, shadcn/ui, TanStack Query, OpenAPI types, SSE
- **Orchestration:** Docker Compose, arm64-compatible slim images

## Next steps

1. Point `PIHOLE_*` / `UNIFI_*` env at your LAN hosts (or replay fixtures offline)
2. Build out dashboard pages (Overview, Live, People, Devices, Findings, Review)

Offline replay examples:

```bash
python -m app.ingest.pihole --replay fixtures/pihole_sample.json
python -m app.ingest.unifi --replay fixtures
python -m app.ingest.unifi_syslog --replay fixtures/unifi_syslog_sample.log
```

Point the UniFi controller’s syslog at this Pi (read-only, one-way): see [`docs/unifi-syslog.md`](docs/unifi-syslog.md).
