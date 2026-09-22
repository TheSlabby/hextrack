"""Background worker that keeps the tracked roster fresh (owner: B2).

One tick (:func:`poll_once`):

1. refresh every tracked summoner (summoner-v4 + league-v4, one transaction each) and
   discover their new match ids: a season backfill for anyone whose ``backfilled_at`` is
   unset (every newly tracked player), otherwise everything Riot recorded since their
   ``synced_through`` watermark;
2. dedupe the ids across the roster (friends share games) and ingest them one transaction
   per match, as fast as the Riot limiter allows (at most :data:`MAX_MATCHES_PER_TICK`; the
   rest is picked up next tick). New games come before the backfills, and each group runs
   oldest first, so a tick that is cut short leaves contiguous history behind;
3. move every player's watermark up over what is now stored, mark finished backfills and
   write the heartbeat to ``app_state["poller"]``.

Per-summoner / per-match failures are logged, recorded and skipped. A missing or
rejected Riot key (:class:`RiotKeyMissing` / :class:`RiotForbidden`) aborts the tick and
:func:`poll_forever` backs off :data:`AUTH_BACKOFF_SECONDS`.

Only one poller runs at a time across all processes: the loop holds a session-level
``pg_try_advisory_lock(POLLER_LOCK_KEY)`` on a dedicated connection.

Heartbeat (``app_state["poller"].value``, datetimes ISO-8601)::

    {"running": bool, "heartbeat_at": ISO, "last_run_at": ISO, "last_error": str | None,
     "matches_ingested": int, "last_report": {...PollReport fields...}}
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from hextrack.config import Settings
from hextrack.db.engine import session_scope
from hextrack.db.repo import app_state as app_state_repo
from hextrack.db.repo import summoners as summoners_repo
from hextrack.demo.names import DEMO_PUUID_PREFIX
from hextrack.ingest.context import IngestContext
from hextrack.ingest.service import (
    Discovery,
    advance_sync,
    discover,
    ingest_match,
    refresh_summoner,
)
from hextrack.riot.errors import RiotError, RiotForbidden, RiotKeyMissing, RiotRateLimited

if TYPE_CHECKING:
    from hextrack.hextrack_ai.inference import Scorer

logger = logging.getLogger(__name__)

#: app_state key holding the poller heartbeat: {"last_run_at", "last_error", "running",
#: "heartbeat_at", "matches_ingested", "last_report": {...}} (ISO datetimes). Read by
#: GET /api/v1/health.
POLLER_STATE_KEY = "poller"
#: ``pg_try_advisory_lock`` key held by the active poller ("HXTRPOLL").
POLLER_LOCK_KEY: Final = 0x4858_5452_504F_4C4C
#: Back-off after the Riot key turned out missing or rejected (dev keys expire daily).
AUTH_BACKOFF_SECONDS: Final = 600.0
#: Matches ingested per tick at most; the rest is rediscovered and ingested next tick.
MAX_MATCHES_PER_TICK: Final = 500
#: Errors kept in a PollReport / heartbeat.
MAX_REPORTED_ERRORS: Final = 50
#: Write an in-tick heartbeat after this many ingested matches (long backfills).
HEARTBEAT_EVERY_MATCHES: Final = 25
#: Longest pause after a 429 that survived the client's own retry.
MAX_RATE_LIMIT_PAUSE_SECONDS: Final = 60.0
#: After ``stop`` is set, a running tick gets this long to finish before it is cancelled.
STOP_GRACE_SECONDS: Final = 5.0

_FATAL_RIOT_ERRORS: Final = (RiotForbidden, RiotKeyMissing)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class PollReport:
    started_at: datetime
    finished_at: datetime
    summoners: int = 0
    new_matches: int = 0
    scored_matches: int = 0
    errors: list[str] = field(default_factory=list)
    #: True when another process held the advisory lock and this tick did nothing.
    skipped: bool = False
    #: True when the tick was aborted because the Riot key is missing or rejected.
    auth_failed: bool = False
    #: Summoners whose season backfill completed during this tick.
    backfilled: int = 0

    def add_error(self, message: str) -> None:
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(message)

    def as_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["finished_at"] = self.finished_at.isoformat()
        return data


# --- advisory lock ---------------------------------------------------------------------------


def _engine_of(ctx: IngestContext) -> AsyncEngine:
    bind = ctx.session_factory.kw.get("bind")
    if isinstance(bind, AsyncEngine):
        return bind
    if isinstance(bind, AsyncConnection):
        return bind.engine
    raise RuntimeError("the ingest session factory is not bound to an AsyncEngine")


class AdvisoryLock:
    """A session-level Postgres advisory lock held on its own autocommit connection.

    The lock lives exactly as long as that connection: closing it (or the server losing
    it) releases the lock, so a crashed worker never blocks the next one.
    """

    def __init__(self, engine: AsyncEngine, key: int = POLLER_LOCK_KEY) -> None:
        self._engine = engine
        self.key = key
        self._conn: AsyncConnection | None = None

    @property
    def held(self) -> bool:
        return self._conn is not None

    async def acquire(self) -> bool:
        """Try to take the lock without waiting (True if held afterwards). When already
        held, verifies the connection is still alive and re-acquires if it was lost."""
        if self._conn is not None:
            try:
                await self._conn.execute(text("SELECT 1"))
                return True
            except Exception:
                logger.warning("poller lock connection lost; re-acquiring")
                await self._discard()
        conn = await self._engine.connect()
        try:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            acquired = bool(
                await conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key})
            )
        except BaseException:
            await conn.close()
            raise
        if not acquired:
            await conn.close()
            return False
        self._conn = conn
        return True

    async def release(self) -> None:
        """Release the lock (idempotent)."""
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})
        except Exception:
            # Never return a connection that may still hold the lock to the pool.
            with contextlib.suppress(Exception):
                await conn.invalidate()
        finally:
            with contextlib.suppress(Exception):
                await conn.close()

    async def _discard(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        with contextlib.suppress(Exception):
            await conn.invalidate()
        with contextlib.suppress(Exception):
            await conn.close()


# --- heartbeat -------------------------------------------------------------------------------


async def _write_heartbeat(ctx: IngestContext, patch: dict[str, Any]) -> None:
    """Merge ``patch`` into the heartbeat; failures are logged, never raised."""
    try:
        async with session_scope(ctx.session_factory) as session:
            await app_state_repo.merge_state(
                session, POLLER_STATE_KEY, {"heartbeat_at": _utcnow().isoformat(), **patch}
            )
    except Exception:
        logger.exception("could not write the poller heartbeat")


# --- one tick --------------------------------------------------------------------------------


def _stopping(stop: asyncio.Event | None) -> bool:
    return stop is not None and stop.is_set()


def _chronological(match_ids: Sequence[str]) -> list[str]:
    """Match ids oldest first. Riot's game ids grow with time on a platform, so sorting on
    them orders every single player's games the way they were played (two players' games
    only interleave, which does not matter)."""

    def key(match_id: str) -> tuple[str, int, str]:
        platform, _, game_id = match_id.rpartition("_")
        return (platform, int(game_id) if game_id.isdigit() else -1, match_id)

    return sorted(dict.fromkeys(match_ids), key=key)


class _AbortTick(Exception):
    """Internal: the Riot key is missing or rejected; stop this tick."""


async def _pause_for_rate_limit(stop: asyncio.Event | None, exc: RiotRateLimited) -> None:
    """Honour Retry-After (bounded) before the next request; returns early on stop."""
    seconds = min(max(exc.retry_after, 1.0), MAX_RATE_LIMIT_PAUSE_SECONDS)
    logger.warning("poll: Riot rate limit persisted; pausing %.0fs", seconds)
    if stop is None:
        await asyncio.sleep(seconds)
    else:
        await _sleep_until_stopped(stop, seconds)


async def _tick(ctx: IngestContext, report: PollReport, stop: asyncio.Event | None) -> None:
    factory = ctx.session_factory
    await _write_heartbeat(ctx, {"running": True})
    async with factory() as session:
        roster = await summoners_repo.list_tracked(session)
    # Demo players have synthetic puuids: Riot answers 404 for every one of them, so polling
    # them only burns the key's budget (`seed-demo` may have run against a real database).
    roster = [s for s in roster if not s.puuid.startswith(DEMO_PUUID_PREFIX)]
    report.summoners = len(roster)

    steady: list[str] = []
    backfill: list[str] = []
    #: puuid -> what Riot listed for them this tick; drives the watermark after ingestion.
    discoveries: dict[str, Discovery] = {}
    #: Players whose season backfill is still pending.
    backfilling: set[str] = set()
    for summoner in roster:
        if _stopping(stop):
            return
        wants_backfill = summoner.backfilled_at is None
        try:
            async with factory() as session:
                await refresh_summoner(ctx, session, summoner.puuid)
                await session.commit()
                found = await discover(ctx, session, summoner.puuid, backfill=wants_backfill)
        except _FATAL_RIOT_ERRORS as exc:
            report.add_error(f"{summoner.riot_id}: {exc}")
            raise _AbortTick from exc
        except RiotRateLimited as exc:
            report.add_error(f"{summoner.riot_id}: {exc}")
            await _pause_for_rate_limit(stop, exc)
            continue
        except RiotError as exc:
            logger.warning("poll: %s skipped: %s", summoner.riot_id, exc)
            report.add_error(f"{summoner.riot_id}: {exc}")
            continue
        except Exception as exc:
            logger.exception("poll: unexpected error for %s", summoner.riot_id)
            report.add_error(f"{summoner.riot_id}: {type(exc).__name__}: {exc}")
            continue
        discoveries[summoner.puuid] = found
        (backfill if wants_backfill else steady).extend(found.missing)
        if wants_backfill:
            backfilling.add(summoner.puuid)
        await _write_heartbeat(ctx, {"running": True})

    # New games of the roster first, then the season backfills; each group oldest first, so
    # cutting the tick short leaves every player's stored history contiguous and the
    # watermark can move up over what was ingested.
    queue = list(dict.fromkeys(_chronological(steady) + _chronological(backfill)))
    if len(queue) > MAX_MATCHES_PER_TICK:
        logger.info(
            "poll: %d new matches discovered; ingesting %d this tick",
            len(queue),
            MAX_MATCHES_PER_TICK,
        )
    done: set[str] = set()
    for index, match_id in enumerate(queue[:MAX_MATCHES_PER_TICK], start=1):
        if _stopping(stop):
            break
        try:
            async with session_scope(factory) as session:
                result = await ingest_match(ctx, session, match_id)
        except _FATAL_RIOT_ERRORS as exc:
            report.add_error(f"{match_id}: {exc}")
            raise _AbortTick from exc
        except RiotRateLimited as exc:
            report.add_error(f"{match_id}: {exc}")
            await _pause_for_rate_limit(stop, exc)
            continue
        except RiotError as exc:
            logger.warning("poll: match %s skipped: %s", match_id, exc)
            report.add_error(f"{match_id}: {exc}")
            continue
        except Exception as exc:
            logger.exception("poll: unexpected error ingesting %s", match_id)
            report.add_error(f"{match_id}: {type(exc).__name__}: {exc}")
            continue
        # None means Riot has no valid payload for it (404 / corrupt): nothing to retry.
        done.add(match_id)
        if result is not None and result.created:
            report.new_matches += 1
            if result.scored:
                report.scored_matches += 1
        if index % HEARTBEAT_EVERY_MATCHES == 0:
            await _write_heartbeat(ctx, {"running": True})

    if not discoveries:
        return
    finished = [
        puuid
        for puuid, found in discoveries.items()
        if puuid in backfilling and done.issuperset(found.missing)
    ]
    async with session_scope(factory) as session:
        for found in discoveries.values():
            await advance_sync(session, found, done)
        if finished:
            report.backfilled = await summoners_repo.mark_backfilled(session, finished, _utcnow())


async def poll_once(
    ctx: IngestContext,
    *,
    lock: AdvisoryLock | None = None,
    stop: asyncio.Event | None = None,
) -> PollReport:
    """One tick: refresh every tracked summoner, dedupe new ids across the roster, ingest
    them at rate-limiter pace, and write the heartbeat. Guarded by a Postgres advisory lock
    so only one poller runs at a time.

    ``lock``: an :class:`AdvisoryLock` the caller already holds (``poll_forever``); without
    one the tick takes the lock for its own duration and returns ``skipped=True`` when
    another poller has it. ``stop``: checked between units of work to end the tick early.
    """
    started = _utcnow()
    own_lock = lock is None
    active = lock if lock is not None else AdvisoryLock(_engine_of(ctx))
    if not await active.acquire():
        return PollReport(started_at=started, finished_at=_utcnow(), skipped=True)
    report = PollReport(started_at=started, finished_at=started)
    try:
        try:
            await _tick(ctx, report, stop)
        except _AbortTick:
            report.auth_failed = True
            logger.error("poll aborted: %s", report.errors[-1] if report.errors else "Riot key")
        report.finished_at = _utcnow()
        await _write_heartbeat(
            ctx,
            {
                "running": True,
                "last_run_at": report.finished_at.isoformat(),
                "last_error": report.errors[-1] if report.errors else None,
                "matches_ingested": report.new_matches,
                "last_report": report.as_json(),
            },
        )
    finally:
        if own_lock:
            await active.release()
    return report


# --- loop ------------------------------------------------------------------------------------


async def _sleep_until_stopped(stop: asyncio.Event, seconds: float) -> bool:
    """Sleep ``seconds`` or until ``stop`` is set; True when stopped."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(seconds, 0.0))
    except TimeoutError:
        return False
    return True


