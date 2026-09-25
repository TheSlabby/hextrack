# CLAUDE.md

HexTrack: an op.gg-style League of Legends stats site for a group of friends, with an
"AI Score" on every game. Live at https://hextrack.slabby.dev. Monorepo with a FastAPI
backend (`api/`) and a Vite + React frontend (`web/`). See README.md for the user-facing
overview and web/DESIGN.md for the frontend design system.

## Rules that matter most

- **Never read, print or grep `.env` files** (repo root, `api/.env`, or on the servers).
  They hold the Riot API key, Discord token and admin token. Listing variable *names*
  with values stripped is fine when needed. Use `.env.example` to learn settings.
- **Production runs on the Pi, and its database is the live one.** Don't run
  `hextrack worker` or `hextrack bot` on the Mac against the real keys: a second poller
  splits the Riot key's rate budget and writes to a stale database, and a second bot
  connects as the same Discord app and double-posts. Local dev uses `make api` (API with
  an in-process poller) against the local database only when nothing else is polling.
- **The Discord bot posts to the user's real channel.** Ask before anything that would
  make it post (starting another instance, inserting `bot_events` rows, changing
  `last_post_date` in `app_state["bot_daily"]`).
- Ship changes with `./deploy.sh` (below). Commit first; the Pi deploys what is on GitHub.
- **Production runs as the `hextrack` user** (see Deployment). Don't run HexTrack as walker on
  the Pi or restart the old walker user units; they're disabled.
- Git: commit only when asked; git has no global identity on this Mac, so pass
  `-c user.name="Walker McGilvary" -c user.email="walker.mcgilvary@gmail.com"`.

## Layout

```
api/src/hextrack/
  config.py        pydantic-settings Settings (env + repo-root .env + api/.env)
  main.py          create_app(): lifespan builds engine, RiotClient, DDragon, Scorer;
                   serves web/dist with SPA fallback; hot-reloads the AI model
  cli.py           typer CLI `hextrack` (serve, worker, bot, train, backfill, model,
                   roster, import-legacy, seed-demo, clear-demo, openapi, db)
  db/              models.py (SQLAlchemy 2 typed), engine.py, repo/ (write-side helpers)
  riot/            client.py (httpx, X-Riot-Token), ratelimit.py, routing.py,
                   schemas.py (DTOs), errors.py, ddragon.py (versions + icon URLs)
  ingest/          mapping.py (match-v5 JSON -> rows; rejects error bodies),
                   service.py (refresh_summoner, discover, ingest_match), poller.py,
                   ondemand.py (Update button / first lookup), backfill.py, roster.py,
                   events.py (bot outbox)
  hextrack_ai/     features.py, model.py, train.py, inference.py (Scorer),
                   explain.py (attributions), registry.py (activate, rescore)
  api/             schemas.py (THE response contract), deps.py, v1/* routes
  stats/           read-side SQL: queries.py, aggregate.py, metrics.py, present.py
  bot/             discord.py bot: client.py, consumer.py (outbox), embeds.py, queries.py
  demo/            deterministic fake data (DEMO_ match ids, demo- puuids)
  legacy_import.py import from the v1 LPBot SQLite / old Postgres
  rank.py riotid.py queues.py   shared helpers (rank_value, Riot ID parsing, queue labels)
api/alembic/       migrations (0001 initial, 0002 watermark/Arena/remakes)
api/tests/         pytest; conftest.py creates a throwaway DB per session
web/src/
  api/             openapi.json + schema.d.ts (GENERATED, committed), client.ts, queries.ts
  lib/             riotId, ddragon, format, score, tiers, queues, motion, chartTheme ...
  components/      common/ (shared UI), ui/ (shadcn, restyled), home/, leaderboard/,
                   summoner/, match/, ai/, search/, layout/, charts/
  routes/          home, leaderboard, summoner, match; router.tsx (TanStack Router)
deploy.sh          ship to the Pi
```

## Commands

Local dev (macOS; Postgres 16 from Homebrew, no Docker needed):

