# Parent Network Dashboard — Project Conventions

These conventions are **NON-NEGOTIABLE**. All future work must follow them. Do not substitute the pinned tech stack or weaken the architecture, security, or testing principles below.

---

## TECH STACK (pinned — do not substitute)

### Backend

- Python 3.11
- FastAPI
- SQLAlchemy 2.x
- Alembic
- Pydantic v2
- PostgreSQL 16
- httpx
- APScheduler or a simple asyncio loop for the worker

### Backend processes

Two backend processes from the **same codebase**:

1. **`api`** — FastAPI / uvicorn
2. **`worker`** — ingestion + analysis loops

They share models and the database but run as **separate containers**.

### Frontend

- Next.js (App Router)
- React
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- OpenAPI-generated types
- Server-Sent Events (SSE) for live updates

### Orchestration

- Docker Compose
- All images must be **arm64-compatible** (runs on a Raspberry Pi)
- Prefer slim base images; be mindful of memory

---

## ARCHITECTURE PRINCIPLES

### Read-only ingestion

Ingestion is **READ-ONLY**. Nothing in this project writes to Pi-hole or UniFi.

### Local-only data

All household data stays on the LAN. No cloud analytics, no external calls except to the local Pi-hole and UniFi hosts.

### Versioned normalization and correlation

Normalization and correlation logic must be **VERSIONED**: every derived record stores the version of the logic that produced it (e.g. a `logic_version` column), so we can replay and compare.

### Preserve raw payloads

Preserve raw ingested payloads in **append-only raw tables** so we can replay and debug. Never discard source data on normalization.

### Confidence-aware correlation

Attribute activity to a device/person **ONLY** when confidence is sufficient. It is better to leave activity unattributed than to attribute it to the wrong child.

- Always store the evidence and a confidence score
- Keep conflicting evidence rather than overwriting it

### Honest language about DNS

The system must **never** imply that a DNS request proves a person viewed specific content. Language in findings must reflect uncertainty.

### Durable device identity

IP addresses change and get reassigned. Device identity must be durable (**MAC / UniFi client id / hostname**), never keyed on IP alone.

---

## SECURITY

- **No credentials or admin tokens in frontend/browser bundles.** The backend admin token is used only server-side. The Next.js app talks to the backend through a **server-side proxy route**.
- Pi-hole / UniFi / optional dashboard passwords may be entered once via the setup wizard or Settings UI; they are stored **encrypted in Postgres** (or still via env fallback) and must never be returned to the client after save.
- The dashboard is protected by **local authentication** (trusted home LAN).
- Keep an **audit trail** of decisions and configuration state.

---

## TESTING

- Every backend feature ships with **pytest** tests.
- Ingestion and correlation must be testable **offline** using fixtures in `/fixtures` (no live Pi-hole/UniFi required).
- Prefer **deterministic, transparent rules and statistical comparisons** over opaque ML for all MVP analysis.

---

## CODE STYLE

### Backend

- Type hints everywhere
- ruff + black formatting
- Small pure functions for logic that needs testing

### Frontend

- Typed components
- No `any`
- Data fetching via TanStack Query hooks only
