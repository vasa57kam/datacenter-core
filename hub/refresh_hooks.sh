#!/usr/bin/env bash
set -e
for d in /srv/git/*.git; do
  cat > "$d/hooks/post-receive" <<'HOOK'
#!/usr/bin/env bash
NAME=$(basename "$PWD" .git)
DEPLOY="/srv/git/$NAME.deploy"
[ -f "$DEPLOY" ] || exit 0
while read -r host port path post; do
  [ -z "${host:-}" ] && continue
  case "$host" in \#*) continue;; esac
  ssh -o StrictHostKeyChecking=accept-new -p "${port:-22}" root@"$host" "
    cd '$path' || exit 1
    git remote get-url hub >/dev/null 2>&1 || git remote add hub ssh://root@192.168.0.135/srv/git/$NAME.git
    if git fetch origin main >/dev/null 2>&1; then SRC=origin/main;
    elif git fetch hub main >/dev/null 2>&1; then SRC=hub/main; echo '[fallback] hub instead of github' >> /var/log/hub-deploy.log;
    else echo \"[\$(date)] $NAME: ни GitHub, ни хаб недоступны\" >> /var/log/hub-deploy.log; exit 1; fi
    git reset --hard \$SRC >> /var/log/hub-deploy.log 2>&1
    [ -n '$post' ] && bash '$post' >> /var/log/hub-deploy.log 2>&1
  " >> /var/log/hub-deploy.log 2>&1
done < "$DEPLOY"
HOOK
  chmod +x "$d/hooks/post-receive"
done
echo "✓ hooks v2 (github primary, hub fallback)"
