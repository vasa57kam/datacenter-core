#!/usr/bin/env bash
set -euo pipefail
REPO="${REPO:-vasa57kam/datacenter-core}"
INSTALL_DIR="${INSTALL_DIR:-/opt/billing}"
ADMIN_EMAIL="${ADMIN_EMAIL:-}"
CREDS_FILE="/root/billing-creds.env"
log() { echo "[billing] $*"; }
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
MODE="${1:-install}"
case "${MODE}" in install|update) [ -n "${ADMIN_EMAIL}" ] || [ -f "${CREDS_FILE}" ] \
  || { echo "set ADMIN_EMAIL=you@example.com"; exit 1; } ;; esac
clone_url() {
  if [ -n "${GIT_TOKEN:-}" ]; then echo "https://x-access-token:${GIT_TOKEN}@github.com/${REPO}.git"
  else echo "https://github.com/${REPO}.git"; fi
}
compose() { docker compose -f "${INSTALL_DIR}/docker-compose.yml" --env-file "${INSTALL_DIR}/.env" "$@"; }
ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then curl -fsSL https://get.docker.com | sh; fi
  if ! docker compose version >/dev/null 2>&1; then apt-get update && apt-get install -y docker-compose-plugin; fi
  command -v zstd >/dev/null 2>&1 || { apt-get update && apt-get install -y zstd; }
  systemctl enable --now docker
}
fetch_repo() {
  if [ -d "${INSTALL_DIR}/.git" ]; then
    git -C "${INSTALL_DIR}" pull --ff-only
  else
    git clone "$(clone_url)" "${INSTALL_DIR}"
    if [ -n "${GIT_TOKEN:-}" ]; then
      # не оставляем токен в .git/config
      git -C "${INSTALL_DIR}" remote set-url origin "https://github.com/${REPO}.git"
    fi
  fi
}

make_env() {
  if [ -f "${INSTALL_DIR}/.env" ]; then log ".env exists — keeping"; return; fi
  local PG_PASS JWT_SEC INT_KEY FERNET
  PG_PASS=$(openssl rand -hex 24); JWT_SEC=$(openssl rand -hex 32)
  INT_KEY=$(openssl rand -hex 24); FERNET=$(openssl rand -base64 32)
  cat > "${INSTALL_DIR}/.env" <<ENV
POSTGRES_PASSWORD=${PG_PASS}
DATABASE_URL=postgresql+psycopg://billing:${PG_PASS}@db:5432/billing
REDIS_URL=redis://redis:6379/0
JWT_SECRET=${JWT_SEC}
INTERNAL_API_KEY=${INT_KEY}
CRYPTO_KEY=${FERNET}
HEARTBEAT_GRACE_SECONDS=300
CHARGE_INTERVAL_SECONDS=20
PROVISIONING_INTERVAL_SECONDS=15
ENV
  if [ -n "${DOMAIN:-}" ]; then echo "DOMAIN=${DOMAIN}" >> "${INSTALL_DIR}/.env"; fi
  chmod 600 "${INSTALL_DIR}/.env"
}
deploy() {
  compose up -d --build db redis api worker
  local ready=0
  for _ in $(seq 1 30); do
    if compose exec -T db pg_isready -U billing -d billing >/dev/null 2>&1; then ready=1; break; fi
    sleep 2
  done
  [ "${ready}" -eq 1 ] || { echo "database did not become ready"; exit 1; }
  compose run --rm api python scripts/init_db.py
  compose run --rm api python scripts/seed_products.py
}
make_admin() {
  if [ -f "${CREDS_FILE}" ]; then log "admin creds in ${CREDS_FILE}"; return; fi
  local PASS; PASS=$(openssl rand -hex 12)
  ( umask 077; printf 'ADMIN_EMAIL=%s\nADMIN_PASSWORD=%s\n' "${ADMIN_EMAIL}" "${PASS}" > "${CREDS_FILE}" )
  compose run --rm api python scripts/create_admin.py --email "${ADMIN_EMAIL}" --password "${PASS}" \
    || { rm -f "${CREDS_FILE}"; exit 1; }
}
install_backup_cron() {
  mkdir -p /var/backups
  cat > /etc/cron.d/billing-backup <<'CRON'
15 2 * * * root /opt/billing/install.sh backup && find /var/backups -name 'billing-*.sql.zst' -mtime +14 -delete
CRON
}
case "${MODE}" in
  install|update) ensure_docker; fetch_repo; make_env; deploy; make_admin; install_backup_cron
    log "OK: curl http://127.0.0.1:8008/healthz" ;;
  backup)
    mkdir -p /var/backups
    out="/var/backups/billing-$(date +%F-%H%M).sql.zst"
    if compose exec -T db pg_dump -U billing billing | zstd -9 -f -o "${out}.tmp"; then mv "${out}.tmp" "${out}"
    else rm -f "${out}.tmp"; echo "backup failed"; exit 1; fi ;;
  status) compose ps; curl -fsS http://127.0.0.1:8008/healthz || true ;;
  *) echo "usage: install.sh [install|update|backup|status]"; exit 1 ;;
esac