```bash
make db-start          # needs LC_ALL=en_US.UTF-8, the Makefile sets it
make migrate
make api               # uvicorn on :8000 with in-process poller + reload
make web               # Vite on :5173, proxies /api to :8000
```

Checks (run all before calling backend or frontend work done):

```bash
cd api && uv run ruff check . && uv run ruff format --check . && uv run pytest -q
cd web && npm run typecheck && npm run lint && npm run build
```

- Python is 3.12 via `uv` only. Never use the system `python3` (3.9 on the Mac, 3.11 on the Pi).
- Tests create and drop a unique `hextrack_test_<hex>` database per session, so they are
  safe to run anywhere Postgres is up; they never touch the dev database.
- Local DB URL: `postgresql://hextrack:hextrack@localhost:5432/hextrack`.

## Contracts you must keep

- **API contract:** `api/src/hextrack/api/schemas.py` defines every response. After changing
  it, regenerate and commit the client: `make gen-api` (writes `web/src/api/openapi.json` and
  `schema.d.ts`). Prefer additive changes; the frontend is typed against these names.
- **Migrations:** any model change needs an Alembic migration
  (`cd api && uv run alembic revision --autogenerate -m "..."`, then review it by hand).
  `uv run alembic check` must report no drift. Deploys run `hextrack db upgrade`.
- **Ingest transactions:** functions in `ingest/service.py` take a session and never commit;
  callers own the transaction (the poller commits per match). Riot calls happen before writes.
- **Nothing from Riot is stored unless it is a 200 that validates** (`ingest/mapping.py`).
  That is what prevents the v1 "corrupt match" rows.
- **Match discovery** is anchored on `summoners.synced_through`: every ranked game below it
  is stored. Listings run from the watermark (or season start) to now and never stop early at
  a stored id (that lost games in half-filled gaps). `hextrack backfill` resets the watermark
  and re-lists a roster from a date.
- **AI features:** `hextrack_ai/features.py` `FEATURE_NAMES` order is the model's input
  contract (30 features). Changing it means retraining; `Scorer.load` refuses artifacts whose
  `meta.json` feature list differs.
- **Riot client:** key only in the `X-Riot-Token` header, path segments URL-quoted, errors
  mapped to `riot/errors.py` types. The API process has its own small on-demand budget
  (`RIOT_ONDEMAND_RATE_LIMITS`) and fails fast; the worker queues on the limiter.

## Domain notes

- **AI Score** = the model's probability that a participant's stat line is on the winning
  team, 0 to 100. It is strongly tied to the result (scores cluster near 0 and 100; wins
  average ~80, losses ~21), so UI copy must not call it a skill or "carry" rating. Averages
  are shown as plain numbers, not grades. Averages only use rows scored by the active model.
- **Season** starts at `HEXTRACK_SEASON_START` (default 2026-01-08T20:00Z). Rank snapshots
  from before it, or older than the heartbeat window, are not shown as the current rank.
- **Rank snapshots** are change-only plus a 24 h heartbeat; `rank.rank_value` handles
  Master+ (no divisions). LP delta = latest solo value minus first value this season.
- **Best ally** = most frequent same-team co-participant who is also tracked.
- **Remake** = game under 300 s; stored but not scored.
- **Bot events** go through the `bot_events` outbox. Events older than 6 h are skipped when
  the bot starts; tier events are only created when the previous snapshot is fresh (48 h),
  so long gaps or imports never announce old promotions. `new_match` is consumed silently;
  bad-game posts are off unless `HEXTRACK_BAD_GAME_EMBEDS=true`.
- **Riot IDs** in URLs are `/summoner/na/<GameName>-<TAG>`, split on the LAST `-`
  (`web/src/lib/riotId.ts`, `api/src/hextrack/riotid.py`).
- Demo data uses `DEMO_` match ids and `demo-` puuids; `hextrack clear-demo` removes it.

## Frontend

- Follow web/DESIGN.md: dark "Hextech night" tokens in `src/index.css`, shared components
  in `components/common`, motion timings in `lib/motion.ts` (everything settles within
  ~600 ms, respects reduced motion), charts via `lib/chartTheme.ts`.
