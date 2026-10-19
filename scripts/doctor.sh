#!/usr/bin/env bash
# Доктор: полная синхронизация + проверка согласованности.
# Что может — чинит сам. Что не может — печатает диагноз по-русски.
set -uo pipefail
export GIT_PAGER=cat PAGER=cat LESS=
cd /opt/billing || { echo "❌ Не удалось зайти в /opt/billing"; exit 1; }
LOG=/opt/billing/sync.log
say(){ echo "▶ $*"; }
fail(){ echo; echo "❌ $*"; echo; echo "--- последние 20 строк $LOG ---"; tail -20 "$LOG" 2>/dev/null; exit 1; }

say "1/8 Состояние git"
git fetch origin main -q || fail "Нет доступа к GitHub (сеть/токен). Проверь: git fetch origin main"
LOCAL=$(git rev-parse HEAD); REMOTE=$(git rev-parse origin/main)
echo "   сервер: ${LOCAL:0:8}   git: ${REMOTE:0:8}"

if [ "$LOCAL" != "$REMOTE" ]; then
  say "2/8 Синхронизация кода"
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "   найдены локальные правки — сбрасываю (все изменения ходят только через git)"
    git reset --hard "$LOCAL" >>"$LOG" 2>&1
  fi
  git merge-base --is-ancestor "$LOCAL" "$REMOTE" || fail "История разошлась: локальные коммиты не в git. Решение вручную: git reset --hard origin/main"
  git pull --ff-only origin main >>"$LOG" 2>&1 || fail "git pull не прошёл. Смотри вывод выше; обычно мешает грязный файл: git status --short"
else
  say "2/8 Код уже актуален"
fi

BUILT=$(cat .last_built_commit 2>/dev/null || echo none)
HEAD=$(git rev-parse HEAD)
if [ "$BUILT" != "$HEAD" ] || [ "${1:-}" = "--rebuild" ]; then
  say "3/8 Пересборка контейнеров без кэша (1–3 минуты)"
  docker compose build --no-cache api worker >>"$LOG" 2>&1 || fail "Ошибка сборки docker. Смотри: tail -40 $LOG"
  if ! docker compose up -d >>"$LOG" 2>&1; then
    echo "   чищу зависшие контейнеры с хэшем в имени и повторяю"
    docker ps -a --format '{{.Names}}' | grep -E '^[0-9a-f]{12}_' | xargs -r docker rm -f >>"$LOG" 2>&1
    docker compose up -d >>"$LOG" 2>&1 || fail "docker compose up -d не стартовал: tail -20 $LOG"
  fi
  docker compose restart api worker >>"$LOG" 2>&1
  echo "$HEAD" > .last_built_commit
else
  say "3/8 Образ уже собран из текущего коммита"
fi

say "4/8 Ожидание API (до 60 секунд)"
code=""
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8008/healthz 2>/dev/null || true)
  [ "$code" = "200" ] && break
  sleep 2
done
if [ "$code" != "200" ]; then
  echo
  echo "❌ API не поднялся. Последние логи api:"
  docker compose logs api --tail=25 | tail -25
  echo
  echo "Логи worker:"
  docker compose logs worker --tail=10 | tail -10
  exit 1
fi

say "5/8 Миграции БД"
bash scripts/db_migrate.sh >>"$LOG" 2>&1 || fail "Ошибка миграций: tail -20 $LOG"
docker compose run --rm -T api python -c "from app.db import engine; from app.models import Base; Base.metadata.create_all(bind=engine)" >>"$LOG" 2>&1 || true

say "6/8 Версия и коммит в БД"
VER=$(cat VERSION 2>/dev/null || echo unknown)
docker compose exec -T db psql -U billing -d billing -c "INSERT INTO system_settings(key,value) VALUES('app_version','$VER'),('app_commit','$HEAD') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value;" >>"$LOG" 2>&1 || fail "Не удалось записать версию в БД: tail -20 $LOG"

say "7/8 Проверка согласованности"
DBV=$(docker compose exec -T db psql -U billing -d billing -tAc "SELECT value FROM system_settings WHERE key='app_commit'" 2>/dev/null | tr -d ' \r')
[ "$DBV" = "$HEAD" ] || fail "Коммит в БД ($DBV) != коммит на сервере ($HEAD)"
docker compose exec -T api test -f /app/app/services/offline_guard.py || fail "В контейнере нет offline_guard.py — образ старый. Запусти: bash scripts/doctor.sh --rebuild"
docker compose exec -T api grep -q "set_client_expiry" /app/app/adapters/vpn/threexui.py || fail "В контейнере старый адаптер 3x-ui. Запусти: bash scripts/doctor.sh --rebuild"

say "8/8 Контейнеры"
docker compose ps --format "table {{.Name}}\t{{.Status}}" | sed 's/^/   /'

echo
echo "✅ ВСЁ СИНХРОНИЗИРОВАНО И СООТВЕТСТВУЕТ: версия v$VER, коммит ${HEAD:0:8}"
echo "   В браузере: /admin-ops/status — бейдж «Сервер синхронизирован с git»"
