"""Git-хаб ITKAM34: веб-управление bare-репо и автодеплоем."""
import os
import subprocess
import time
from pathlib import Path
from flask import Flask, request, render_template, redirect, session, jsonify

BASE = Path("/srv/git")
LOG = Path("/var/log/hub-deploy.log")
ENV = Path("/opt/hub/.hub_env")

def env():
    d = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k] = v
    return d

ENV_VARS = env()
app = Flask(__name__)
app.secret_key = ENV_VARS.get("HUB_SECRET", os.urandom(24))

def auth():
    return session.get("hub") == "yes"

def repos():
    out = []
    for p in sorted(BASE.glob("*.git")):
        name = p.stem
        deploy = BASE / f"{name}.deploy"
        targets = []
        if deploy.exists():
            for line in deploy.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split(maxsplit=3)
                    if len(parts) >= 3:
                        targets.append({"host": parts[0], "port": parts[1], "path": parts[2],
                                        "post": parts[3] if len(parts) > 3 else ""})
        try:
            last = subprocess.check_output(
                ["git", "-C", str(p), "log", "-1", "--pretty=%ad|%h|%s", "--date=short"],
                stderr=subprocess.DEVNULL, timeout=5).decode().strip()
            date, h, msg = last.split("|", 2)
        except Exception:
            date, h, msg = "—", "—", "пусто"
        out.append({"name": name, "targets": targets, "last": {"date": date, "h": h, "msg": msg}})
    return out

@app.route("/login", methods=["GET", "POST"])
def login():
    err = None
    if request.method == "POST":
        if request.form.get("password") == ENV_VARS.get("HUB_PASSWORD"):
            session["hub"] = "yes"
            return redirect("/")
        err = "Неверный пароль"
    return render_template("login.html", error=err)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
def index():
    if not auth(): return redirect("/login")
    return render_template("repos.html", repos=repos(), flash=request.args.get("ok"),
                           host=request.host.split(":")[0])

@app.route("/create", methods=["POST"])
def create():
    if not auth(): return redirect("/login")
    name = (request.form.get("name") or "").strip()
    if name and not any(c in name for c in "/\\ "):
        target = BASE / f"{name}.git"
        if not target.exists():
            subprocess.run(["git", "init", "--bare", "-b", "main", str(target)],
                           check=True, capture_output=True)
            hook = f"""#!/usr/bin/env bash
NAME=$(basename "$PWD" .git)
DEPLOY="/srv/git/$NAME.deploy"
[ -f "$DEPLOY" ] || exit 0
while read -r port path post; do
  [ -z "${{port:-}}" ] && continue
  case "$port" in \\#*) continue;; esac
  ssh -o StrictHostKeyChecking=accept-new -p "${{port:-22}}" root@"$host" \\
    "cd '$path' && git fetch origin main && git reset --hard origin/main && {{ [ -n '$post' ] && bash '$post'; }}" >> {LOG} 2>&1
done < "$DEPLOY"
"""
            (target / "hooks" / "post-receive").write_text(hook)
            (target / "hooks" / "post-receive").chmod(0o755)
    return redirect("/?ok=repo_created")

@app.route("/delete/<name>", methods=["POST"])
def delete(name):
    if not auth(): return redirect("/login")
    target = BASE / f"{name}.git"
    deploy = BASE / f"{name}.deploy"
    if target.exists():
        subprocess.run(["rm", "-rf", str(target)], check=False)
    if deploy.exists(): deploy.unlink()
    return redirect("/?ok=repo_deleted")

@app.route("/deploy/<name>", methods=["GET"])
def deploy_edit(name):
    if not auth(): return redirect("/login")
    deploy = BASE / f"{name}.deploy"
    targets = []
    if deploy.exists():
        for line in deploy.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split(maxsplit=3)
                if len(parts) >= 3:
                    targets.append({"host": parts[0], "port": parts[1], "path": parts[2],
                                    "post": parts[3] if len(parts) > 3 else ""})
    return render_template("deploy_edit.html", name=name, targets=targets)

@app.route("/deploy/<name>/save", methods=["POST"])
def deploy_save(name):
    if not auth(): return redirect("/login")
    deploy = BASE / f"{name}.deploy"
    lines = []
    i = 0
    while True:
        host = request.form.get(f"host_{i}")
        port = request.form.get(f"port_{i}")
        path = request.form.get(f"path_{i}")
        post = request.form.get(f"post_{i}", "")
        if host is None: break
        if host and path:
            lines.append(f"{host} {port or 22} {path} {post}".strip())
        i += 1
    deploy.write_text("\n".join(lines) + "\n" if lines else "")
    return redirect(f"/deploy/{name}?ok=saved")

@app.route("/deploy/<name>/run", methods=["POST"])
def deploy_run(name):
    if not auth(): return redirect("/login")
    target = BASE / f"{name}.git"
    subprocess.run([str(target / "hooks" / "post-receive")],
                   input=b"0000 0000 refs/heads/main\n",
                   cwd=str(target), check=False, timeout=60)
    return redirect(f"/logs?ok=triggered:{name}")

@app.route("/logs")
def logs():
    if not auth(): return redirect("/login")
    try:
        lines = LOG.read_text().splitlines()[-200:]
    except FileNotFoundError:
        lines = []
    return render_template("logs.html", lines=reversed(lines),
                           flash=request.args.get("ok"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(ENV_VARS.get("HUB_PORT", "8080")))