- Data comes only through the hooks in `src/api/queries.ts`; types from `src/api/types.ts`.
- Item and champion icons resolve against the game's own patch (`lib/ddragon.ts`), because
  old matches contain removed items.

## Deployment (live)

```
browser ─https─▶ bloom (VPS, Caddy: hextrack.slabby.dev) ─tailscale─▶ rpi5 :8000
                                                            (API + web/dist, worker, bot, Postgres)
```

- **rpi5** (`ssh rpi5`, Debian 12 arm64, 8 GB): HexTrack runs as the unprivileged system user
  `hextrack` (no shell, no sudo) in hardened **system** units `hextrack-api` (127.0.0.1:8000),
  `hextrack-worker`, `hextrack-bot`, plus the one-shot `hextrack-migrate` (runs as
  `hextrack-migrate`). Layout, design and runbook: `deploy/README.md`.
  - Releases in `/opt/hextrack/releases/<build>` (root-owned, read-only to the service),
    `current`/`previous` symlinks; venvs in `/opt/hextrack/venvs/<uv.lock hash>`; Python in
    `/opt/hextrack/python`. `~/hextrack-v2` is only walker's build checkout; nothing runs from it.
  - Settings in `/etc/hextrack/hextrack.env`; secrets one file each in
    `/etc/hextrack/credentials/` (root 0600, `LoadCredential=`). Don't print them.
  - Models in `/var/lib/hextrack/artifacts/<version>/` (active one named in `ACTIVE`).
  - Database `hextrack_v2` in the Pi's Postgres 15, peer auth over the Unix socket, no
    passwords: the services use role `hextrack_app` (rows only), migrations use the owner
    `hextrack_v2`. DB dumps in `/var/backups/hextrack/`.
  - Exposed only via `tailscale serve --tcp 8000` (tailnet only; not on the LAN).
  - Don't touch anything Baron (`/opt/baron`, `/etc/baron`, ...), which also runs on this Pi.
- **bloom** (`ssh bloom`, Ubuntu 24.04 VPS, 1 CPU / 3.7 GB, runs a Minecraft server and the
  Amity Next.js site on mc.slabby.dev): Caddy's `/etc/caddy/Caddyfile` has a
  `hextrack.slabby.dev` block that reverse-proxies to `100.127.88.92:8000`. UFW allows only
  22, 25565, 80, 443. Memory is tight there: never run HexTrack processes on bloom.
- **Tailscale:** tailnet `tail2746ae.ts.net`. rpi5 = `tag:hextrack` (100.127.88.92), bloom =
  `tag:proxy` (100.124.49.81), both with `--accept-dns=false`. Policy: the user's own devices
  reach everything; `tag:proxy` may reach only `tag:hextrack` on tcp:8000.
- **DNS:** Namecheap; `hextrack` A record -> 208.92.232.87 (bloom).

Day to day:

```bash
./deploy.sh              # push; Pi builds unprivileged, installs, migrates, restarts, health check (rolls back on failure)
./deploy.sh --status     # release, services, health on the Pi
./deploy.sh --logs       # follow journald for all three services
./deploy.sh --rollback   # back to the previous release
ssh rpi5 'sudo hextrack-admin train --activate'   # retrain on live data (runs as hextrack, sandboxed)
ssh rpi5 'sudo systemctl stop hextrack-worker && sudo hextrack-admin backfill; sudo systemctl start hextrack-worker'
```

Training is manual (suggested monthly or after a few hundred new games). Activation rescores
stored games; the API (every 30 s) and worker (every poll) pick up the new model without a
restart. Roll back with `sudo hextrack-admin model activate <version>` (`... model list`).
walker's sudo rules for HexTrack are in `deploy/sudoers.hextrack` (walker also still has
blanket passwordless sudo, by choice).

## History

v1 was a Next.js app (tag `legacy-nextjs`), a separate PyTorch repo (TheSlabby/hextrack-ai)
and a C++ Discord bot (TheSlabby/LPBot); both repos are archived. Their data was imported
from the Pi; local copies live outside the repo in `~/Developer/LoL/legacy-data/`. The Pi's
old folders are in `~/archive/hextrack-v1-2026-09-22/`.