async def _run_tick(
    ctx: IngestContext, lock: AdvisoryLock, stop: asyncio.Event
) -> PollReport | None:
    """Run one tick; if ``stop`` is set meanwhile, allow :data:`STOP_GRACE_SECONDS` for it
    to wind down, then cancel it (returns None in that case)."""
    tick = asyncio.create_task(poll_once(ctx, lock=lock, stop=stop), name="hextrack-poll-tick")
    stopper = asyncio.create_task(stop.wait(), name="hextrack-poll-stop")
    try:
        await asyncio.wait({tick, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if not tick.done():
            await asyncio.wait({tick}, timeout=STOP_GRACE_SECONDS)
        if not tick.done():
            logger.warning("poll tick still busy %.0fs after stop; cancelling", STOP_GRACE_SECONDS)
            tick.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tick
            return None
        return tick.result()
    finally:
        stopper.cancel()
        if not tick.done():
            tick.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await tick


async def poll_forever(ctx: IngestContext, stop: asyncio.Event | None = None) -> None:
    """Run :func:`poll_once` every ``poll_interval_seconds`` until ``stop`` is set or the
    task is cancelled. Errors are logged and recorded in the heartbeat, never raised; a
    RiotForbidden / RiotKeyMissing backs off :data:`AUTH_BACKOFF_SECONDS`.

    Holds the poller advisory lock for as long as it runs; while another process holds it,
    this loop stands by and retries every interval.
    """
    stop = stop if stop is not None else asyncio.Event()
    interval = float(ctx.settings.poll_interval_seconds)
    lock = AdvisoryLock(_engine_of(ctx))
    standing_by = False
    logger.info("poller started (every %.0fs)", interval)
    try:
        while not stop.is_set():
            delay = interval
            try:
                await reload_scorer_if_changed(ctx)
                if await lock.acquire():
                    if standing_by:
                        logger.info("poller lock acquired; polling")
                        standing_by = False
                    report = await _run_tick(ctx, lock, stop)
                    if report is None:
                        break
                    if report.auth_failed:
                        delay = max(interval, AUTH_BACKOFF_SECONDS)
                        logger.warning("Riot key missing or rejected; next poll in %.0fs", delay)
                    else:
                        logger.info(
                            "poll: %d summoners, %d new matches (%d scored), %d errors",
                            report.summoners,
                            report.new_matches,
                            report.scored_matches,
                            len(report.errors),
                        )
                elif not standing_by:
                    logger.info("another poller holds the lock; standing by")
                    standing_by = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("poll tick failed")
                if lock.held:
                    await _write_heartbeat(
                        ctx, {"running": True, "last_error": f"{type(exc).__name__}: {exc}"}
                    )
            if await _sleep_until_stopped(stop, delay):
                break
    finally:
        if lock.held:
            await _write_heartbeat(ctx, {"running": False})
        await lock.release()
        logger.info("poller stopped")


# --- standalone worker -----------------------------------------------------------------------


def _load_scorer(settings: Settings) -> Scorer | None:
    from hextrack.hextrack_ai.inference import Scorer

    try:
        scorer = Scorer.load(settings.model_dir)
    except Exception:
        logger.exception("failed to load the AI model from %s; scores disabled", settings.model_dir)
        return None
    if scorer is None:
        logger.info("no AI model in %s; matches are stored unscored", settings.model_dir)
    else:
        logger.info("loaded AI model %s", scorer.version)
    return scorer


def _active_version(settings: Settings) -> str | None:
    from hextrack.hextrack_ai.inference import read_active_version

    return read_active_version(settings.model_dir)


def _rescore_stale(settings: Settings) -> int:
    """Score rows that still carry an older model version (blocking; run in a thread)."""
    from hextrack.hextrack_ai.registry import rescore

    return rescore(settings, all_rows=False)


async def reload_scorer_if_changed(ctx: IngestContext) -> bool:
    """Pick up a model activated by ``hextrack train`` / ``model activate`` while running.

    Swaps ``ctx.scorer`` and rescores rows left on the previous version, so new games are
    never stored under a model the averages and trends already ignore. Failures are logged;
    polling continues with the model it has.
    """
    settings = ctx.settings
    current = ctx.scorer.version if ctx.scorer is not None else None
    try:
        active = await asyncio.to_thread(_active_version, settings)
        if active is None or active == current:
            return False
        scorer = await asyncio.to_thread(_load_scorer, settings)
        if scorer is None or scorer.version == current:
            return False
        ctx.scorer = scorer
        logger.info("AI model changed: scoring with %s (was %s)", scorer.version, current or "none")
    except Exception:
        logger.exception("could not load the newly activated AI model")
        return False
    try:
        rows = await asyncio.to_thread(_rescore_stale, settings)
        logger.info("rescored %d participant rows with %s", rows, scorer.version)
    except Exception:
        logger.exception("could not rescore stored matches with %s", scorer.version)
    return True


def _install_signal_handlers(stop: asyncio.Event) -> list[signal.Signals]:
    loop = asyncio.get_running_loop()

    def request_stop(sig: signal.Signals) -> None:
        if stop.is_set():
            logger.info("%s received again; already shutting down", sig.name)
        else:
            logger.info("%s received; shutting down", sig.name)
            stop.set()

    installed: list[signal.Signals] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop, sig)
        except (NotImplementedError, RuntimeError):  # pragma: no cover (Windows)
            signal.signal(sig, lambda s, _f: loop.call_soon_threadsafe(request_stop, s))
        installed.append(sig)
    return installed


async def run_worker(settings: Settings) -> None:
    """Standalone worker entrypoint (``hextrack worker``): builds engine, RiotClient and
    Scorer, runs :func:`poll_forever` until SIGINT/SIGTERM, then disposes everything."""
    from hextrack.db.engine import make_async_engine, make_session_factory
    from hextrack.riot.client import RiotClient

    if not settings.riot_key_configured:
        logger.warning("RIOT_API_KEY is not set; the poller will idle until it is configured")
    engine = make_async_engine(settings, pool_size=3, max_overflow=2)
    stop = asyncio.Event()
    installed = _install_signal_handlers(stop)
    loop = asyncio.get_running_loop()
    try:
        scorer = await asyncio.to_thread(_load_scorer, settings)
        # The worker leaves the on-demand share of the key to the API process and queues on
        # the limiter instead of failing fast (nobody is waiting for its requests).
        async with RiotClient(settings, app_limits=settings.worker_app_rate_limits) as riot:
            ctx = IngestContext(
                settings=settings,
                session_factory=make_session_factory(engine),
                riot=riot,
                scorer=scorer,
            )
            await poll_forever(ctx, stop)
    finally:
        for sig in installed:
            with contextlib.suppress(Exception):
                loop.remove_signal_handler(sig)
        await engine.dispose()
