"""ingest.poller: ticks, dedupe, error handling, heartbeat, advisory lock and the loop."""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from hextrack.db.models import AppState, Match, Summoner
from hextrack.demo.names import demo_puuid
from hextrack.ingest import poller, service
from hextrack.ingest.poller import POLLER_STATE_KEY, AdvisoryLock, poll_forever, poll_once
from hextrack.riot.errors import RiotForbidden, RiotKeyMissing, RiotRateLimited, RiotUnavailable
from tests.factories import make_match_json, match_series, spec
from tests.test_ingest_support import (
    IngestFakeRiot,
    StubScorer,
    count,
    events_of,
    make_ctx,
    recent,
    stored_match_ids,
)


@pytest.fixture
def riot(settings) -> IngestFakeRiot:
    return IngestFakeRiot(settings)


@pytest.fixture
def ctx(clean_db, settings, session_factory, riot):
    fast = settings.model_copy(update={"poll_interval_seconds": 0.05})
    return make_ctx(fast, session_factory, riot)


async def _roster(session, riot, *names: str, backfilled: bool = True) -> list[str]:
    """Tracked summoners (already backfilled unless told otherwise); returns puuids."""
    puuids = []
    for i, name in enumerate(names):
        puuid = f"p-{name.lower()}"
        riot.add_account(name, "NA1", puuid=puuid, level=100 + i)
        riot.add_league_entry(puuid, "RANKED_SOLO_5x5", "GOLD", "II", 10 * i)
        session.add(
            Summoner(
                puuid=puuid,
                game_name=name,
                tag_line="NA1",
                platform="na1",
                is_tracked=True,
                tracked_since=datetime(2026, 1, 1, tzinfo=UTC),
                backfilled_at=datetime(2026, 1, 2, tzinfo=UTC) if backfilled else None,
            )
        )
        puuids.append(puuid)
    await session.commit()
    return puuids


async def _heartbeat(session) -> dict:
    value = await session.scalar(
        select(AppState.value)
        .where(AppState.key == POLLER_STATE_KEY)
        .execution_options(populate_existing=True)
    )
    assert value is not None
    return value


async def _wait_for(predicate) -> None:
    """Poll ``predicate`` until true (fails after about 5 s)."""
    for _ in range(250):
        if await predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


# --- one tick --------------------------------------------------------------------------------


async def test_poll_once_refreshes_ingests_and_writes_heartbeat(ctx, riot, session):
    a, b = await _roster(session, riot, "Alpha", "Bravo")
    ctx.scorer = StubScorer()
    riot.add_match(make_match_json("NA1_1", [spec(a, "Alpha", "NA1")], start=recent(3)))
    riot.add_match(make_match_json("NA1_2", [spec(b, "Bravo", "NA1")], start=recent(2)))

    report = await poll_once(ctx)

    assert report.skipped is False and report.auth_failed is False
    assert (report.summoners, report.new_matches, report.scored_matches) == (2, 2, 2)
    assert report.errors == []
    assert await stored_match_ids(session) == {"NA1_1", "NA1_2"}
    refreshed = await session.scalars(
        select(Summoner.last_refreshed_at).execution_options(populate_existing=True)
    )
    assert all(ts is not None for ts in refreshed)
    beat = await _heartbeat(session)
    assert beat["running"] is True and beat["last_error"] is None
    assert beat["matches_ingested"] == 2
    assert datetime.fromisoformat(beat["last_run_at"]) >= report.started_at
    assert datetime.fromisoformat(beat["heartbeat_at"]) >= report.started_at
    assert beat["last_report"]["new_matches"] == 2
    assert {e.kind for e in await events_of(session)} == {"new_match"}

    # nothing new: a second tick fetches no matches
    again = await poll_once(ctx)
    assert again.new_matches == 0
    assert len(riot.calls_to("match")) == 2


