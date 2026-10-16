#!/usr/bin/env bash
set -uo pipefail
cd /opt/billing || exit 1
if ! grep -q billing-sync /etc/cron.d/billing-sync 2>/dev/null; then
  echo "* * * * * root /opt/billing/scripts/auto_sync.sh >> /opt/billing/sync.log 2>&1" > /etc/cron.d/billing-sync
  chmod 644 /etc/cron.d/billing-sync
  echo "cron installed"
fi
bash scripts/auto_sync.sh
echo "bootstrap done; далее сервер синхронизируется сам каждую минуту"
