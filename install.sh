#!/usr/bin/env bash
set -euo pipefail
REPO="${REPO:-vasa57kam/datacenter-core}"
INSTALL_DIR="${INSTALL_DIR:-/opt/billing}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@itkam34.ru}"
CREDS_FILE="/root/billing-creds.env"
log() { echo "[billing] $*"; }
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
MODE="${1:-install}"
clone_url() {
  if [ -n "${GIT_TOKEN:-}" ]; then echo "https://x-access-token:${GIT_TOKEN}@github.com/${REPO}.git"
  else echo "https://github.com/${REPO}.git"; fi
}
compose() { docker compose -f "${INSTALL_DIR}/docker-compose.yml" --env-file "${INSTALL_DIR}/.env" "$@"; }
ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then curl -fsSL https://get.docker.com | sh; fi
  if ! docker compose version >/dev/null 2>&1; then apt-get update && apt-get install -y docker-compose-plugin; fi
  systemctl enable --now docker
}
fetch_repo() {
  if [ -d "${INSTALL_DIR}/.git" ]; then git -C "${INSTALL_DIR}" pull --ff-only
  else git clone "$(clone_url)" "${INSTALL_DIR}"; [ -n "${GIT_TOKEN:-}" ] && chmod 700 "${INSTALL_DIR}/.git"; fi
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
  chmod 600 "${INSTALL_DIR}/.env"
}
deploy() {
  compose up -d --build db redis api worker
  for _ in $(seq 1 30); do compose exec -T db pg_isready -U billing -d billing >/dev/null 2>&1 && break; sleep 2; done
  compose run --rm api python scripts/init_db.py
  compose run --rm api python scripts/seed_products.py
}
make_admin() {
  if [ -f "${CREDS_FILE}" ]; then log "admin creds in ${CREDS_FILE}"; return; fi
  local PASS; PASS=$(openssl rand -base64 15)
  compose run --rm api python scripts/create_admin.py --email "${ADMIN_EMAIL}" --password "${PASS}"
  umask 077
  printf 'ADMIN_EMAIL=%s\nADMIN_PASSWORD=%s\n' "${ADMIN_EMAIL}" "${PASS}" > "${CREDS_FILE}"
}
install_backup_cron() {
  mkdir -p /var/backups
  cat > /etc/cron.d/billing-backup <<'CRON'
15 2 * * * root docker compose -f /opt/billing/docker-compose.yml --env-file /opt/billing/.env exec -T db pg_dump -U billing billing | zstd -9 -o /var/backups/billing-$(date +\%F).sql.zst
CRON
}
case "${MODE}" in
  install|update) ensure_docker; fetch_repo; make_env; deploy; make_admin; install_backup_cron
    log "OK: curl http://127.0.0.1:8008/healthz" ;;
  backup) compose exec -T db pg_dump -U billing billing | zstd -9 -o "/var/backups/billing-$(date +%F-%H%M).sql.zst" ;;
  status) compose ps; curl -fsS http://127.0.0.1:8008/healthz || true ;;
  *) echo "usage: install.sh [install|update|backup|status]"; exit 1 ;;
esac
