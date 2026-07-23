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

## Local development

```bash
cp ../infra/.env.example ../infra/.env   # if needed
# From frontend/:
export BACKEND_URL=http://localhost:8000
export ADMIN_TOKEN=changeme              # must match infra/.env
npm install
npm run dev
```

Open http://localhost:3000 — Health page should turn green when the API is up.

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

These are read only inside the Next.js server / route handlers.
