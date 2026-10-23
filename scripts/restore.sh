#!/usr/bin/env bash
set -euo pipefail
B=${1:?каталог бэкапа, например /opt/backups/billing-20261022-031700}
cd /opt/billing
docker compose stop api worker
gunzip -c "$B/db.sql.gz" | docker compose exec -T db psql -U billing -d billing
tar xzf "$B/config.tgz" -C /opt/billing 2>/dev/null || true
docker compose start api worker
bash scripts/doctor.sh
echo "restore ok: $B"
