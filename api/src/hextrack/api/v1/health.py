"""GET /health: database, model, Riot key and poller status."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack import __version__
from hextrack.api.schemas import Health, HealthBot, HealthModel, HealthPoller, HealthRiot
from hextrack.bot.state import BOT_STATE_KEY
from hextrack.config import Settings
from hextrack.db.models import AppState
from hextrack.ingest.poller import POLLER_STATE_KEY

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

DB_TIMEOUT_SECONDS = 3.0
#: The bot writes its heartbeat every 10 s; older than this means the process is gone.
BOT_HEARTBEAT_STALE = timedelta(seconds=60)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def poller_status(
    state: dict[str, Any] | None, settings: Settings, *, now: datetime | None = None
) -> HealthPoller:
    """Interpret the ``app_state["poller"]`` heartbeat.

    ``running`` is true when the heartbeat does not say ``running: false`` and was written
    within three poll intervals (plus a minute of slack); a stale heartbeat means the worker
    died without cleaning up.
    """
    if not state:
        return HealthPoller(last_run_at=None, last_error=None, running=False)
    now = now or datetime.now(UTC)
    last_run_at = _parse_dt(state.get("last_run_at"))
    heartbeat_at = _parse_dt(state.get("heartbeat_at")) or last_run_at
    stale_after = timedelta(seconds=3 * settings.poll_interval_seconds + 60)
    fresh = heartbeat_at is not None and now - heartbeat_at <= stale_after
    running = bool(state.get("running", True)) and fresh
    last_error = state.get("last_error")
    return HealthPoller(
        last_run_at=last_run_at,
        last_error=str(last_error) if last_error else None,
        running=running,
    )


def bot_status(
    state: dict[str, Any] | None, settings: Settings, *, now: datetime | None = None
) -> HealthBot:
    """Interpret the ``app_state["bot"]`` heartbeat written by the Discord bot process."""
    configured = bool(settings.discord_token) and settings.discord_broadcast_channel_id is not None
    if not state:
        return HealthBot(
            configured=configured,
            running=False,
            connected=False,
            heartbeat_at=None,
            last_error=None,
        )
    now = now or datetime.now(UTC)
    heartbeat_at = _parse_dt(state.get("heartbeat_at"))
    fresh = heartbeat_at is not None and now - heartbeat_at <= BOT_HEARTBEAT_STALE
    running = bool(state.get("running", True)) and fresh
    last_error = state.get("last_error")
    return HealthBot(
        configured=configured,
        running=running,
        connected=running and bool(state.get("connected", False)),
        heartbeat_at=heartbeat_at,
        last_error=str(last_error) if last_error else None,
    )


def worker_key_rejected(state: dict[str, Any] | None, last_ok_at: datetime | None) -> str | None:
    """The worker's report that Riot refused the key, when it is newer than this process'
    own last successful Riot call.

    The API only talks to Riot when a visitor looks up an unknown player, so after the daily
    development key expires it can keep reporting "Ready" for hours while the worker is
    already backing off. Returns the error to surface, or None.
    """
    if not state:
        return None
    report = state.get("last_report")
    if not isinstance(report, dict) or not report.get("auth_failed"):
        return None
    reported_at = _parse_dt(report.get("finished_at")) or _parse_dt(state.get("last_run_at"))
    if reported_at is None or (last_ok_at is not None and reported_at <= last_ok_at):
        return None
    errors = report.get("errors")
    detail = errors[-1] if isinstance(errors, list) and errors else None
    return str(detail) if detail else "the poller's Riot API key was rejected"


async def _check_db(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[bool, dict[str, dict[str, Any]]]:
    async with factory() as session:
        await session.execute(text("SELECT 1"))
        rows = await session.execute(
            select(AppState.key, AppState.value).where(
                AppState.key.in_((POLLER_STATE_KEY, BOT_STATE_KEY))
            )
        )
        states = {key: value for key, value in rows.tuples() if isinstance(value, dict)}
        return True, states


@router.get("/health", response_model=Health, summary="Service health")
async def get_health(request: Request) -> Health:
    state = request.app.state
    settings: Settings = state.settings

    db_ok = False
    states: dict[str, dict[str, Any]] = {}
    try:
        db_ok, states = await asyncio.wait_for(
            _check_db(state.session_factory), timeout=DB_TIMEOUT_SECONDS
        )
    except Exception as exc:  # health must never raise
        logger.warning("health: database check failed: %s", exc)

    scorer = getattr(state, "scorer", None)
    if scorer is not None:
        try:
            trained_at = scorer.trained_at
        except Exception:
            trained_at = None
        model = HealthModel(
            loaded=True,
            version=scorer.version,
            trained_at=trained_at,
            n_features=len(scorer.feature_names),
        )
    else:
        model = HealthModel(loaded=False, version=None, trained_at=None, n_features=None)

    riot_status = state.riot.status
    key_ok = riot_status.key_ok
    last_error = riot_status.last_error
    # The worker owns most of the Riot traffic: when it says the key was rejected after our
    # own last successful call, the key is expired for the whole deployment.
    rejected = worker_key_rejected(states.get(POLLER_STATE_KEY), riot_status.last_ok_at)
    if rejected is not None:
        key_ok = False
        last_error = rejected
    riot = HealthRiot(
        key_configured=riot_status.key_configured,
        key_ok=key_ok,
        last_error=last_error,
    )

    healthy = db_ok and riot.key_configured and riot.key_ok is not False
    return Health(
        status="ok" if healthy else "degraded",
        version=__version__,
        db_ok=db_ok,
        model=model,
        riot=riot,
        poller=poller_status(states.get(POLLER_STATE_KEY), settings),
        bot=bot_status(states.get(BOT_STATE_KEY), settings),
    )
