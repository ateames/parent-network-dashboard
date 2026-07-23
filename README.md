# Parent Network Dashboard

A locally hosted family network visibility platform that ingests **read-only** data from Pi-hole and UniFi and presents a parent-focused dashboard. Designed to run on a dedicated Raspberry Pi (arm64) via Docker Compose.

## Status

Monorepo skeleton only. Application frameworks are not scaffolded yet.

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

1. Scaffold the FastAPI backend (`api` + `worker` entrypoints) and PostgreSQL schema
2. Scaffold the Next.js frontend with server-side API proxy
3. Add Docker Compose under `infra/` and env templates
4. Drop fixture payloads into `fixtures/` and wire offline ingestion tests
