#!/usr/bin/env bash
cp -r /root/datacenter-core/hub/. /opt/hub/
systemctl restart hub-web
echo "[post-deploy] $(date) hub-web updated+restarted"
