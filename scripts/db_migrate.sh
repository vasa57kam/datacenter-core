#!/usr/bin/env bash
set -uo pipefail
cd /opt/billing || exit 1
docker compose exec -T db psql -U billing -d billing -v ON_ERROR_STOP=0 <<'SQL'
CREATE TABLE IF NOT EXISTS system_settings (key text PRIMARY KEY, value text NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS patch_history (id serial PRIMARY KEY, version text NOT NULL, actor_email text NOT NULL DEFAULT '', summary text NOT NULL DEFAULT '', applied_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS notifications (id serial PRIMARY KEY, kind text NOT NULL DEFAULT 'info', message text NOT NULL, created_at timestamptz DEFAULT now(), read_at timestamptz);
CREATE TABLE IF NOT EXISTS audit_log (id serial PRIMARY KEY, actor_id integer, actor_email text NOT NULL DEFAULT '', action text NOT NULL, target text NOT NULL DEFAULT '', created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS payment_methods (id serial PRIMARY KEY, code text UNIQUE NOT NULL, title text NOT NULL, instructions text NOT NULL DEFAULT '', active boolean NOT NULL DEFAULT true, client_visible boolean NOT NULL DEFAULT true, sort_order integer NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS coupons (id serial PRIMARY KEY, code text UNIQUE NOT NULL, kind text NOT NULL DEFAULT 'promo', amount_minor integer NOT NULL, max_activations integer NOT NULL DEFAULT 1, activations_count integer NOT NULL DEFAULT 0, active boolean NOT NULL DEFAULT true, expires_at timestamptz, note text, created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS coupon_activations (id serial PRIMARY KEY, coupon_id integer NOT NULL REFERENCES coupons(id) ON DELETE CASCADE, user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE, amount_minor integer NOT NULL, created_at timestamptz DEFAULT now(), UNIQUE(coupon_id, user_id));
CREATE TABLE IF NOT EXISTS support_tickets (id serial PRIMARY KEY, user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE, subject text NOT NULL, status text NOT NULL DEFAULT 'open', created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS ticket_messages (id serial PRIMARY KEY, ticket_id integer NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE, author_role text NOT NULL, body text NOT NULL, created_at timestamptz DEFAULT now());
ALTER TABLE users ADD COLUMN IF NOT EXISTS register_ip text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_used boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone text;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_ck;
ALTER TABLE users ADD CONSTRAINT users_role_ck CHECK (role IN ('client','admin','cashier'));
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS auto_approved_count integer NOT NULL DEFAULT 0;
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS auto_approve_limit_minor integer;
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS auto_approve_max_uses integer NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by integer REFERENCES users(id);
SQL
