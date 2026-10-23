#!/usr/bin/env bash
set -euo pipefail
cd /opt/billing
STAMP=$(date +%Y%m%d-%H%M%S)
DIR=/opt/backups/billing-$STAMP
mkdir -p "$DIR"
docker compose exec -T db pg_dump -U billing billing | gzip > "$DIR/db.sql.gz"
tar czf "$DIR/config.tgz" .env docker-compose.yml scripts/ 2>/dev/null || true
git -C /root/datacenter-core bundle create "$DIR/repo.bundle" --all 2>/dev/null || true
git -C /root/datacenter-core rev-parse HEAD > "$DIR/commit.txt"
cat > "$DIR/README.txt" <<'TX'
Восстановление:
1) Код:   cd /root/datacenter-core && git fetch /opt/backups/billing-<STAMP>/repo.bundle main && git reset --hard FETCH_HEAD && cd /opt/billing && bash scripts/doctor.sh
2) БД:    cd /opt/billing && bash scripts/restore.sh /opt/backups/billing-<STAMP>
TX
find /opt/backups -maxdepth 1 -name 'billing-*' -mtime +14 -exec rm -rf {} + 2>/dev/null || true
rsync -aq /opt/backups/ root@192.168.0.172:/opt/backups/billing-offsite/ 2>/dev/null || echo "offsite: недоступен (не критично)"
echo "backup ok: $DIR ($(du -sh "$DIR" | cut -f1))"
