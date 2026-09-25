#!/usr/bin/env bash
# Deploy HexTrack to the Pi.
#
#   ./deploy.sh                 push the current branch, build on the Pi, install, migrate, restart
#   ./deploy.sh --force         same, even if the Pi already runs this commit
#   ./deploy.sh --install-only  build, install and migrate, but don't restart (first install)
#   ./deploy.sh --rollback      switch the Pi back to the previous release and restart
#   ./deploy.sh --status        show what the Pi is running
#   ./deploy.sh --logs          follow the Pi's HexTrack logs (Ctrl-C to stop)
#
# Only committed code is deployed. On the Pi, walker builds a release in
# ~/hextrack-staging/<commit> without any privileges (git archive, uv, npm), then three
# whitelisted root commands install it (see deploy/sudoers.hextrack):
#   sudo hextrack-install <staging dir>     copy to /opt/hextrack/releases, switch "current"
#   sudo systemctl start hextrack-migrate   Alembic, as the schema owner
#   sudo systemctl restart hextrack-...     the services run as the hextrack user
# A failed health check rolls back to the previous release. Secrets (/etc/hextrack), the
# database and the models (/var/lib/hextrack) are never touched by a deploy.
#
# Overrides: DEPLOY_HOST (default rpi5), DEPLOY_PUBLIC_URL (default https://hextrack.slabby.dev).
set -euo pipefail

HOST="${DEPLOY_HOST:-rpi5}"
PUBLIC_URL="${DEPLOY_PUBLIC_URL:-https://hextrack.slabby.dev}"

bold=$'\033[1m' green=$'\033[32m' yellow=$'\033[33m' red=$'\033[31m' reset=$'\033[0m'
step() { printf '%s==>%s %s\n' "$bold" "$reset" "$*"; }
warn() { printf '%swarning:%s %s\n' "$yellow" "$reset" "$*" >&2; }
fail() { printf '%serror:%s %s\n' "$red" "$reset" "$*" >&2; exit 1; }

cd "$(dirname "$0")"

# Shared by the remote scripts: health check with rollback.
REMOTE_LIB=$(cat <<'LIB'
say() { printf '    %s\n' "$*"; }
healthy() {
  for _ in $(seq 1 45); do
    curl -fs -m 2 http://127.0.0.1:8000/api/v1/health >/dev/null && break
    sleep 1
  done
  curl -fs -m 5 http://127.0.0.1:8000/api/v1/health >/dev/null || return 1
  sleep 3
  for s in hextrack-worker hextrack-bot; do
    if systemctl is-enabled -q "$s" 2>/dev/null && ! systemctl is-active -q "$s"; then
      echo "    $s is not running" >&2
      return 1
    fi
  done
}
restart() {
  sudo -n /usr/bin/systemctl restart hextrack-api hextrack-worker
  sudo -n /usr/bin/systemctl try-restart hextrack-bot
}
logs() { journalctl -u hextrack-api -u hextrack-worker -u hextrack-bot -u hextrack-migrate -n 30 --no-pager -o cat >&2; }
LIB
)

remote_status() {
  ssh -o BatchMode=yes "$HOST" bash -s <<'REMOTE'
set -uo pipefail
echo "release:  $(cat /opt/hextrack/current/BUILD 2>/dev/null || echo none) (previous: $(cat /opt/hextrack/previous/BUILD 2>/dev/null || echo none))"
for s in hextrack-api hextrack-worker hextrack-bot; do
  printf '%-16s %s\n' "$s:" "$(systemctl is-active "$s" 2>/dev/null)"
done
curl -fs -m 5 http://127.0.0.1:8000/api/v1/health | python3 -c '
import json, sys
d = json.load(sys.stdin)
p = d.get("poller") or {}
print("health:   {} | model {} | poller last ran {}".format(
    d["status"], d["model"]["version"], p.get("last_run_at") or "never"))
' || echo "health:   API not answering"
REMOTE
}

case "${1:-}" in
  --status) remote_status; exit ;;
  --logs) exec ssh -t "$HOST" 'journalctl -f -o cat -u hextrack-api -u hextrack-worker -u hextrack-bot' ;;
  --rollback)
    step "rolling back $HOST to the previous release"
    { printf '%s\n' 'set -euo pipefail' "$REMOTE_LIB"; cat <<'BODY'
sudo -n /usr/local/sbin/hextrack-install --rollback
restart
healthy || { logs; exit 1; }
say "healthy on $(cat /opt/hextrack/current/BUILD)"
BODY
    } | ssh -o BatchMode=yes "$HOST" bash -s
    exit ;;
  --force | --install-only | "") ;;
  -h | --help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit ;;
  *) fail "unknown option: $1 (see --help)" ;;
