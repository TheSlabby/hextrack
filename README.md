# HexTrack

League of Legends stats for you and your friends, with an **AI Score** on every game: a
small neural network's read on how often a stat line like yours wins.

Tracked friends are polled continuously (match history, rank, LP). Anyone else can be
looked up on demand, op.gg style. The same data drives a Discord bot that announces rank
changes and stand-out games.

## Layout

```
api/   FastAPI + SQLAlchemy/Alembic + Postgres, the Riot poller, the AI Score model
       (PyTorch), and the Discord bot. One package, several entry points.
web/   Vite + React + TypeScript single-page app (Tailwind, shadcn/ui, TanStack Query
       and Router, Recharts). Built to static files that the API can serve.
```

The v1 Next.js app lives on in git history under the `legacy-nextjs` tag, together with
the two repositories this replaced: `hextrack-ai` (the model) and `LPBot` (a C++ Discord
bot that shelled out to Python for every score).

## Requirements

Python 3.12 via [uv], Node 20+, and PostgreSQL 16. Docker is optional: `docker-compose.yml`
runs just the database.

## Getting started

```bash
cp .env.example .env          # fill in RIOT_API_KEY at least
make db-start                 # or: docker compose up -d postgres
make migrate
make seed                     # demo players and games, no Riot key needed
make api                      # http://localhost:8000  (API + in-process poller)
make web                      # http://localhost:5173  (dev server, proxies /api)
```

`make help` lists every target. Without a Riot key the demo data still gives you a full
site; player lookups and the poller need one.

## Real data

```bash
uv run hextrack roster add "Name#TAG"     # track a friend
uv run hextrack backfill                  # one-off: catch the roster up to Riot
uv run hextrack import-legacy --sqlite path/to/database.sqlite --players players.txt
uv run hextrack clear-demo                # drop demo data once real games are in
```

`import-legacy` also reads the v1 app's Postgres database with `--neon-url`. Both sources
go through the same ingestion path as live matches, and both are idempotent.

## The AI Score

A 30-feature multilayer perceptron trained on stored ranked games predicts whether a
participant's stat line belongs to the winning team. The AI Score is that probability,
0 to 100. Features are per-minute and per-gold rates (damage, gold, CS, vision, objectives,
kills, deaths, assists and more), so the score says how a game was played rather than who
won it — though the two correlate strongly, and the profile's insights tab shows which
stats moved a player's score.

```bash
uv run hextrack train --activate   # train on stored games, activate, re-score
uv run hextrack model list
```

Activation re-scores stored games and running processes pick the new model up within a
minute. Artifacts live in `api/artifacts/<version>/` and are not committed.

## Discord bot

```bash
uv run hextrack bot     # needs DISCORD_TOKEN and DISCORD_BROADCAST_CHANNEL_ID
```

It posts rank ups and downs, stand-out games with their AI Score, and a daily season
leaderboard, and answers `/lp`. It reads the database only, never Riot, and consumes an
outbox table, so events queued while it was offline are not spammed later.

## Deployment

Live at https://hextrack.slabby.dev. Everything runs on a Raspberry Pi; a VPS only
terminates HTTPS and forwards requests to the Pi over Tailscale:

```
browser ──https──▶ VPS (Caddy, hextrack.slabby.dev) ──tailscale──▶ Pi :8000
                                                                   ├─ hextrack serve  (API + web/dist)
                                                                   ├─ hextrack worker (Riot poller)
                                                                   ├─ hextrack bot    (Discord)
                                                                   └─ Postgres
```

The Pi runs the three processes as systemd user units (`hextrack-api`, `hextrack-worker`,
`hextrack-bot`) from `~/hextrack-v2`, with its own `.env`, database and model artifacts.
The API listens on localhost only and `tailscale serve --tcp 8000` exposes it to the
tailnet, where the access policy lets the VPS (`tag:proxy`) reach that one port.

To ship a change, commit it and run:

```bash
./deploy.sh             # push, then pull + sync + migrate + build + restart on the Pi
./deploy.sh --status    # what the Pi is running
./deploy.sh --logs      # follow the Pi's logs
```

The Pi's database is the live one, so train and rescore there:

```bash
ssh rpi5 'cd ~/hextrack-v2/api && .venv/bin/hextrack train --activate'
```

Only one poller may run at a time (it takes a Postgres advisory lock), and the rate
limiter splits the Riot key's budget between the poller and the site, so don't run a
second worker against the same key.

## Tests

```bash
make test    # backend
make lint
cd web && npm run typecheck && npm run lint && npm run build
```

---

HexTrack isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot
Games or anyone officially involved in producing or managing Riot Games properties. Riot
Games, and all associated properties are trademarks or registered trademarks of Riot
Games, Inc.

[uv]: https://docs.astral.sh/uv/