async def test_shared_games_are_fetched_once(ctx, riot, session):
    a, b, c = await _roster(session, riot, "Alpha", "Bravo", "Charlie")
    shared = make_match_json(
        "NA1_10",
        [spec(a, "Alpha", "NA1"), spec(b, "Bravo", "NA1"), spec(c, "Charlie", "NA1")],
        start=recent(),
    )
    riot.add_match(shared)
    riot.add_match(make_match_json("NA1_11", [spec(a), spec(b)], start=recent(2)))

    report = await poll_once(ctx)

    assert report.new_matches == 2
    assert sorted(call.args[0] for call in riot.calls_to("match")) == ["NA1_10", "NA1_11"]
    # one new_match event per tracked participant
    assert len(await events_of(session, "new_match")) == 5


async def test_per_summoner_errors_are_skipped(ctx, riot, session):
    a, b = await _roster(session, riot, "Alpha", "Bravo")
    riot.add_match(make_match_json("NA1_20", [spec(b, "Bravo", "NA1")], start=recent()))
    riot.fail("summoner_by_puuid", RiotUnavailable("503 from Riot"))  # Alpha (first) only

    report = await poll_once(ctx)

    assert report.auth_failed is False
    assert report.new_matches == 1
    assert len(report.errors) == 1 and "Alpha#NA1" in report.errors[0]
    assert (await _heartbeat(session))["last_error"] == report.errors[0]


async def test_per_match_errors_are_skipped(ctx, riot, session):
    a, b = await _roster(session, riot, "Alpha", "Bravo")
    # Matches are ingested oldest first (NA1_30 before NA1_31).
    riot.add_match(make_match_json("NA1_31", [spec(a)], start=recent(1)))
    riot.add_match(make_match_json("NA1_30", [spec(b)], start=recent(2)))
    riot.fail("match", RiotUnavailable("timeout"))  # the first fetch of the tick
    riot.corrupt["NA1_31"] = {"status": {"status_code": 500}}

    report = await poll_once(ctx)

    assert report.new_matches == 0
    assert len(report.errors) == 1  # NA1_30 transient error; NA1_31 corrupt (skipped quietly)
    assert await stored_match_ids(session) == set()

    riot.corrupt.clear()
    assert (await poll_once(ctx)).new_matches == 2


async def test_persistent_rate_limit_pauses_then_continues(ctx, riot, session, monkeypatch):
    monkeypatch.setattr(poller, "MAX_RATE_LIMIT_PAUSE_SECONDS", 0.01)
    pauses: list[float] = []
    real_pause = poller._pause_for_rate_limit

    async def spy(stop, exc):
        pauses.append(exc.retry_after)
        await real_pause(stop, exc)

    monkeypatch.setattr(poller, "_pause_for_rate_limit", spy)
    a, b = await _roster(session, riot, "Alpha", "Bravo")
    riot.add_match(make_match_json("NA1_41", [spec(a)], start=recent(1)))
    riot.add_match(make_match_json("NA1_40", [spec(b)], start=recent(2)))
    riot.fail("match", RiotRateLimited(retry_after=7))  # the first (oldest) fetch

    report = await poll_once(ctx)

    assert pauses == [7]
    assert report.new_matches == 1 and len(report.errors) == 1
    assert await stored_match_ids(session) == {"NA1_41"}


@pytest.mark.parametrize(
    "error", [RiotForbidden("Forbidden", status=403), RiotKeyMissing()], ids=["403", "no-key"]
)
async def test_rejected_key_aborts_the_tick(ctx, riot, session, error):
    await _roster(session, riot, "Alpha", "Bravo")
    riot.fail("summoner_by_puuid", error, times=None)

    report = await poll_once(ctx)

    assert report.auth_failed is True
    # the second summoner was never attempted
    assert len(riot.calls_to("summoner_by_puuid")) == 1
    assert riot.calls_to("match_ids_by_puuid") == []
    beat = await _heartbeat(session)
    assert beat["last_error"] and str(error) in beat["last_error"]
    assert await count(session, Match) == 0


