#!/usr/bin/env bash
set -e
NEW=${1:-$(openssl rand -hex 10)}
sed -i "s/^HUB_PASSWORD=.*/HUB_PASSWORD=$NEW/" /opt/hub/.hub_env
systemctl restart hub-web
echo "✓ Новый пароль Git-хаба: $NEW"
