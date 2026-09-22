# HexTrack v2 developer tasks. Run `make help` for a list.

PG_BIN  ?= /opt/homebrew/opt/postgresql@16/bin
PG_DATA ?= /opt/homebrew/var/postgresql@16
PG_LOG  ?= $(PG_DATA)/server.log
UV      ?= uv
NPM     ?= npm
API     := cd api &&

.DEFAULT_GOAL := help
.PHONY: help db-start db-stop migrate api worker bot web gen-api seed train test lint

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

db-start: ## Start the Homebrew Postgres 16 server
	LC_ALL=en_US.UTF-8 $(PG_BIN)/pg_ctl -D $(PG_DATA) -l $(PG_LOG) -w start

db-stop: ## Stop the Homebrew Postgres 16 server
	LC_ALL=en_US.UTF-8 $(PG_BIN)/pg_ctl -D $(PG_DATA) -w stop

migrate: ## Apply database migrations
	$(API) $(UV) run hextrack db upgrade

api: ## Run the API with the in-process poller and auto-reload
	$(API) $(UV) run hextrack serve --with-worker --reload

worker: ## Run the standalone poller
	$(API) $(UV) run hextrack worker

bot: ## Run the Discord bot
	$(API) $(UV) run hextrack bot

web: ## Run the Vite dev server
	$(NPM) --prefix web run dev

gen-api: ## Regenerate web/src/api/openapi.json and the TypeScript client types
	$(API) $(UV) run hextrack openapi --out ../web/src/api/openapi.json
	$(NPM) --prefix web run gen:api

seed: ## Add deterministic demo players and games (replaces demo data, keeps real data)
	$(API) $(UV) run hextrack seed-demo --reset

train: ## Train and activate a new AI Score model (re-scores stored games; restart api/worker)
	$(API) $(UV) run hextrack train --activate

test: ## Run the backend tests
	$(API) $(UV) run pytest -q

lint: ## Lint and format-check the backend
	$(API) $(UV) run ruff check .
	$(API) $(UV) run ruff format --check .
