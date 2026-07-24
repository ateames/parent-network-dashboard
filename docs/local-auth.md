# Local dashboard authentication

The dashboard UI is gated by a **local admin login**. This is separate from the
backend `ADMIN_TOKEN`, which must never reach the browser.

## How it works

| Layer | Mechanism |
|-------|-----------|
| Browser | Signs in at `/login`; receives an httpOnly `pnd_session` cookie |
| Next.js middleware | Redirects unauthenticated page requests to `/login` |
| `/api/proxy/*` | Requires a valid session, then forwards to FastAPI with `Authorization: Bearer ${ADMIN_TOKEN}` |
| FastAPI | Receives the admin token from the proxy only (server-side) |

The login form checks `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` on the Next.js
server. The session cookie is HMAC-signed with `DASHBOARD_SESSION_SECRET`.

## Setup

1. Copy env defaults:

   ```bash
   cp infra/.env.example infra/.env
   ```

2. Set strong values in `infra/.env`:

   ```env
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=choose-a-strong-password
   ADMIN_TOKEN=choose-a-long-random-token

   DASHBOARD_USERNAME=admin
   DASHBOARD_PASSWORD=choose-a-strong-password
   DASHBOARD_SESSION_SECRET=choose-a-long-random-string
   ```

   For MVP it is fine if `DASHBOARD_*` matches `ADMIN_USERNAME` /
   `ADMIN_PASSWORD`. `ADMIN_TOKEN` should still be a distinct secret used only
   between the frontend proxy and the API.

3. Start the stack:

   ```bash
   make up
   open http://localhost:3000/login
   ```

## Local frontend without Docker

```bash
export BACKEND_URL=http://localhost:8000
export ADMIN_TOKEN=changeme
export DASHBOARD_USERNAME=admin
export DASHBOARD_PASSWORD=changeme
export DASHBOARD_SESSION_SECRET=dev-session-secret
npm run dev
```

## Security notes

- Never prefix dashboard credentials or `ADMIN_TOKEN` with `NEXT_PUBLIC_`.
- Browser code may only call `/api/proxy/*` and `/api/auth/*`.
- Signing out clears the session cookie via `POST /api/auth/logout`.
- This is a single-admin MVP gate for a LAN-hosted dashboard, not multi-user IAM.
