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
  ssh -o StrictHostKeyChecking=accept-new -p "${port:-22}" root@"$host" \
    "cd '$path' && git fetch origin main && git reset --hard origin/main && { [ -n '$post' ] && bash '$post'; }" >> /var/log/hub-deploy.log 2>&1
done < "$DEPLOY"
HOOK
  chmod +x "$d/hooks/post-receive"
done
echo "✓ hooks refreshed for: $(ls /srv/git | tr '\n' ' ')"
