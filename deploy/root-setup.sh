#!/bin/bash
# One-time (idempotent) root setup for running HexTrack as the locked-down `hextrack` user.
#
#   sudo bash deploy/root-setup.sh        (on rpi5, from ~/hextrack-v2 at the commit to install)
#
# It prepares everything but starts nothing: no service is enabled or restarted, the old
# walker user units keep running, and walker's .env is left in place (copied, not moved) so
# the cutover can be rolled back. Secret values are never printed.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C
umask 022

[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
[ "$(hostname)" = rpi5 ] || { echo "this is for rpi5" >&2; exit 1; }
cd "$(dirname "$0")"
SRC=$PWD                                   # the deploy/ folder of walker's checkout
OLD_ENV=/home/walker/hextrack-v2/.env
OLD_ARTIFACTS=/home/walker/hextrack-v2/api/artifacts
PY_VERSION=3.12.14
PG=/etc/postgresql/15/main
step() { printf '==> %s\n' "$*"; }

for p in /opt/hextrack /etc/hextrack /var/lib/hextrack /var/backups/hextrack; do
  case "$(realpath -m "$p")" in /srv/nfs | /srv/nfs/*) echo "refusing: $p is under /srv/nfs" >&2; exit 1 ;; esac
done

step "backing up the database"
install -d -o root -g root -m 0700 /var/backups/hextrack
dump=/var/backups/hextrack/hextrack_v2-$(date +%Y%m%d-%H%M%S).dump
runuser -u postgres -- pg_dump -Fc hextrack_v2 >"$dump"
chmod 0600 "$dump"
echo "    $dump ($(du -h "$dump" | cut -f1))"

step "system users"
for u in hextrack hextrack-migrate; do
  getent passwd "$u" >/dev/null ||
    adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin "$u"
done
for g in sudo docker adm; do
  for u in hextrack hextrack-migrate; do
    if id -nG "$u" | tr ' ' '\n' | grep -qx "$g"; then echo "$u must not be in $g" >&2; exit 1; fi
  done
done

step "directories"
install -d -o root -g root -m 0755 /opt/hextrack /opt/hextrack/releases /opt/hextrack/venvs /opt/hextrack/python
install -d -o root -g hextrack -m 0750 /etc/hextrack
install -d -o root -g root -m 0700 /etc/hextrack/credentials
install -d -o hextrack -g hextrack -m 0700 /var/lib/hextrack /var/cache/hextrack

step "Python $PY_VERSION in /opt/hextrack/python"
install -o root -g root -m 0755 /home/walker/.local/bin/uv /usr/local/bin/uv
UV_PYTHON_INSTALL_DIR=/opt/hextrack/python UV_CACHE_DIR=/var/cache/uv-root \
  /usr/local/bin/uv python install --quiet "$PY_VERSION"
chown -R root:root /opt/hextrack/python
chmod -R go-w /opt/hextrack/python
ls -d /opt/hextrack/python/cpython-*/bin/python3.12

step "helpers and sudoers"
install -o root -g root -m 0755 "$SRC/hextrack-install" /usr/local/sbin/hextrack-install
install -o root -g root -m 0755 "$SRC/hextrack-admin" /usr/local/sbin/hextrack-admin
visudo -cqf "$SRC/sudoers.hextrack"
install -o root -g root -m 0440 "$SRC/sudoers.hextrack" /etc/sudoers.d/.hextrack.tmp   # ignored while named with a "."
visudo -cqf /etc/sudoers.d/.hextrack.tmp
mv /etc/sudoers.d/.hextrack.tmp /etc/sudoers.d/hextrack
visudo -cq

step "systemd units (installed, not enabled)"
install -o root -g root -m 0644 "$SRC"/systemd/hextrack-{api,worker,bot,migrate}.service /etc/systemd/system/
install -d -o root -g root -m 0755 /etc/systemd/system/hextrack-.service.d
install -o root -g root -m 0644 "$SRC/systemd/hextrack-.service.d/10-hardening.conf" /etc/systemd/system/hextrack-.service.d/
systemctl daemon-reload

step "Postgres roles and peer auth"
cp -n "$PG/pg_hba.conf" "$PG/pg_hba.conf.pre-hextrack"
cp -n "$PG/pg_ident.conf" "$PG/pg_ident.conf.pre-hextrack"
grep -q '^hextrack[[:space:]]\+hextrack[[:space:]]' "$PG/pg_ident.conf" ||
  grep -v '^#' "$SRC/postgres/pg_ident.conf.snippet" >>"$PG/pg_ident.conf"
if ! grep -q 'map=hextrack' "$PG/pg_hba.conf"; then
  line=$(grep -v '^#' "$SRC/postgres/pg_hba.conf.snippet" | grep .)
  awk -v add="$line" '{ print } !done && /^local[[:space:]]+all[[:space:]]+postgres[[:space:]]/ { print add; done = 1 }' \
    "$PG/pg_hba.conf" >"$PG/pg_hba.conf.new"
  grep -q 'map=hextrack' "$PG/pg_hba.conf.new" || { echo "could not place the pg_hba line" >&2; exit 1; }
  chown postgres:postgres "$PG/pg_hba.conf.new"; chmod 0640 "$PG/pg_hba.conf.new"
  mv "$PG/pg_hba.conf.new" "$PG/pg_hba.conf"
fi
runuser -u postgres -- psql -X -q -v ON_ERROR_STOP=1 -f "$SRC/postgres/roles.sql"
systemctl reload postgresql

step "config and secrets in /etc/hextrack (names only)"
# Parse walker's .env as root and write: non-secret settings to hextrack.env, each secret to
# its own root-only credential file (systemd LoadCredential= hands them to the right unit).
python3 -I - "$OLD_ENV" <<'PY'
import os, re, sys
src = sys.argv[1]
values = {}
for line in open(src, encoding="utf-8"):
    m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
    if not m or line.lstrip().startswith("#"):
        continue
    key, val = m.groups()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
        val = val[1:-1]
    values[key] = val

SECRETS = ("RIOT_API_KEY", "HEXTRACK_ADMIN_TOKEN", "DISCORD_TOKEN")
PLAIN = ("HEXTRACK_PUBLIC_URL", "DISCORD_BROADCAST_CHANNEL_ID")
for key in SECRETS:
    if not values.get(key):
        sys.exit(f"{key} missing from {src}")
    path = f"/etc/hextrack/credentials/{key}"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(values[key] + "\n")
    print(f"    credential {key}")

env = [
    "# HexTrack service settings (non-secret). Secrets are in /etc/hextrack/credentials/.",
    "DATABASE_URL=postgresql+asyncpg://hextrack_app@/hextrack_v2?host=/run/postgresql",
    "HEXTRACK_MODEL_DIR=/var/lib/hextrack/artifacts",
] + [f"{k}={values[k]}" for k in PLAIN if values.get(k)]
with open("/etc/hextrack/hextrack.env", "w") as f:
    f.write("\n".join(env) + "\n")
with open("/etc/hextrack/migrate.env", "w") as f:
    f.write("DATABASE_URL=postgresql+asyncpg://hextrack_v2@/hextrack_v2?host=/run/postgresql\n")
print("    hextrack.env: " + ", ".join(line.split("=")[0] for line in env[1:]))
PY
chown root:hextrack /etc/hextrack/hextrack.env && chmod 0640 /etc/hextrack/hextrack.env
chown root:hextrack-migrate /etc/hextrack/migrate.env && chmod 0640 /etc/hextrack/migrate.env
chown -R root:root /etc/hextrack/credentials && chmod 0600 /etc/hextrack/credentials/*

step "model artifacts -> /var/lib/hextrack/artifacts"
if [ ! -d /var/lib/hextrack/artifacts ]; then
  cp -a "$OLD_ARTIFACTS" /var/lib/hextrack/artifacts
  chown -R hextrack:hextrack /var/lib/hextrack/artifacts
  chmod -R u=rwX,go= /var/lib/hextrack/artifacts
fi
echo "    active model: $(cat /var/lib/hextrack/artifacts/ACTIVE 2>/dev/null || echo none)"

step "checks"
runuser -u hextrack -- psql -X -At -h /run/postgresql -U hextrack_app -d hextrack_v2 -c 'select count(*) from matches' >/dev/null &&
  echo "    hextrack -> hextrack_app: ok"
runuser -u hextrack-migrate -- psql -X -At -h /run/postgresql -U hextrack_v2 -d hextrack_v2 -c 'select 1' >/dev/null &&
  echo "    hextrack-migrate -> hextrack_v2: ok"
if runuser -u hextrack -- psql -X -At -h /run/postgresql -U hextrack_app -d hextrack_v2 -c 'create table _x(i int)' 2>/dev/null; then
  echo "hextrack_app can create tables; check roles.sql" >&2; exit 1
fi
echo "    hextrack_app cannot change the schema: ok"
echo "done. Next: ./deploy.sh --install-only from the Mac (see deploy/README.md)."
