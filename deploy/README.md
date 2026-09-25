# Running HexTrack as the `hextrack` system user

HexTrack is internet-facing (bloom Caddy → Tailscale → rpi5:8000). These files move it from
walker's systemd **user** units (walker has passwordless sudo, so a HexTrack compromise was root)
to locked-down **system** units running as an unprivileged `hextrack` user.

## Layout after the change

| What | Where | Owner / mode |
|---|---|---|
| Releases (source + built web) | `/opt/hextrack/releases/<build>/`, `current` and `previous` symlinks | root:root 0755, read-only to hextrack |
| Python 3.12 interpreter | `/opt/hextrack/python/` (uv-managed, outside /home) | root:root |
| Dependency venvs, keyed by uv.lock | `/opt/hextrack/venvs/<id>/` (reused until uv.lock changes) | root:root |
| Settings (non-secret) | `/etc/hextrack/hextrack.env`, `/etc/hextrack/migrate.env` | root:hextrack(-migrate) 0640 |
| Secrets, one file each | `/etc/hextrack/credentials/{RIOT_API_KEY,HEXTRACK_ADMIN_TOKEN,DISCORD_TOKEN}` | root:root 0600, handed to each unit by `LoadCredential=` |
| Models (the only writable state) | `/var/lib/hextrack/artifacts/` | hextrack 0700, writable only in `hextrack-admin train/model` runs |
| Caches (torch, matplotlib) | `/var/cache/hextrack/` | hextrack 0700 |
| DB backups | `/var/backups/hextrack/` | root 0700 |

Units: `hextrack-api` (127.0.0.1:8000, unchanged, so `tailscale serve --tcp 8000` and bloom keep
working), `hextrack-worker`, `hextrack-bot`, and the one-shot `hextrack-migrate`. All share the
hardening drop-in `hextrack-.service.d/10-hardening.conf`, which also applies to the transient
`hextrack-admin-*` runs.

## Design decisions

- **One `hextrack` user for api/worker/bot (as asked), secrets per unit.** Each unit gets only the
  secrets it uses (bot: Discord token only; worker: Riot key only; api: Riot key + admin
  token), and the files are root-only on disk. Limit: this kernel has no Yama LSM, so a
  process running as `hextrack` can still read another `hextrack` process's memory. The
  boundary this change guarantees is **hextrack vs. walker / root / Baron**, not api vs. bot.
  Separate users per service would close that gap, at the cost of three DB mappings and shared
  state permissions. That could be a later step.
- **Postgres: two roles, peer auth over the Unix socket, no passwords.**
  - `hextrack_app` (new) is what the services use. It can read and write rows only (no DDL,
    no ownership), and new tables get the same grants through `ALTER DEFAULT PRIVILEGES`.
  - `hextrack_v2` (the existing owner) is used only by `hextrack-migrate.service`, which runs
    as its own OS user `hextrack-migrate`. A compromised service therefore can't drop or alter
    tables, only change rows.
  - `pg_ident` maps each OS user to exactly one role.
- **The venv is built unprivileged.** walker builds it in staging (`uv venv --relocatable`,
  `--no-install-project`), and the package itself runs from the release's `api/src` via
  `PYTHONPATH` (`python -m hextrack`). No package build code ever runs as root.
- **The install helper treats walker's staging as hostile.** `hextrack-install` is Python
  (`/usr/bin/python3 -I`). It reads the tree as walker, then checks every archive member before
  unpacking: no absolute or `..` paths, no hard links or devices, symlinks only inside `venv/`
  (or pointing at `/opt/hextrack/python`), and nothing below a symlink. Tested against 13
  hostile and valid archives. It then makes everything root-owned 0755/0644 and swaps
  `current` atomically.
- **Maintenance commands stay possible without root:** `sudo hextrack-admin train|model|backfill|roster ...`
  runs the CLI as `hextrack`, inside the same sandbox.
- **Logs need no sudo:** walker is in `adm`, which can read the system journal.
- **Linger stays on for walker:** other user units (amity bot/tunnel, homelab, rpi-connect) need it.

## Phase 0: review (nothing on the Pi changes)

Files: `systemd/`, `postgres/`, `hextrack-install`, `hextrack-admin`, `sudoers.hextrack`,
`root-setup.sh`, the new `../deploy.sh`, and two small app changes: `hextrack/__main__.py`
(`python -m hextrack`) and `config.py` (reads `$CREDENTIALS_DIRECTORY`). These are backward
compatible: the old user units keep working with them.

## Phase 1: prepare (no downtime; old units keep serving)

```bash
# Mac: commit, then push only (the new deploy.sh must not run yet)
git push origin main
# Pi:
ssh rpi5 'cd ~/hextrack-v2 && git pull --ff-only && systemd-analyze security --user hextrack-api | tail -1'
ssh -t rpi5 'cd ~/hextrack-v2 && sudo bash deploy/root-setup.sh'
```

`root-setup.sh`:
1. Dumps the DB to `/var/backups/hextrack/`.
2. Creates the `hextrack` and `hextrack-migrate` users (system users: no shell, no home, no groups).
3. Creates the directories.
4. Installs Python into `/opt/hextrack/python`.
5. Installs the two helpers and the sudoers file (checked with `visudo`).
6. Installs the units without enabling them.
7. Adds the Postgres roles and the peer-auth lines (backs up `pg_hba`/`pg_ident` first).
8. Copies the secrets into `/etc/hextrack` without printing them. walker's `.env` stays in place for rollback.
9. Copies the models to `/var/lib/hextrack`.
10. Checks that each OS user can reach the right DB role and that `hextrack_app` cannot create tables.

