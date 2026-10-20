#!/usr/bin/env bash
set -euo pipefail
[ "$EUID" -ne 0 ] && { echo "Запусти от root"; exit 1; }
mkdir -p /opt/hub /srv/git /var/log
touch /var/log/hub-deploy.log && chmod 644 /var/log/hub-deploy.log
if [ ! -f /opt/hub/.hub_env ]; then
  PW=$(openssl rand -hex 10)
  SEC=$(openssl rand -hex 24)
  IP=$(hostname -I | awk '{print $1}')
  cat > /opt/hub/.hub_env <<EOF
HUB_PASSWORD=$PW
HUB_SECRET=$SEC
HUB_PORT=8080
HUB_HOST=$IP
EOF
  chmod 600 /opt/hub/.hub_env
fi
[ -d /opt/hub/venv ] || python3 -m venv /opt/hub/venv
/opt/hub/venv/bin/pip install -q flask
# Копируем исходники
cp -r /root/datacenter-core/hub/* /opt/hub/
cat > /etc/systemd/system/hub-web.service <<'UNIT'
[Unit]
Description=ITKAM34 Git Hub Web
After=network.target
[Service]
Type=simple
User=root
WorkingDirectory=/opt/hub
EnvironmentFile=/opt/hub/.hub_env
Environment=PATH=/opt/hub/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/hub/venv/bin/python /opt/hub/hub_server.py
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now hub-web
systemctl restart hub-web
sleep 2
IP=$(grep HUB_HOST /opt/hub/.hub_env | cut -d= -f2)
PW=$(grep HUB_PASSWORD /opt/hub/.hub_env | cut -d= -f2)
echo "═══════════════════════════════════════════"
echo "Git-хаб:  http://$IP:8080"
echo "Пароль:   $PW"
echo "═══════════════════════════════════════════"
