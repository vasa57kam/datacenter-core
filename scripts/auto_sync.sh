#!/usr/bin/env bash
exec 9>/var/lock/billing-deploy.lock
flock -n 9 || { echo "deploy уже идёт — пропускаю"; exit 0; }

# Синхронизация: сравниваем КОММИТ В ОБРАЗЕ (.last_built_commit) с origin/main.
set -uo pipefail
cd /opt/billing || exit 0
LOCK=/tmp/billing_sync.lock
exec 9>"$LOCK"; flock -n 9 || exit 0
LOG=/opt/billing/sync.log

git fetch origin main -q || exit 0
REMOTE=$(git rev-parse origin/main)
LOCAL=$(git rev-parse HEAD)
echo "$REMOTE" > .last_origin
grep -q '^ORIGIN_COMMIT=' .env 2>/dev/null && sed -i "s/^ORIGIN_COMMIT=.*/ORIGIN_COMMIT=$REMOTE/" .env || echo "ORIGIN_COMMIT=$REMOTE" >> .env

FORCE=0
[ -f /tmp/billing_rebuild.flag ] && { FORCE=1; rm -f /tmp/billing_rebuild.flag; }

LAST_BUILT=$(cat .last_built_commit 2>/dev/null || echo none)
[ "$LAST_BUILT" = "$REMOTE" ] && [ "$FORCE" = "0" ] && exit 0

echo "[$(date)] sync: built=$LAST_BUILT remote=$REMOTE force=$FORCE" >> "$LOG"
if [ "$LOCAL" != "$REMOTE" ]; then
  git merge-base --is-ancestor "$LOCAL" "$REMOTE" || { echo "[$(date)] DIVERGED — нужен ручной разбор" >> "$LOG"; exit 0; }
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "[$(date)] dirty worktree: сбрасываю локальные правки tracked-файлов (все изменения идут через git)" >> "$LOG"
    git reset --hard "$LOCAL" >> "$LOG" 2>&1
  fi
  git pull --ff-only origin main >> "$LOG" 2>&1 || exit 1
fi
grep -q '^DEPLOYED_COMMIT=' .env 2>/dev/null && sed -i "s/^DEPLOYED_COMMIT=.*/DEPLOYED_COMMIT=$REMOTE/" .env || echo "DEPLOYED_COMMIT=$REMOTE" >> .env
docker compose build --no-cache api worker >> "$LOG" 2>&1 || { echo "[$(date)] BUILD FAILED" >> "$LOG"; exit 1; }
docker compose up -d >> "$LOG" 2>&1
docker compose restart api worker >> "$LOG" 2>&1
sleep 8
bash scripts/db_migrate.sh >> "$LOG" 2>&1 || true
VER=$(cat VERSION 2>/dev/null || echo unknown)
docker compose exec -T db psql -U billing -d billing -c "INSERT INTO system_settings(key,value) VALUES('app_version','$VER') ON CONFLICT(key) DO UPDATE SET value='$VER';" >> "$LOG" 2>&1 || true
docker compose exec -T db psql -U billing -d billing -c "INSERT INTO system_settings(key,value) VALUES('app_commit','$REMOTE') ON CONFLICT(key) DO UPDATE SET value='$REMOTE';" >> "$LOG" 2>&1 || true
echo "$REMOTE" > .last_built_commit
curl -s http://127.0.0.1:8008/healthz >> "$LOG" 2>&1
echo "[$(date)] sync done, image=$REMOTE" >> "$LOG"
