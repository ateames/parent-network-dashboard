# Parent Network Dashboard — frontend

Next.js (App Router) + TypeScript dashboard. Talks to the FastAPI backend **only**
through a server-side proxy so the admin token never reaches the browser.

## Stack

- Next.js App Router, React, TypeScript
- Tailwind CSS + shadcn/ui
- TanStack Query for data fetching

## API access (important)

| Caller | Allowed target |
|--------|----------------|
| Browser / React | `/api/proxy/*` only |
| Next.js route handler | Backend (`BACKEND_URL`) + `ADMIN_TOKEN` |

- Route handler: `src/app/api/proxy/[...path]/route.ts`
- Typed client: `src/lib/api/client.ts` (`apiFetch` always prefixes `/api/proxy`)
- **Never** put `ADMIN_TOKEN` or the backend URL in `NEXT_PUBLIC_*` vars
- **Never** call the backend origin from client components

Example:

```ts
import { apiFetch } from "@/lib/api/client";

const health = await apiFetch<{ status: string }>("/health");
// → browser GET /api/proxy/health
// → server forwards to ${BACKEND_URL}/health with Authorization: Bearer ${ADMIN_TOKEN}
```

## OpenAPI types

Frontend types come from the FastAPI OpenAPI schema (not hand-written):

```bash
# from repo root
make openapi
# → backend/openapi.json
# → frontend/src/generated/openapi.ts
```

Docker frontend builds regenerate these in-image. Locally, run `make openapi` after backend schema changes.

## Local authentication

The UI requires a local admin login (`/login`). Session cookies are signed with
`DASHBOARD_SESSION_SECRET`. The proxy still attaches `ADMIN_TOKEN` server-side
when calling the API — the browser never sees that token.

See [`docs/local-auth.md`](../docs/local-auth.md).

## Local development

```bash
cp ../infra/.env.example ../infra/.env   # if needed
# From frontend/:
export BACKEND_URL=http://localhost:8000
export ADMIN_TOKEN=changeme              # must match infra/.env
export DASHBOARD_USERNAME=admin
export DASHBOARD_PASSWORD=changeme
export DASHBOARD_SESSION_SECRET=dev-session-secret
npm install
make -C .. openapi   # or: npm run generate:api after exporting schema
npm run dev
```

Open http://localhost:3000/login — after signing in, Source Health / System Health
should load through `/api/proxy/*`.

## Docker (production)

The image is a **multi-stage** build: `next build` with `output: "standalone"`,
then a slim runtime that runs `node server.js` (not `next dev`).

```bash
# from repo root
make up
# frontend → http://localhost:3000
```

### Server-only env vars (Compose / runtime)

| Variable | Purpose |
|----------|---------|
| `BACKEND_URL` | Upstream FastAPI base URL (e.g. `http://api:8000`) |
| `ADMIN_TOKEN` | Bearer token injected by the proxy (same as API) |
| `DASHBOARD_USERNAME` | Local UI login username |
| `DASHBOARD_PASSWORD` | Local UI login password |
| `DASHBOARD_SESSION_SECRET` | HMAC secret for the httpOnly session cookie |

These are read only inside the Next.js server / middleware / route handlers.
