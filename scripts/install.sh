#!/usr/bin/env bash
# Parent Network Dashboard — Raspberry Pi bootstrap
#
# Usage (from repo root, or after clone):
#   ./scripts/install.sh
#
# What it does:
#   1. Checks arm64 + Docker
#   2. Creates infra/.env with generated secrets (if missing)
#   3. Builds and starts the Compose stack
#   4. Prints the LAN setup URL and initial dashboard password

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/infra/.env"
ENV_EXAMPLE="${ROOT}/infra/.env.example"
COMPOSE=(docker compose -f "${ROOT}/infra/docker-compose.yml" --env-file "${ENV_FILE}")

log() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

rand_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

lan_ip() {
  # Prefer the default-route interface address.
  if command -v ip >/dev/null 2>&1; then
    ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}' || true
  fi
  if command -v hostname >/dev/null 2>&1; then
    hostname -I 2>/dev/null | awk '{print $1}' || true
  fi
}

set_env_kv() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    # macOS/BSD and GNU sed differ; use a portable temp rewrite.
    local tmp
    tmp="$(mktemp)"
    awk -v k="${key}" -v v="${value}" '
      BEGIN { done=0 }
      index($0, k "=") == 1 && !done { print k "=" v; done=1; next }
      { print }
      END { if (!done) print k "=" v }
    ' "${ENV_FILE}" > "${tmp}"
    mv "${tmp}" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

arch="$(uname -m)"
case "${arch}" in
  aarch64|arm64) ;;
  *)
    log "warning: expected aarch64/arm64 for Raspberry Pi; found ${arch}"
    ;;
esac

need_cmd git
need_cmd curl

if ! command -v docker >/dev/null 2>&1; then
  log "Docker not found — installing via get.docker.com (requires sudo)…"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "${USER}" || true
  log "Docker installed. If 'docker' fails with permission denied, log out/in (or reboot) and re-run this script."
fi

need_cmd docker
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 plugin is required (docker compose)"

cd "${ROOT}"

if [[ ! -f "${ENV_FILE}" ]]; then
  [[ -f "${ENV_EXAMPLE}" ]] || die "missing ${ENV_EXAMPLE}"
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"

  ADMIN_TOKEN="$(rand_hex)"
  SESSION_SECRET="$(rand_hex)"
  CONNECTIONS_SECRET="$(rand_hex)"
  DASH_PASS="$(rand_hex | cut -c1-16)"
  DB_PASS="$(rand_hex | cut -c1-16)"

  set_env_kv POSTGRES_PASSWORD "${DB_PASS}"
  set_env_kv DATABASE_URL "postgresql+asyncpg://parent:${DB_PASS}@db:5432/parent_network"
  set_env_kv ADMIN_USERNAME "admin"
  set_env_kv ADMIN_PASSWORD "${DASH_PASS}"
  set_env_kv ADMIN_TOKEN "${ADMIN_TOKEN}"
  set_env_kv DASHBOARD_USERNAME "admin"
  set_env_kv DASHBOARD_PASSWORD "${DASH_PASS}"
  set_env_kv DASHBOARD_SESSION_SECRET "${SESSION_SECRET}"
  set_env_kv DASHBOARD_COOKIE_SECURE "false"
  set_env_kv CONNECTIONS_SECRET "${CONNECTIONS_SECRET}"

  # Clear upstream placeholders — wizard will set these.
  set_env_kv PIHOLE_PASSWORD ""
  set_env_kv UNIFI_USERNAME ""
  set_env_kv UNIFI_PASSWORD ""

  GENERATED_PASSWORD="${DASH_PASS}"
  log "Created ${ENV_FILE} with generated secrets."
else
  GENERATED_PASSWORD=""
  log "Using existing ${ENV_FILE}"
fi

log "Building and starting containers (first build on a Pi can take several minutes)…"
"${COMPOSE[@]}" up -d --build

IP="$(lan_ip)"
IP="${IP:-<pi-lan-ip>}"
PORT="$(grep -E '^FRONTEND_PORT=' "${ENV_FILE}" | cut -d= -f2- || true)"
PORT="${PORT:-3000}"

log ""
log "============================================"
log " Parent Network Dashboard is starting"
log "============================================"
log " Setup wizard:  http://${IP}:${PORT}/setup"
log " Sign in:       http://${IP}:${PORT}/login"
if [[ -n "${GENERATED_PASSWORD}" ]]; then
  log " Username:      admin"
  log " Password:      ${GENERATED_PASSWORD}"
  log " (Save this password — it is only shown once.)"
fi
log ""
log " Next: open the setup wizard and enter Pi-hole / UniFi details."
log " Day-2: git pull && make up"
log "============================================"
