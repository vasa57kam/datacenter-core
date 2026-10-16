#!/usr/bin/env bash
set -uo pipefail
cd /opt/billing || exit 1
docker compose exec -T db psql -U billing -d billing -v ON_ERROR_STOP=0 <<'SQL'
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS auto_approved_count integer NOT NULL DEFAULT 0;
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS auto_approve_limit_minor integer;
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS auto_approve_max_uses integer NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by integer REFERENCES users(id);
SQL