esac
MODE="${1:-}"

branch=$(git branch --show-current)
[ -n "$branch" ] || fail "not on a branch (detached HEAD)"
if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "you have uncommitted changes; commit them first (the Pi deploys what is on GitHub)"
fi
[ -z "$(git ls-files --others --exclude-standard)" ] || warn "untracked files are not deployed"

step "pushing $branch to GitHub"
git push -q origin "$branch"
sha=$(git rev-parse --short HEAD)

step "deploying $sha to $HOST"
{ printf '%s\n' 'set -euo pipefail' "$REMOTE_LIB"; cat <<'BODY'
branch=$1 sha=$2 mode=$3
repo=~/hextrack-v2                     # walker's build checkout (never run from)
stage_root=~/hextrack-staging
uv=~/.local/bin/uv
py=$(ls -d /opt/hextrack/python/cpython-3.12*/bin/python3.12 | head -1)

current=$(cat /opt/hextrack/current/BUILD 2>/dev/null || true)
if [ "$current" = "$sha" ] && [ "$mode" != --force ]; then
  say "already running $sha; nothing to do (use --force to rebuild and restart)"
  exit 0
fi

cd "$repo"
git fetch -q origin
git checkout -q "$branch"
git merge -q --ff-only "origin/$branch"
[ "$(git rev-parse --short HEAD)" = "$sha" ] || { echo "    GitHub has a different $branch than this Mac" >&2; exit 1; }

build=$sha
[ "$current" = "$sha" ] && build="$sha-$(date +%s)"     # --force redeploy of the same commit
stage="$stage_root/$build"
rm -rf "$stage"
mkdir -p "$stage"
chmod 0755 "$stage_root" "$stage"

say "source: git archive $sha"
git archive "$sha" api/src api/alembic api/alembic.ini | tar -x -C "$stage"
echo "$build" >"$stage/BUILD"

# Dependencies are keyed by uv.lock + interpreter, so most deploys reuse the installed venv.
venv_id=$( (cat api/uv.lock; echo "$py"; "$py" -VV) | sha256sum | cut -c1-24)
echo "$venv_id" >"$stage/VENV_ID"
if [ -d "/opt/hextrack/venvs/$venv_id" ]; then
  say "backend: dependencies unchanged ($venv_id)"
else
  say "backend: building dependencies ($venv_id)"
  "$uv" venv -q --relocatable --python "$py" "$stage/venv"
  (cd api && UV_PROJECT_ENVIRONMENT="$stage/venv" "$uv" sync -q --frozen --no-dev --no-install-project --compile-bytecode --python "$py")
fi

say "frontend: building"
cd web
lock_hash=$(sha256sum package-lock.json | cut -c1-16)
if [ "$(cat node_modules/.hextrack-lock 2>/dev/null)" != "$lock_hash" ]; then
  say "frontend: installing packages"
  npm ci --no-audit --no-fund --silent
  echo "$lock_hash" >node_modules/.hextrack-lock
fi
if ! npm run build --silent -- --outDir "$stage/web/dist" >"$stage_root/build.log" 2>&1; then
  echo "    frontend build failed:" >&2
  tail -40 "$stage_root/build.log" >&2
  exit 1
fi
cd ..

say "installing"
sudo -n /usr/local/sbin/hextrack-install "$stage"

say "migrating"
if ! sudo -n /usr/bin/systemctl start hextrack-migrate; then
  echo "    migration failed; switching back (nothing was restarted):" >&2
  logs
  sudo -n /usr/local/sbin/hextrack-install --rollback
  exit 1
fi

# Keep the three newest staging dirs.
ls -1dt "$stage_root"/*/ | tail -n +4 | xargs -r rm -rf

if [ "$mode" = --install-only ]; then
  say "installed $build (not restarted)"
  exit 0
fi

say "restarting services"
restart
if ! healthy; then
  echo "    the new release is unhealthy; rolling back:" >&2
  logs
  sudo -n /usr/local/sbin/hextrack-install --rollback
  restart
  healthy && echo "    back on $(cat /opt/hextrack/current/BUILD)" >&2
  exit 1
fi
say "services healthy"
BODY
} | ssh -o BatchMode=yes "$HOST" bash -s -- "$branch" "$sha" "$MODE"

[ "$MODE" = --install-only ] && exit 0
step "checking $PUBLIC_URL"
if curl -fs -m 15 "$PUBLIC_URL/api/v1/health" >/dev/null; then
  printf '%sdeployed %s%s  %s\n' "$green" "$sha" "$reset" "$PUBLIC_URL"
else
  fail "the Pi is healthy but $PUBLIC_URL is not answering (check Caddy on bloom and Tailscale)"
fi