## Phase 2: first install and smoke tests (no downtime)

```bash
./deploy.sh --install-only        # build as walker, hextrack-install, hextrack-migrate; no restart
```

Smoke-test the new API on port 8001, next to the old one:

```bash
ssh rpi5 'sudo systemd-run --unit=hextrack-smoke --service-type=exec -p User=hextrack -p Group=hextrack \
  -p EnvironmentFile=/etc/hextrack/hextrack.env -p CacheDirectory=hextrack \
  -p LoadCredential=RIOT_API_KEY:/etc/hextrack/credentials/RIOT_API_KEY \
  /opt/hextrack/current/venv/bin/python -m hextrack serve --host 127.0.0.1 --port 8001 \
  && sleep 8 && curl -fsS http://127.0.0.1:8001/api/v1/health; echo; sudo systemctl stop hextrack-smoke'
```

`MemoryDenyWriteExecute` test: run the same command with `-p MemoryDenyWriteExecute=yes` and
fetch one AI explanation (this runs torch). Only if that works does MDWE get enabled in the
api/worker units. For the bot, check that its imports load under MDWE (it must not connect: a
second bot would double-post):

```bash
ssh rpi5 'sudo systemd-run --unit=hextrack-mdwe --wait --pipe --collect -p User=hextrack -p MemoryDenyWriteExecute=yes \
  /opt/hextrack/current/venv/bin/python -c "import discord, hextrack.bot.client; print(\"bot imports ok\")"'
```

## Phase 3: cutover (about 10–20 s of downtime)

```bash
ssh rpi5 'systemctl --user disable --now hextrack-api hextrack-worker hextrack-bot \
  && sudo systemctl enable --now hextrack-api hextrack-worker hextrack-bot \
  && sleep 10 && curl -fsS http://127.0.0.1:8000/api/v1/health'
curl -fsS https://hextrack.slabby.dev/api/v1/health
```

The old user unit files stay in `~/.config/systemd/user/` (disabled) until Phase 5.

## Phase 4: verify

```bash
ssh rpi5 'ps -o user=,args= -C python3,python,python3.12 | grep -i hextrack'   # all "hextrack", none "walker"
ssh rpi5 'sudo -u hextrack sudo -n true; echo "exit $?"'                         # must fail
ssh rpi5 'sudo -u hextrack ls /etc/hextrack/credentials /srv/nfs /home/walker; echo "exit $?"'  # must fail
ssh rpi5 'sudo systemd-run --wait --pipe --collect --unit=hextrack-probe -p User=hextrack ls /srv/nfs /home /etc/hextrack/credentials; echo "exit $?"'  # inside the sandbox
ssh rpi5 'curl -fsS http://127.0.0.1:8000/api/v1/health'; curl -fsS https://hextrack.slabby.dev/api/v1/health
ssh rpi5 'journalctl -u hextrack-worker -u hextrack-bot --since -10min -o cat | tail -30'   # poller ran, bot logged in
ssh rpi5 'systemd-analyze security hextrack-api | tail -1'                       # before: 9.8 UNSAFE
./deploy.sh --status
```

Also check `sudo -u hextrack ls /run/baron /etc/baron`. Those paths don't exist yet on the
Pi; they are blocked in the units in advance (`InaccessiblePaths=-...`).

**Plain `sudo -u hextrack` runs outside the sandbox.** The services can't see `/srv/nfs`
(`InaccessiblePaths`), but the `hextrack` user itself could still list it, because it is
0777. To make it fail for the user too, without changing access for anyone else, add an
ACL entry denying that one user (optional; needs your OK because it touches `/srv/nfs`):

```bash
ssh rpi5 'sudo setfacl -m u:hextrack:--- /srv/nfs && sudo -u hextrack ls /srv/nfs; echo "exit $?"'
```

## Rollback (any time before Phase 5)

```bash
ssh rpi5 'sudo systemctl disable --now hextrack-api hextrack-worker hextrack-bot \
  && systemctl --user enable --now hextrack-api hextrack-worker hextrack-bot'
```

The old code in `~/hextrack-v2`, its `.env` and the `hextrack_v2` password login are all
untouched until Phase 5. The old deploy.sh is in git history if needed. DB restore, if a
migration ever went wrong:
`sudo -u postgres pg_restore --clean -d hextrack_v2 /var/backups/hextrack/<dump>`.

## Phase 5: cleanup (after a few days of normal running)

```bash
ssh rpi5 'rm ~/.config/systemd/user/hextrack-{api,worker,bot}.service && systemctl --user daemon-reload'
ssh rpi5 'shred -u ~/hextrack-v2/.env && rm -rf ~/hextrack-v2/api/.venv ~/hextrack-v2/api/artifacts'
ssh rpi5 'sudo -u postgres psql -c "ALTER ROLE hextrack_v2 PASSWORD NULL"'   # socket-only from now on
```

## Decided (2026-09-24)

- **Postgres stays reachable over the network** (`listen_addresses='*'`) as before; HexTrack
  itself now uses only the Unix socket.
- **walker keeps passwordless sudo.** `sudoers.hextrack` is installed anyway so deploys only use
  the narrow commands, and nothing breaks if the blanket rule is ever removed.
- **`/srv/nfs`:** an ACL entry denies the `hextrack` user only (`setfacl -m u:hextrack:--- /srv/nfs`);
  everyone else's access is unchanged. The services are also blocked by `InaccessiblePaths`.
- `/srv/nfs` itself stays 0777.