async def test_newly_tracked_players_are_backfilled_once(ctx, riot, session, settings):
    ctx.settings = ctx.settings.model_copy(update={"backfill_count": 2})
    (new,) = await _roster(session, riot, "Newbie", backfilled=False)
    for raw in match_series(new, 5, game_name="Newbie"):
        riot.add_match(raw)

    report = await poll_once(ctx)

    assert report.new_matches == 5 and report.backfilled == 1
    calls = riot.calls_to("match_ids_by_puuid")
    assert [c.kwargs["start"] for c in calls] == [0, 2, 4]
    assert all(c.kwargs["start_time"] == settings.season_start for c in calls)
    summoner = await session.get(Summoner, new, populate_existing=True)
    assert summoner is not None and summoner.backfilled_at is not None
    # season backfills never announce old games
    assert await events_of(session) == []

    # The finished backfill left a watermark: the next tick only lists from there instead
    # of paging the whole season again.
    assert summoner.synced_through is not None
    riot.calls.clear()
    await poll_once(ctx)
    steady = riot.calls_to("match_ids_by_puuid")[0]
    assert steady.kwargs["start_time"] == summoner.synced_through - service.SYNC_OVERLAP
    assert steady.kwargs["start_time"] > settings.season_start


async def test_unfinished_backfill_is_retried(ctx, riot, session, monkeypatch):
    monkeypatch.setattr(poller, "MAX_MATCHES_PER_TICK", 3)
    (new,) = await _roster(session, riot, "Newbie", backfilled=False)
    for raw in match_series(new, 5, game_name="Newbie"):
        riot.add_match(raw)

    first = await poll_once(ctx)
    assert first.new_matches == 3 and first.backfilled == 0
    second = await poll_once(ctx)
    assert second.new_matches == 2 and second.backfilled == 1
    assert len(await stored_match_ids(session)) == 5


async def test_untracked_players_are_not_polled(ctx, riot, session):
    riot.add_account("Stranger", "NA1", puuid="stranger")
    session.add(Summoner(puuid="stranger", game_name="Stranger", tag_line="NA1", platform="na1"))
    await session.commit()
    report = await poll_once(ctx)
    assert report.summoners == 0 and riot.calls == []


