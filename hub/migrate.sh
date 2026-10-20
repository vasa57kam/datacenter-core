#!/usr/bin/env bash
set -e
mkdir -p /srv/git
for R in datacenter-core hosting-deploy cctv-deploy; do
  [ -d "/srv/git/$R.git" ] || git init --bare -b main "/srv/git/$R.git"
  cd "/root/$R"
  git remote remove hub 2>/dev/null || true
  git remote add hub "/srv/git/$R.git"
  git push hub --all -q 2>/dev/null || true
  # Добавляем post-receive хук (тот же что и в hub_server.py создаёт)
  HUB_HOST=$(grep HUB_HOST /opt/hub/.hub_env 2>/dev/null | cut -d= -f2 || hostname -I | awk '{print $1}')
  cat > "/srv/git/$R.git/hooks/post-receive" <<HOOK
#!/usr/bin/env bash
NAME=\$(basename "\$PWD" .git)
DEPLOY="/srv/git/\$NAME.deploy"
[ -f "\$DEPLOY" ] || exit 0
while read -r port path post; do
  [ -z "\${port:-}" ] && continue
  case "\$port" in \\#*) continue;; esac
  ssh -o StrictHostKeyChecking=accept-new -p "\$port" root@$HUB_HOST \\
    "cd '\$path' && git fetch origin main && git reset --hard origin/main && { [ -n '\$post' ] && bash '\$post'; }" >> /var/log/hub-deploy.log 2>&1
done < "\$DEPLOY"
HOOK
  chmod +x "/srv/git/$R.git/hooks/post-receive"
done
# Цели
echo "2172 /opt/hosting /opt/hosting/scripts/post_deploy.sh" > /srv/git/hosting-deploy.deploy
echo "2135 /opt/hub" > /srv/git/datacenter-core.deploy
echo "✓ Миграция завершена. Открой http://$(grep HUB_HOST /opt/hub/.hub_env 2>/dev/null | cut -d= -f2):8080"
