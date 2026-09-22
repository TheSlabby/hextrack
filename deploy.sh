#!/usr/bin/env bash
# Deploy HexTrack to the Pi.
#
#   ./deploy.sh            push the current branch, then pull, build, migrate and restart on the Pi
#   ./deploy.sh --force    same, but rebuild the frontend and restart even if nothing changed
#   ./deploy.sh --status   show what the Pi is running
#   ./deploy.sh --logs     follow the Pi's HexTrack logs (Ctrl-C to stop)
#
# Only committed code is deployed: the Pi pulls from GitHub. Secrets (.env), the database and
# the trained model (api/artifacts) live on the Pi and are never touched by a deploy.
#
# Overrides: DEPLOY_HOST (default rpi5), DEPLOY_DIR (default hextrack-v2, relative to the Pi's
# home), DEPLOY_PUBLIC_URL (default https://hextrack.slabby.dev).
set -euo pipefail

HOST="${DEPLOY_HOST:-rpi5}"
DIR="${DEPLOY_DIR:-hextrack-v2}"
PUBLIC_URL="${DEPLOY_PUBLIC_URL:-https://hextrack.slabby.dev}"

bold=$'\033[1m' green=$'\033[32m' yellow=$'\033[33m' red=$'\033[31m' reset=$'\033[0m'
step() { printf '%s==>%s %s\n' "$bold" "$reset" "$*"; }
warn() { printf '%swarning:%s %s\n' "$yellow" "$reset" "$*" >&2; }
fail() { printf '%serror:%s %s\n' "$red" "$reset" "$*" >&2; exit 1; }

cd "$(dirname "$0")"

remote_status() {
  ssh -o BatchMode=yes "$HOST" bash -s -- "$DIR" <<'REMOTE'
set -uo pipefail
cd ~/"$1" || exit 1
echo "commit:   $(git log -1 --format='%h %s (%cr)') on $(git branch --show-current)"
for s in hextrack-api hextrack-worker hextrack-bot; do
  printf '%-16s %s\n' "$s:" "$(systemctl --user is-active "$s" 2>/dev/null)"
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
  --logs) exec ssh -t "$HOST" 'journalctl --user -f -o cat -u hextrack-api -u hextrack-worker -u hextrack-bot' ;;
  --force | "") ;;
  -h | --help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit ;;
  *) fail "unknown option: $1 (see --help)" ;;
esac
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

branch=$(git branch --show-current)
[ -n "$branch" ] || fail "not on a branch (detached HEAD)"
if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "you have uncommitted changes; commit them first (the Pi deploys what is on GitHub)"
fi
[ -z "$(git ls-files --others --exclude-standard)" ] || warn "untracked files are not deployed"

step "pushing $branch to GitHub"
git push -q origin "$branch"
sha=$(git rev-parse --short HEAD)

step "deploying $sha to $HOST:~/$DIR"
ssh -o BatchMode=yes "$HOST" bash -s -- "$DIR" "$branch" "$FORCE" <<'REMOTE'
set -euo pipefail
dir=$1 branch=$2 force=$3
root=~/"$dir"
cd "$root"
say() { printf '    %s\n' "$*"; }

old=$(git rev-parse HEAD)
git fetch -q origin
git checkout -q "$branch"
git merge -q --ff-only "origin/$branch"
new=$(git rev-parse HEAD)

if [ "$old" = "$new" ] && [ "$force" != 1 ]; then
  say "already at $(git log -1 --format='%h %s'); nothing to do (use --force to rebuild and restart)"
  exit 0
fi
[ "$old" = "$new" ] || say "$(git log --oneline "$old..$new" | wc -l | tr -d ' ') new commit(s): ${old:0:7} -> ${new:0:7}"

# True when anything under the given paths changed in this deploy (always true with --force).
changed() {
  [ "$force" = 1 ] && return 0
  ! git -C "$root" diff --quiet "$old" "$new" -- "$@"
}

say "backend: syncing Python dependencies"
(cd api && ~/.local/bin/uv sync --frozen --no-dev -q)

say "database: applying migrations"
(cd api && .venv/bin/hextrack db upgrade 2>&1 | tail -1 | sed 's/^/    /')

if [ ! -f web/dist/index.html ] || changed web; then
  cd web
  if [ ! -d node_modules ] || changed web/package.json web/package-lock.json; then
    say "frontend: installing packages"
    npm ci --no-audit --no-fund --silent
  fi
  say "frontend: building"
  rm -rf dist.new
  npm run build --silent -- --outDir dist.new >/dev/null
  # Swap the finished build in, so the site never serves a half-written dist/.
  rm -rf dist.old
  [ -d dist ] && mv dist dist.old
  mv dist.new dist
  rm -rf dist.old
  cd ..
else
  say "frontend: unchanged, skipping build"
fi

say "restarting services"
systemctl --user restart hextrack-api hextrack-worker
systemctl --user try-restart hextrack-bot

for _ in $(seq 1 45); do
  curl -fs -m 2 http://127.0.0.1:8000/api/v1/health >/dev/null && break
  sleep 1
done
if ! curl -fs -m 5 http://127.0.0.1:8000/api/v1/health >/dev/null; then
  echo "    API did not come back; last log lines:" >&2
  journalctl --user -u hextrack-api -n 25 --no-pager -o cat >&2
  exit 1
fi
for s in hextrack-worker hextrack-bot; do
  if systemctl --user is-enabled -q "$s" 2>/dev/null && ! systemctl --user is-active -q "$s"; then
    echo "    $s failed to start; last log lines:" >&2
    journalctl --user -u "$s" -n 25 --no-pager -o cat >&2
    exit 1
  fi
done
say "services healthy"
REMOTE

step "checking $PUBLIC_URL"
if curl -fs -m 15 "$PUBLIC_URL/api/v1/health" >/dev/null; then
  printf '%sdeployed %s%s  %s\n' "$green" "$sha" "$reset" "$PUBLIC_URL"
else
  fail "the Pi is healthy but $PUBLIC_URL is not answering (check Caddy on bloom and Tailscale)"
fi
