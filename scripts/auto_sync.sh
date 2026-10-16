#!/usr/bin/env bash
# Автосинхронизация: если origin/main ушёл вперёд — pull, пересборка, миграции, версия в БД.
set -uo pipefail
cd /opt/billing || exit 0
LOCK=/tmp/billing_sync.lock
exec 9>"$LOCK"; flock -n 9 || exit 0
LOG=/opt/billing/sync.log

git fetch origin main -q || exit 0
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
echo "$REMOTE" > .last_origin
grep -q '^ORIGIN_COMMIT=' .env 2>/dev/null && sed -i "s/^ORIGIN_COMMIT=.*/ORIGIN_COMMIT=$REMOTE/" .env || echo "ORIGIN_COMMIT=$REMOTE" >> .env

FORCE=0
[ -f /tmp/billing_rebuild.flag ] && { FORCE=1; rm -f /tmp/billing_rebuild.flag; }
[ "$LOCAL" = "$REMOTE" ] && [ "$FORCE" = "0" ] && exit 0
git merge-base --is-ancestor "$LOCAL" "$REMOTE" || { echo "[$(date)] DIVERGED — нужен ручной разбор" >> "$LOG"; exit 0; }

echo "[$(date)] sync $LOCAL -> $REMOTE (force=$FORCE)" >> "$LOG"
git pull --ff-only origin main >> "$LOG" 2>&1 || exit 1
grep -q '^DEPLOYED_COMMIT=' .env 2>/dev/null && sed -i "s/^DEPLOYED_COMMIT=.*/DEPLOYED_COMMIT=$REMOTE/" .env || echo "DEPLOYED_COMMIT=$REMOTE" >> .env
docker compose build --no-cache api worker >> "$LOG" 2>&1
docker compose up -d >> "$LOG" 2>&1
docker compose restart api worker >> "$LOG" 2>&1
sleep 8
bash scripts/db_migrate.sh >> "$LOG" 2>&1 || true
VER=$(cat VERSION 2>/dev/null || echo unknown)
docker compose exec -T db psql -U billing -d billing -c "INSERT INTO system_settings(key,value) VALUES('app_version','$VER') ON CONFLICT(key) DO UPDATE SET value='$VER';" >> "$LOG" 2>&1 || true
docker compose exec -T db psql -U billing -d billing -c "INSERT INTO system_settings(key,value) VALUES('app_commit','$REMOTE') ON CONFLICT(key) DO UPDATE SET value='$REMOTE';" >> "$LOG" 2>&1 || true
curl -s http://127.0.0.1:8008/healthz >> "$LOG" 2>&1
echo "[$(date)] sync done" >> "$LOG"