async def test_demo_players_are_not_polled(ctx, riot, session):
    """`seed-demo` marks its players tracked, but their puuids are synthetic: polling them
    would spend the real key on requests Riot can only answer with 404."""
    session.add(
        Summoner(
            puuid=demo_puuid("Demo Person", "DEMO"),
            game_name="Demo Person",
            tag_line="DEMO",
            platform="na1",
            is_tracked=True,
            tracked_since=datetime(2026, 1, 1, tzinfo=UTC),
            backfilled_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    await session.commit()
    report = await poll_once(ctx)
    assert report.summoners == 0 and riot.calls == []


# --- advisory lock ---------------------------------------------------------------------------


async def test_advisory_lock_prevents_concurrent_polls(ctx, riot, session, engine):
    await _roster(session, riot, "Alpha")
    holder = AdvisoryLock(engine)
    assert await holder.acquire() is True
    try:
        other = AdvisoryLock(engine)
        assert await other.acquire() is False
        report = await poll_once(ctx)
        assert report.skipped is True
        assert riot.calls == []
    finally:
        await holder.release()
    assert holder.held is False
    report = await poll_once(ctx)
    assert report.skipped is False and report.summoners == 1


async def test_two_simultaneous_ticks_run_only_once(ctx, riot, session):
    await _roster(session, riot, "Alpha")
    gate = riot.block("summoner_by_puuid")

    first = asyncio.create_task(poll_once(ctx))
    await asyncio.wait_for(riot.entered["summoner_by_puuid"].wait(), 5)
    second = await poll_once(ctx)
    gate.set()
    first_report = await first

    assert second.skipped is True
    assert first_report.skipped is False and first_report.summoners == 1
    assert len(riot.calls_to("summoner_by_puuid")) == 1


# --- loop ------------------------------------------------------------------------------------


async def test_poll_forever_loops_until_stopped(ctx, riot, session):
    await _roster(session, riot, "Alpha")
    stop = asyncio.Event()
    task = asyncio.create_task(poll_forever(ctx, stop))

    async def two_ticks() -> bool:
        return len(riot.calls_to("summoner_by_puuid")) >= 2

    await _wait_for(two_ticks)
    stop.set()
    await asyncio.wait_for(task, 5)

    beat = await _heartbeat(session)
    assert beat["running"] is False
    assert beat["last_run_at"] is not None
    # the lock was released on the way out
    lock = AdvisoryLock(poller._engine_of(ctx))
    assert await lock.acquire() is True
    await lock.release()


async def test_poll_forever_backs_off_after_rejected_key(ctx, riot, session, monkeypatch):
    await _roster(session, riot, "Alpha")
    riot.fail("summoner_by_puuid", RiotForbidden("Forbidden", status=403), times=None)
    delays: list[float] = []
    real_sleep = poller._sleep_until_stopped

    async def recording_sleep(stop: asyncio.Event, seconds: float) -> bool:
        delays.append(seconds)
        return await real_sleep(stop, 0.01) or len(delays) >= 2

    monkeypatch.setattr(poller, "_sleep_until_stopped", recording_sleep)
    await asyncio.wait_for(poll_forever(ctx, asyncio.Event()), 5)

    assert delays == [poller.AUTH_BACKOFF_SECONDS, poller.AUTH_BACKOFF_SECONDS]
    beat = await _heartbeat(session)
    assert "Forbidden" in beat["last_error"] and beat["running"] is False


async def test_poll_forever_stands_by_while_another_poller_holds_the_lock(ctx, riot, session):
    await _roster(session, riot, "Alpha")
    holder = AdvisoryLock(poller._engine_of(ctx))
    assert await holder.acquire()
    stop = asyncio.Event()
    task = asyncio.create_task(poll_forever(ctx, stop))
    try:
        await asyncio.sleep(0.3)  # several intervals
        assert riot.calls == []
        await holder.release()

        async def polled() -> bool:
            return bool(riot.calls_to("summoner_by_puuid"))

        await _wait_for(polled)
    finally:
        stop.set()
        await asyncio.wait_for(task, 5)
        await holder.release()


async def test_stop_cancels_a_stuck_tick_after_grace(ctx, riot, session, monkeypatch):
    monkeypatch.setattr(poller, "STOP_GRACE_SECONDS", 0.1)
    await _roster(session, riot, "Alpha")
    riot.block("summoner_by_puuid")  # never released
    stop = asyncio.Event()
    task = asyncio.create_task(poll_forever(ctx, stop))
    await asyncio.wait_for(riot.entered["summoner_by_puuid"].wait(), 5)

    stop.set()
    await asyncio.wait_for(task, 2)

    assert (await _heartbeat(session))["running"] is False
    lock = AdvisoryLock(poller._engine_of(ctx))
    assert await lock.acquire() is True
    await lock.release()


async def test_heartbeat_is_readable_by_health(ctx, riot, session):
    from hextrack.api.v1.health import poller_status

    await _roster(session, riot, "Alpha")
    await poll_once(ctx)
    status = poller_status(
        await _heartbeat(session), ctx.settings.model_copy(update={"poll_interval_seconds": 120})
    )
    assert status.running is True and status.last_error is None
    assert status.last_run_at is not None
    assert datetime.now(UTC) - status.last_run_at < timedelta(minutes=1)


async def test_tracked_since_is_untouched_by_polling(ctx, riot, session):
    (a,) = await _roster(session, riot, "Alpha")
    await session.execute(update(Summoner).values(tracked_since=datetime(2026, 2, 2, tzinfo=UTC)))
    await session.commit()
    await poll_once(ctx)
    summoner = await session.get(Summoner, a, populate_existing=True)
    assert summoner is not None and summoner.tracked_since == datetime(2026, 2, 2, tzinfo=UTC)


# --- standalone worker -----------------------------------------------------------------------


async def test_run_worker_shuts_down_gracefully_on_sigterm(
    clean_db, settings, session_factory, monkeypatch
):
    fast = settings.model_copy(update={"poll_interval_seconds": 0.05})  # empty roster, no key
    started = asyncio.Event()
    contexts = []
    real_poll_forever = poller.poll_forever

    async def spy(ctx, stop):
        contexts.append(ctx)
        started.set()
        await real_poll_forever(ctx, stop)

    monkeypatch.setattr(poller, "poll_forever", spy)
    worker = asyncio.create_task(poller.run_worker(fast))
    await asyncio.wait_for(started.wait(), 30)

    # run_worker installed its SIGTERM handler before starting the loop
    signal.raise_signal(signal.SIGTERM)
    await asyncio.wait_for(worker, 10)

    (ctx,) = contexts
    assert ctx.scorer is None
    assert ctx.riot.closed is True
    async with session_factory() as s:
        value = await s.scalar(select(AppState.value).where(AppState.key == POLLER_STATE_KEY))
    assert value is not None and value["running"] is False
    # handlers were removed again: SIGTERM is back to the default disposition
    assert signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, None)


async def test_pending_backfill_lists_from_the_watermark_next_tick(ctx, riot, session, monkeypatch):
    """While a large backfill is still running, the next tick must not page the whole
    season again for every player: what the first tick ingested is already behind the
    watermark."""
    monkeypatch.setattr(poller, "MAX_MATCHES_PER_TICK", 3)
    ctx.settings = ctx.settings.model_copy(update={"backfill_count": 2})
    (new,) = await _roster(session, riot, "Newbie", backfilled=False)
    for raw in match_series(new, 6, game_name="Newbie"):
        riot.add_match(raw)

    first = await poll_once(ctx)
    assert first.new_matches == 3 and first.backfilled == 0
    summoner = await session.get(Summoner, new, populate_existing=True)
    assert summoner is not None and summoner.synced_through is not None
    first_listings = len(riot.calls_to("match_ids_by_puuid"))

    riot.calls.clear()
    second = await poll_once(ctx)

    assert second.new_matches == 3 and second.backfilled == 1
    second_listings = riot.calls_to("match_ids_by_puuid")
    assert len(second_listings) < first_listings
    assert second_listings[0].kwargs["start_time"] > ctx.settings.season_start
    assert len(await stored_match_ids(session)) == 6


async def test_the_worker_picks_up_a_model_activated_while_it_runs(ctx, monkeypatch):
    """Otherwise every game the worker stores keeps the old model_version, which the
    averages and the trend then ignore."""

    class _Scorer:
        def __init__(self, version: str) -> None:
            self.version = version

    active = {"version": "v2"}
    rescored: list[str] = []
    monkeypatch.setattr(poller, "_active_version", lambda _settings: active["version"])
    monkeypatch.setattr(poller, "_load_scorer", lambda _settings: _Scorer(active["version"]))
    monkeypatch.setattr(
        poller, "_rescore_stale", lambda _settings: rescored.append(active["version"]) or 7
    )

    ctx.scorer = _Scorer("v1")
    assert await poller.reload_scorer_if_changed(ctx) is True
    assert ctx.scorer.version == "v2" and rescored == ["v2"]
    # Unchanged: no reload, no rescore.
    assert await poller.reload_scorer_if_changed(ctx) is False
    assert rescored == ["v2"]


async def test_model_reload_failures_never_stop_the_poller(ctx, monkeypatch):
    def boom(_settings):
        raise RuntimeError("artifacts are being written right now")

    monkeypatch.setattr(poller, "_active_version", boom)
    ctx.scorer = None
    assert await poller.reload_scorer_if_changed(ctx) is False
