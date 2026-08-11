# Local dashboard authentication

The dashboard UI is gated by a **local admin login**. This is separate from the
backend `ADMIN_TOKEN`, which must never reach the browser.

This stack is intended for a **trusted home LAN**. Credentials may briefly appear
in browser form fields during first-run setup; they are stored encrypted in
Postgres afterward and are never shipped in client JS bundles.

## How it works

| Layer | Mechanism |
|-------|-----------|
| Browser | Signs in at `/login`; receives an httpOnly `pnd_session` cookie |
| Next.js middleware | Redirects unauthenticated page requests to `/login` (`/setup` is public) |
| `/api/proxy/*` | Requires a valid session (setup connection routes are open until setup completes), then forwards to FastAPI with `Authorization: Bearer ${ADMIN_TOKEN}` |
| FastAPI | Receives the admin token from the proxy only (server-side) |

Login verifies against:

1. Optional dashboard username/password saved via the setup wizard / Settings (encrypted in Postgres), or
2. `ADMIN_USERNAME` / `ADMIN_PASSWORD` (typically mirrored by `DASHBOARD_*` at install time), with a final env fallback in the Next.js login route using `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`.

The session cookie is HMAC-signed with `DASHBOARD_SESSION_SECRET`.

## Setup

### Recommended (Pi)

```bash
./scripts/install.sh
open http://<pi-lan-ip>:3000/setup
```

`install.sh` generates `ADMIN_TOKEN`, `DASHBOARD_SESSION_SECRET`,
`CONNECTIONS_SECRET`, and an initial dashboard password (printed once).

### Manual

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
   DASHBOARD_COOKIE_SECURE=false
   CONNECTIONS_SECRET=choose-a-long-random-string
   ```

   For MVP it is fine if `DASHBOARD_*` matches `ADMIN_USERNAME` /
   `ADMIN_PASSWORD`. `ADMIN_TOKEN` should still be a distinct secret used only
   between the frontend proxy and the API.

3. Start the stack:

   ```bash
   make up
   open http://localhost:3000/setup
   ```

## Local frontend without Docker

```bash
export BACKEND_URL=http://localhost:8000
export ADMIN_TOKEN=changeme
export DASHBOARD_USERNAME=admin
export DASHBOARD_PASSWORD=changeme
export DASHBOARD_SESSION_SECRET=dev-session-secret
export DASHBOARD_COOKIE_SECURE=false
npm run dev
```

## Session cookie (LAN HTTP)

`DASHBOARD_COOKIE_SECURE` defaults to `false` so the httpOnly session cookie works
on plain `http://<pi-ip>:3000`. Set it to `true` only when the UI is served over
HTTPS.

## Security notes

- Never prefix dashboard credentials or `ADMIN_TOKEN` with `NEXT_PUBLIC_`.
- Browser code may only call `/api/proxy/*` and `/api/auth/*`.
- Pi-hole / UniFi secrets are entered in the setup wizard or Settings → Connections,
  stored Fernet-encrypted with `CONNECTIONS_SECRET`, and never returned by the API.
- Signing out clears the session cookie via `POST /api/auth/logout`.
- This is a single-admin MVP gate for a LAN-hosted dashboard, not multi-user IAM.
