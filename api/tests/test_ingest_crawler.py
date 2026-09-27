"""ingest.crawler: frontier, player selection, crawling, budget gate, pauses, heartbeat, and
how the poller starts it."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from hextrack.db.engine import session_scope
from hextrack.db.models import AppState, BotEvent, CrawlPlayer, Match, MatchParticipant, Summoner
from hextrack.demo.names import DEMO_PUUID_PREFIX
from hextrack.ingest import crawler as crawler_module
from hextrack.ingest import poller
from hextrack.ingest.crawler import (
    DEFAULT_RESERVE,
    LADDER_SLOTS,
    STATE_KEY,
    CrawlBudget,
    Crawler,
    CrawlReport,
)
from hextrack.ingest.service import ingest_match_json
from hextrack.riot.client import RiotClient
from hextrack.riot.errors import RiotForbidden, RiotKeyMissing, RiotNotFound, RiotRateLimited
from tests.factories import filler_puuid, make_match_json, spec
from tests.test_ingest_support import IngestFakeRiot, StubScorer, count, make_ctx, recent


class _FixedRng:
    """rng stand-in: ladder slot 0 first and always ``page`` (capped to the range)."""

    def __init__(self, page: int = 1) -> None:
        self.page = page

    def randrange(self, n: int) -> int:
        return 0

    def randint(self, a: int, b: int) -> int:
        return max(a, min(self.page, b))


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def riot(settings) -> IngestFakeRiot:
    return IngestFakeRiot(settings)


@pytest.fixture
def ctx(clean_db, settings, session_factory, riot):
    return make_ctx(settings, session_factory, riot)


@pytest.fixture(autouse=True)
def plenty_of_disk(monkeypatch):
    monkeypatch.setattr(crawler_module, "_free_gib", lambda _path: 1000.0)


def _make(ctx, *, stop=None, poll_active=None, sleep=None, rng=None, clock=None, budget=None):
    stop = stop or asyncio.Event()
    poll_active = poll_active or asyncio.Event()

    async def fast_sleep(_seconds: float) -> bool:
        await asyncio.sleep(0)
        return stop.is_set()

    return Crawler(
        ctx,
        stop,
        poll_active,
        budget=budget or CrawlBudget(ctx.riot),
        sleep=sleep or fast_sleep,
        rng=rng or _FixedRng(),
        clock=clock or _Clock(),
    )


async def _frontier(session) -> dict[str, CrawlPlayer]:
    rows = await session.scalars(select(CrawlPlayer).execution_options(populate_existing=True))
    return {row.puuid: row for row in rows}


async def _add_frontier(session, *rows: dict) -> None:
    for row in rows:
        session.add(CrawlPlayer(**{"found_via": "match", **row}))
    await session.commit()


async def _track(session, puuid: str) -> None:
    session.add(
        Summoner(puuid=puuid, game_name="Friend", tag_line="NA1", platform="na1", is_tracked=True)
    )
    await session.commit()


async def _state(session) -> dict:
    value = await session.scalar(
        select(AppState.value)
        .where(AppState.key == STATE_KEY)
        .execution_options(populate_existing=True)
    )
    assert value is not None
    return value


def _game(match_id: str, puuid: str, *, hours_ago: float = 3.0, others=()) -> dict:
    return make_match_json(
        match_id, [spec(puuid, "Stranger", "NA1"), *others], start=recent(hours_ago)
    )


# --- frontier ------------------------------------------------------------------------------


async def test_ladder_pages_seed_the_frontier_and_rotate_through_tiers(ctx, riot, session):
    await _track(session, "friend")
    riot.add_ladder_page("IRON", "IV", ["iron-1", "iron-2", "friend", f"{DEMO_PUUID_PREFIX}x"])
    riot.add_ladder_page("IRON", "III", ["iron-3"])
    crawler = _make(ctx)

    first = await crawler.step()
    second = await crawler.step()

    assert (first.ladder, second.ladder) == ("IRON IV p1", "IRON III p1")
    calls = [c.args for c in riot.calls_to("league_exp_entries")]
    assert calls == [("RANKED_SOLO_5x5", "IRON", "IV"), ("RANKED_SOLO_5x5", "IRON", "III")]
    rows = await _frontier(session)
    assert set(rows) == {"iron-1", "iron-2", "iron-3"}  # tracked and demo players skipped
    assert {(r.found_via, r.tier, r.division) for r in rows.values()} == {
        ("ladder", "IRON", "IV"),
        ("ladder", "IRON", "III"),
    }
    assert first.frontier_added == 2 and first.puuid == "iron-1"

    # apex tiers are one "I" division, stored without a division
    crawler._slot = LADDER_SLOTS.index(("MASTER", "I"))
    riot.add_ladder_page("MASTER", "I", ["master-1"])
    await crawler.step()
    master = (await _frontier(session))["master-1"]
    assert (master.tier, master.division) == ("MASTER", None)
    assert riot.calls_to("league_exp_entries")[-1].args == ("RANKED_SOLO_5x5", "MASTER", "I")


async def test_ladder_page_past_the_end_lowers_the_page_range(ctx, riot, session):
    crawler = _make(ctx, rng=_FixedRng(page=12))
    crawler.ladder_pages["IRON IV"] = [40, False]
    report = CrawlReport()
    await crawler._ladder_page(report, set())
    assert report.ladder == "IRON IV p12"
    assert crawler.ladder_pages["IRON IV"] == [11, True]

    # a full page in the upper half of an open range doubles it
    riot.add_ladder_page("IRON", "III", ["p"], page=12)
    crawler.ladder_pages["IRON III"] = [20, False]
    await crawler._ladder_page(CrawlReport(), set())
    assert crawler.ladder_pages["IRON III"] == [40, False]


async def test_uncrawled_players_come_first_then_recrawls_after_a_week(ctx, session):
    now = datetime.now(UTC)
    await _track(session, "tracked")
    await _add_frontier(
        session,
        {"puuid": "tracked", "discovered_at": now - timedelta(hours=9)},
        {"puuid": "old-match", "discovered_at": now - timedelta(hours=3)},
        {"puuid": "new-match", "discovered_at": now - timedelta(hours=2)},
        {"puuid": "ladder", "found_via": "ladder", "discovered_at": now - timedelta(hours=1)},
        {
            "puuid": "stale",
            "discovered_at": now - timedelta(days=30),
            "crawled_at": now - timedelta(days=8),
        },
        {
            "puuid": "fresh",
            "discovered_at": now - timedelta(days=30),
            "crawled_at": now - timedelta(days=1),
        },
    )
    crawler = _make(ctx)

    # oldest discovered first (tracked players are the poller's); every third pick a ladder one
    assert await crawler._pick() == "old-match"
    assert await crawler._pick() == "old-match"
    assert await crawler._pick() == "ladder"

    async with session_scope(ctx.session_factory) as s:
        for row in (await _frontier(s)).values():
            if row.crawled_at is None and row.puuid != "tracked":
                row.crawled_at = now
    # nobody uncrawled left: whoever was crawled more than 7 days ago
    assert await crawler._pick() == "stale"
    async with session_scope(ctx.session_factory) as s:
        (await _frontier(s))["stale"].crawled_at = now
    assert await crawler._pick() is None


# --- crawling a player -----------------------------------------------------------------------


async def test_crawl_stores_new_games_as_crawl_and_skips_stored_ones(ctx, riot, session, settings):
    ctx.scorer = StubScorer()
    riot.add_match(_game("NA1_1", "p1", hours_ago=5))
    riot.add_match(_game("NA1_2", "p1", hours_ago=4))
    riot.add_match(_game("NA1_3", "p1", hours_ago=3))
    async with session_scope(ctx.session_factory) as s:
        await ingest_match_json(ctx, s, riot.matches["NA1_1"])  # the roster already has it
    await _add_frontier(session, {"puuid": "p1", "found_via": "ladder", "tier": "GOLD"})
    crawler = _make(ctx)

    report = await crawler.step()

    assert report.puuid == "p1"
    assert (report.listed, report.added, report.skipped) == (3, 2, 1)
    assert [c.args[0] for c in riot.calls_to("match")] == ["NA1_3", "NA1_2"]
    (listing,) = riot.calls_to("match_ids_by_puuid")
    assert listing.kwargs["count"] == settings.crawl_matches_per_player
    assert listing.kwargs["type_"] == "ranked"
    assert listing.kwargs["start_time"] == settings.season_start
    sources = dict((await session.execute(select(Match.match_id, Match.source))).all())
    assert sources == {"NA1_1": "roster", "NA1_2": "crawl", "NA1_3": "crawl"}
    # training data only: never scored, even with a model loaded
    assert ctx.scorer.calls == [(1800, 10)]  # the roster game only
    crawled = select(MatchParticipant.ai_score).where(
        MatchParticipant.match_id.in_(["NA1_2", "NA1_3"])
    )
    assert list(await session.scalars(crawled)) == [None] * 20
    unscored = select(Match.scored_at).where(Match.source == "crawl")
    assert list(await session.scalars(unscored)) == [None, None]
    assert await count(session, BotEvent) == 0

    rows = await _frontier(session)
    player = rows["p1"]
    assert player.crawled_at is not None
    assert (player.matches_added, player.last_error) == (2, None)
    # participants of the stored games joined the frontier
    new = {filler_puuid("NA1_2", i) for i in range(1, 10)} | {
        filler_puuid("NA1_3", i) for i in range(1, 10)
    }
    assert new <= set(rows)
    assert all(rows[p].found_via == "match" and rows[p].tier is None for p in new)
    assert filler_puuid("NA1_1", 1) not in rows  # the already stored game adds nobody

    # heartbeat
    await crawler.write_heartbeat()
    beat = await _state(session)
    assert beat["running"] is True and beat["paused_reason"] is None
    assert (beat["matches_added"], beat["matches_added_today"]) == (2, 2)
    assert beat["day"] == datetime.now(UTC).date().isoformat()
    assert beat["players_crawled"] == 1
    assert beat["frontier_total"] == len(rows)
    assert beat["frontier_uncrawled"] == len(rows) - 1
    assert beat["reserve"] == {
        settings.riot_platform: DEFAULT_RESERVE,
        settings.riot_region: DEFAULT_RESERVE,
    }
    assert beat["last_error"] is None
    assert datetime.fromisoformat(beat["updated_at"]) >= datetime.fromisoformat(beat["started_at"])

    # a restart the same day carries today's count over
    again = _make(ctx)
    await again._restore()
    assert again.matches_added_today == 2 and again.matches_added == 0


async def test_games_with_a_tracked_player_are_left_to_the_poller(ctx, riot, session):
    await _track(session, "friend")
    riot.add_match(_game("NA1_7", "p1", others=[spec("friend", "Friend", "NA1")]))
    await _add_frontier(session, {"puuid": "p1"})

    report = await _make(ctx).step()

    assert (report.added, report.skipped) == (0, 1)
    assert await count(session, Match) == 0
    assert await count(session, BotEvent) == 0
    assert "friend" not in await _frontier(session)


async def test_participants_fill_the_frontier_only_up_to_the_cap(ctx, riot, session):
    ctx.settings = ctx.settings.model_copy(update={"crawl_frontier_max": 100})
    others = [spec(f"{DEMO_PUUID_PREFIX}bot", "Demo", "NA1")]
    riot.add_match(_game("NA1_9", "p1", others=others))
    await _add_frontier(
        session,
        {"puuid": "p1"},
        *({"puuid": f"x{i}", "crawled_at": datetime.now(UTC)} for i in range(94)),
    )

    report = await _make(ctx).step()

    rows = await _frontier(session)
    assert report.added == 1
    assert len(rows) == 100 and report.frontier_added == 5
    assert not any(p.startswith(DEMO_PUUID_PREFIX) for p in rows)


async def test_missing_and_invalid_games_are_skipped(ctx, riot, session):
    for hours, match_id in ((5, "NA1_20"), (4, "NA1_21"), (3, "NA1_22")):
        riot.add_match(_game(match_id, "p1", hours_ago=hours))
    riot.fail("match", RiotNotFound("gone"))  # NA1_22, fetched first
    riot.corrupt["NA1_21"] = {"metadata": {"matchId": "NA1_21"}, "info": {"participants": []}}
    await _add_frontier(session, {"puuid": "p1"})

    report = await _make(ctx).step()

    assert (report.listed, report.added, report.skipped) == (3, 1, 2)
    assert set(await session.scalars(select(Match.match_id))) == {"NA1_20"}
    player = (await _frontier(session))["p1"]
    assert player.crawled_at is not None and player.matches_added == 1


# --- budget gate -----------------------------------------------------------------------------


async def test_budget_gate_waits_while_headroom_is_at_or_below_the_reserve(ctx, riot):
    budget = CrawlBudget(riot)
    assert budget.reserve("regional") == DEFAULT_RESERVE  # nothing measured yet
    budget.record("regional", 20)
    assert budget.reserve("regional") == 30 and budget.reserve("platform") == DEFAULT_RESERVE
    riot.headroom = 30
    clock = _Clock()
    crawler = _make(ctx, budget=budget, clock=clock)

    gate = asyncio.create_task(crawler._gate("match"))
    for _ in range(500):
        clock.now += 30
        await asyncio.sleep(0.002)
        if crawler.paused_reason == "budget_starved":
            break
    assert not gate.done()
    assert crawler.paused_reason == "budget_starved"  # waited over 5 minutes

    riot.headroom = 31
    await asyncio.wait_for(gate, 1)
    assert crawler.paused_reason is None

    # a request that would queue in the limiter waits too
    riot.wait_estimate = 0.5
    gate = asyncio.create_task(crawler._gate("match"))
    for _ in range(5):
        await asyncio.sleep(0)
    assert not gate.done()
    riot.wait_estimate = 0.0
    await asyncio.wait_for(gate, 1)


async def test_budget_gate_waits_while_a_poll_tick_runs(ctx, riot):
    poll_active = asyncio.Event()
    poll_active.set()
    clock = _Clock()
    crawler = _make(ctx, poll_active=poll_active, clock=clock)

    gate = asyncio.create_task(crawler._gate("league_exp_entries"))
    for _ in range(20):
        clock.now += 60
        await asyncio.sleep(0.002)
    assert not gate.done()
    assert crawler.paused_reason is None  # a running tick is not starvation

    poll_active.clear()
    await asyncio.wait_for(gate, 1)
    assert riot.calls == []


async def test_budget_gate_raises_on_stop(ctx, riot):
    riot.headroom = 0
    stop = asyncio.Event()
    crawler = _make(ctx, stop=stop)
    gate = asyncio.create_task(crawler._gate("match"))
    await asyncio.sleep(0)
    stop.set()
    with pytest.raises(crawler_module._Stopped):
        await asyncio.wait_for(gate, 1)


async def test_budget_measures_a_tick_on_the_real_limiter(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if "/summoners/" in request.url.path:
            return httpx.Response(
                200, json={"puuid": "p", "profileIconId": 1, "summonerLevel": 30, "revisionDate": 0}
            )
        return httpx.Response(200, json=[])

    keyed = settings.model_copy(update={"riot_api_key": "test-key"})
    async with RiotClient(
        keyed, transport=httpx.MockTransport(handler), app_limits=[(15, 1), (80, 120)]
    ) as client:
        budget = CrawlBudget(client)
        await client.summoner_by_puuid("before-the-tick")
        budget.tick_started()
        for _ in range(5):
            await client.summoner_by_puuid("p")
        for _ in range(3):
            await client.match_ids_by_puuid("p")
        budget.tick_finished()

        assert budget.reserve("platform") == 5 + budget.margin
        assert budget.reserve("regional") == 3 + budget.margin
        # free slots are counted on the 2-minute window, not the 1-second one
        assert budget.headroom("summoner_by_puuid") == 80 - 6
        assert budget.headroom("match") == 80 - 3
        assert client.app_headroom("match") == 15 - 3  # the tightest (1 s) window
        assert budget.available("match") is True  # 77 free > 3 + margin
        budget.record("regional", 80)
        assert budget.available("match") is False


# --- pauses ------------------------------------------------------------------------------------


def _recording_sleep(stop: asyncio.Event, slept: list[float], *, stop_after: int = 1):
    async def sleep(seconds: float) -> bool:
        slept.append(seconds)
        await asyncio.sleep(0)
        if len(slept) >= stop_after:
            stop.set()
        return stop.is_set()

    return sleep


async def test_low_disk_space_pauses_the_crawl(ctx, riot, session, monkeypatch):
    monkeypatch.setattr(crawler_module, "_free_gib", lambda _path: 12.5)
    stop, slept = asyncio.Event(), []
    crawler = _make(ctx, stop=stop, sleep=_recording_sleep(stop, slept))

    await asyncio.wait_for(crawler.run(), 5)

    assert riot.calls == []
    assert slept == [crawler_module.HEARTBEAT_SECONDS]  # first chunk of the 10-minute wait
    beat = await _state(session)
    assert beat["running"] is False and beat["paused_reason"] == "disk"
    assert "12.5 GB" in beat["last_error"]


@pytest.mark.parametrize("error", [RiotForbidden("key expired"), RiotKeyMissing()])
async def test_rejected_key_pauses_the_crawl(ctx, riot, session, error):
    riot.fail("match_ids_by_puuid", error, times=None)
    await _add_frontier(session, {"puuid": "p1"})
    stop, slept = asyncio.Event(), []
    crawler = _make(ctx, stop=stop, sleep=_recording_sleep(stop, slept))

    await asyncio.wait_for(crawler.run(), 5)

    assert slept == [crawler_module.HEARTBEAT_SECONDS]
    beat = await _state(session)
    assert beat["paused_reason"] == "riot_forbidden" and beat["last_error"] == str(error)
    assert (await _frontier(session))["p1"].crawled_at is None  # picked again later


async def test_rate_limit_backs_off_and_leaves_the_player_uncrawled(ctx, riot, session):
    riot.add_match(_game("NA1_30", "p1"))
    riot.fail("match", RiotRateLimited(retry_after=7))
    await _add_frontier(session, {"puuid": "p1"})
    stop, slept = asyncio.Event(), []
    crawler = _make(ctx, stop=stop, sleep=_recording_sleep(stop, slept))

    await asyncio.wait_for(crawler.run(), 5)

    assert slept == [7.0]
    assert (await _frontier(session))["p1"].crawled_at is None


# --- poller integration ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("standalone", "crawl", "expected"),
    [(True, True, True), (False, True, False), (True, False, False)],
)
async def test_poll_forever_runs_the_crawler_only_in_the_standalone_worker(
    ctx, monkeypatch, standalone, crawl, expected
):
    ctx.settings = ctx.settings.model_copy(
        update={"poll_interval_seconds": 0.05, "crawl": crawl, "live_games": False}
    )
    started = asyncio.Event()
    seen: dict = {}

    async def fake_run_crawler(ctx_, stop, poll_active, *, budget):
        seen.update(active_at_start=poll_active.is_set(), budget=budget, poll_active=poll_active)
        started.set()
        await stop.wait()
        seen["stopped"] = True

    monkeypatch.setattr(poller, "run_crawler", fake_run_crawler)
    stop = asyncio.Event()
    task = asyncio.create_task(poller.poll_forever(ctx, stop, crawler=standalone))
    try:
        if expected:
            await asyncio.wait_for(started.wait(), 5)
            assert seen["active_at_start"] is True  # started inside the first tick
            assert isinstance(seen["budget"], CrawlBudget)
            for _ in range(250):
                if not seen["poll_active"].is_set():
                    break
                await asyncio.sleep(0.02)
            assert not seen["poll_active"].is_set()  # cleared between ticks
        else:
            await asyncio.sleep(0.2)
            assert not started.is_set()
    finally:
        stop.set()
        await asyncio.wait_for(task, 10)
    assert seen.get("stopped", False) is expected
