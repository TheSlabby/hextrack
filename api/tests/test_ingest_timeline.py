"""Match timelines: the Riot client call, extraction, the sampling rule, ingestion marking
games pending, the crawler's backlog step and ``hextrack crawl status`` counts."""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from typer.testing import CliRunner

from hextrack.cli import app
from hextrack.db.engine import session_scope
from hextrack.db.models import AppState, CrawlPlayer, Match, MatchTimelinePlayer
from hextrack.ingest import crawler as crawler_module
from hextrack.ingest.crawler import STATE_KEY, CrawlBudget, Crawler
from hextrack.ingest.service import ingest_match_json
from hextrack.ingest.timeline import (
    InvalidTimeline,
    TimelineMismatch,
    extract_timeline,
    match_number,
    timeline_sampled,
)
from hextrack.riot.errors import (
    RiotBadResponse,
    RiotForbidden,
    RiotNotFound,
    RiotRateLimited,
    RiotUnavailable,
)
from tests.factories import (
    COMPONENT_ITEM,
    EVOLVE_PARTICIPANT,
    UNDONE_ITEM,
    make_match_json,
    make_timeline_json,
    spec,
    timeline_plan,
)
from tests.test_crawl_cli import cli_env, empty_frontier  # noqa: F401 (fixtures)
from tests.test_ingest_support import IngestFakeRiot, make_ctx, recent
from tests.test_riot_client import AMERICAS, Script, make_client, reply, riot_error

SEASON = datetime(2026, 1, 8, 20, 0, tzinfo=UTC)


def _players(raw: dict) -> dict[str, int]:
    return {p["puuid"]: p["participantId"] for p in raw["info"]["participants"]}


def _rows_by_pid(rows: list[dict]) -> dict[int, dict]:
    return {row["participant_id"]: row for row in rows}


# --- Riot client -------------------------------------------------------------------------------


async def test_client_fetches_the_timeline_from_the_regional_host() -> None:
    raw = make_match_json("NA1_77")
    timeline = make_timeline_json(raw)
    script = Script(reply(json=timeline))
    client, _ = make_client(script)
    async with client:
        data = await client.match_timeline("NA1_77")
        assert client.limiter_wait_estimate("match_timeline") == 0.0
    assert data == timeline
    request = script.requests[0]
    assert request.url.host == AMERICAS
    assert request.url.path == "/lol/match/v5/matches/NA1_77/timeline"
    assert request.headers["X-Riot-Token"] and "api_key" not in str(request.url)


async def test_client_quotes_the_match_id_segment() -> None:
    script = Script(riot_error(404, "Data not found"))
    client, _ = make_client(script)
    async with client:
        with pytest.raises(RiotNotFound):
            await client.match_timeline("NA1/../x")
    assert script.requests[0].url.raw_path == b"/lol/match/v5/matches/NA1%2F..%2Fx/timeline"


@pytest.mark.parametrize(
    "body",
    [
        {"status": {"message": "oops", "status_code": 500}},  # an error body with a 200
        {"metadata": {"matchId": "NA1_78"}, "info": {"frames": []}},  # another match
        {"metadata": {"matchId": "NA1_77"}, "info": {}},  # no frames
        ["not", "an", "object"],
    ],
)
async def test_client_rejects_invalid_timeline_bodies(body) -> None:
    client, _ = make_client(Script(reply(json=body)))
    async with client:
        with pytest.raises(RiotBadResponse):
            await client.match_timeline("NA1_77")


# --- extraction --------------------------------------------------------------------------------


def test_extraction_matches_the_factory_plan() -> None:
    raw = make_match_json("NA1_900")
    rows = extract_timeline(make_timeline_json(raw), _players(raw), match_id="NA1_900")
    assert len(rows) == 10
    by_pid = _rows_by_pid(rows)
    for pid in range(1, 11):
        plan = timeline_plan(raw, pid)
        row = by_pid[pid]
        assert row["match_id"] == "NA1_900"
        assert row["purchases"] == plan.purchases
        assert row["purchase_s"] == plan.purchase_s
        assert row["skill_order"] == plan.skill_order
        # undone purchase removed; sold / destroyed items stay bought
        assert UNDONE_ITEM not in row["purchases"]
        assert COMPONENT_ITEM in row["purchases"]
        assert row["purchase_s"] == sorted(row["purchase_s"])
    # the EVOLVE level-up is not a skill point
    evolver = by_pid[EVOLVE_PARTICIPANT]["skill_order"]
    assert len(evolver) == raw["info"]["participants"][EVOLVE_PARTICIPANT - 1]["champLevel"]


def test_undo_removes_the_last_matching_purchase_and_sell_undos_are_ignored() -> None:
    raw = make_match_json("NA1_901")
    timeline = make_timeline_json(
        raw,
        purchases={1: [(1055, 10), (2003, 11), (2003, 12), (3006, 600)]},
        skills={1: [1, 3]},
        extra_events=[
            {
                "type": "ITEM_UNDO",
                "timestamp": 13_000,
                "participantId": 1,
                "beforeId": 2003,
                "afterId": 0,
                "goldGain": 50,
            },
            # undoing a sell (beforeId 0) and undoing something never bought: no-ops
            {
                "type": "ITEM_UNDO",
                "timestamp": 14_000,
                "participantId": 1,
                "beforeId": 0,
                "afterId": 1055,
                "goldGain": -200,
            },
            {
                "type": "ITEM_UNDO",
                "timestamp": 15_000,
                "participantId": 1,
                "beforeId": 3071,
                "afterId": 0,
                "goldGain": 0,
            },
            {"type": "ITEM_SOLD", "timestamp": 700_000, "participantId": 1, "itemId": 1055},
            {"type": "ITEM_DESTROYED", "timestamp": 701_000, "participantId": 1, "itemId": 2003},
            {
                "type": "SKILL_LEVEL_UP",
                "timestamp": 900_000,
                "participantId": 1,
                "skillSlot": 4,
                "levelUpType": "EVOLVE",
            },
        ],
    )
    row = _rows_by_pid(extract_timeline(timeline, _players(raw)))[1]
    assert row["purchases"] == [1055, 2003, 3006]
    assert row["purchase_s"] == [10, 11, 600]
    assert row["skill_order"] == [1, 3]


def test_milliseconds_become_whole_seconds_in_timestamp_order() -> None:
    raw = make_match_json("NA1_902")
    timeline = make_timeline_json(raw, purchases={3: []}, skills={3: []})
    frames = timeline["info"]["frames"]
    # events out of order across frames, and a purchase at 61.999 s
    frames[5]["events"].append(
        {"type": "ITEM_PURCHASED", "timestamp": 61_999, "participantId": 3, "itemId": 1001}
    )
    frames[0]["events"].append(
        {"type": "ITEM_PURCHASED", "timestamp": 301_500, "participantId": 3, "itemId": 3020}
    )
    frames[2]["events"].append(
        {"type": "ITEM_PURCHASED", "timestamp": 999, "participantId": 3, "itemId": 1056}
    )
    # participantId 0 is the game, not a player
    frames[1]["events"].append(
        {"type": "ITEM_PURCHASED", "timestamp": 5_000, "participantId": 0, "itemId": 2055}
    )
    row = _rows_by_pid(extract_timeline(timeline, _players(raw)))[3]
    assert row["purchases"] == [1056, 1001, 3020]
    assert row["purchase_s"] == [0, 61, 301]


def test_rows_use_the_stored_participant_ids_matched_by_puuid() -> None:
    raw = make_match_json("NA1_903")
    stored = {puuid: 11 - pid for puuid, pid in _players(raw).items()}  # reversed ids
    by_pid = _rows_by_pid(extract_timeline(make_timeline_json(raw), stored))
    first_puuid = raw["info"]["participants"][0]["puuid"]
    assert by_pid[stored[first_puuid]]["purchases"] == timeline_plan(raw, 1).purchases


def test_metadata_participants_are_the_fallback_mapping() -> None:
    raw = make_match_json("NA1_904")
    timeline = make_timeline_json(raw)
    del timeline["info"]["participants"]
    rows = extract_timeline(timeline, _players(raw))
    assert _rows_by_pid(rows)[4]["purchases"] == timeline_plan(raw, 4).purchases


def test_puuid_mismatch_is_rejected() -> None:
    raw = make_match_json("NA1_905")
    players = [p["puuid"] for p in raw["info"]["participants"]]
    other = make_timeline_json(raw, puuids=[*players[:9], "someone-else"])
    with pytest.raises(TimelineMismatch):
        extract_timeline(other, _players(raw))
    fewer = dict(list(_players(raw).items())[:9])
    with pytest.raises(TimelineMismatch):
        extract_timeline(make_timeline_json(raw), fewer)
    with pytest.raises(TimelineMismatch):
        extract_timeline(make_timeline_json(raw), _players(raw), match_id="NA1_906")


def _broken(mutate) -> dict:
    raw = make_match_json("NA1_907")
    timeline = make_timeline_json(raw)
    mutate(timeline)
    return timeline


@pytest.mark.parametrize(
    "timeline",
    [
        {"status": {"message": "Data not found", "status_code": 404}},
        "nope",
        _broken(lambda t: t["info"].update(frames=[])),
        _broken(lambda t: t["info"].update(frames="x")),
        _broken(lambda t: t["info"]["frames"][1].update(events=[{"type": "ITEM_PURCHASED"}])),
        _broken(
            lambda t: t["info"]["frames"][1]["events"].append(
                {"type": "ITEM_PURCHASED", "timestamp": 70_000, "participantId": 1, "itemId": "x"}
            )
        ),
        _broken(
            lambda t: t["info"]["frames"][1]["events"].append(
                {
                    "type": "SKILL_LEVEL_UP",
                    "timestamp": 70_000,
                    "participantId": 1,
                    "skillSlot": 7,
                    "levelUpType": "NORMAL",
                }
            )
        ),
        _broken(
            lambda t: t["info"]["frames"][1]["events"].append(
                {"type": "ITEM_PURCHASED", "timestamp": 70_000, "participantId": 42, "itemId": 1}
            )
        ),
    ],
)
def test_malformed_timelines_are_rejected(timeline) -> None:
    raw = make_match_json("NA1_907")
    with pytest.raises(InvalidTimeline):
        extract_timeline(timeline, _players(raw))


# --- sampling ----------------------------------------------------------------------------------


def test_match_number() -> None:
    assert match_number("NA1_5123") == 5123
    assert match_number("EUW1_12_9") == 9
    assert match_number("NA1_x") is None and match_number("12") is None


@pytest.mark.parametrize(
    ("match_id", "source", "queue", "remake", "start", "expected"),
    [
        ("NA1_1", "roster", 420, False, SEASON, True),
        ("NA1_2", "roster", 440, False, SEASON + timedelta(days=9), True),
        ("NA1_3", "crawl", 420, False, SEASON, True),
        ("NA1_4", "crawl", 420, False, SEASON, False),
        ("NA1_300", "crawl", 440, False, SEASON, True),
        ("NA1_1", "roster", 400, False, SEASON, False),  # normal draft
        ("NA1_1", "roster", 1700, False, SEASON, False),  # Arena
        ("NA1_1", "roster", 420, True, SEASON, False),  # remake
        ("NA1_1", "roster", 420, False, SEASON - timedelta(seconds=1), False),
        ("DEMO_3", "roster", 420, False, SEASON, False),
    ],
)
def test_sampling_rule(settings, match_id, source, queue, remake, start, expected) -> None:
    settings = settings.model_copy(update={"season_start": SEASON, "timeline_sample": 3})
    assert timeline_sampled(match_id, source, queue, remake, start, settings) is expected
    off = settings.model_copy(update={"timelines": False})
    assert timeline_sampled(match_id, source, queue, remake, start, off) is False


# --- ingestion marks pending -------------------------------------------------------------------


@pytest.fixture
def riot(settings) -> IngestFakeRiot:
    return IngestFakeRiot(settings)


@pytest.fixture
def ctx(clean_db, settings, session_factory, riot):
    return make_ctx(settings, session_factory, riot)


async def _states(session_factory) -> dict[str, tuple[str | None, int, int]]:
    async with session_factory() as s:
        rows = await s.execute(
            select(
                Match.match_id, Match.timeline_state, Match.timeline_attempts, Match.champ_rollup
            )
        )
        return {r[0]: (r[1], r[2], r[3]) for r in rows}


async def test_ingestion_marks_sampled_games_pending(ctx, session_factory) -> None:
    games = [
        (make_match_json("NA1_10", start=recent(5)), "roster"),
        (make_match_json("NA1_11", start=recent(5), queue_id=440), "roster"),
        (make_match_json("NA1_12", start=recent(5), queue_id=400), "roster"),
        (make_match_json("NA1_13", start=recent(5), remake=True, duration_s=200), "roster"),
        (make_match_json("NA1_15", start=recent(5)), "crawl"),
        (make_match_json("NA1_16", start=recent(5)), "crawl"),
    ]
    async with session_scope(session_factory) as s:
        for raw, source in games:
            await ingest_match_json(ctx, s, raw, enqueue_events=False, source=source)
    states = {k: v[0] for k, v in (await _states(session_factory)).items()}
    assert states == {
        "NA1_10": "pending",
        "NA1_11": "pending",
        "NA1_12": None,
        "NA1_13": None,
        "NA1_15": "pending",  # 15 % 3 == 0
        "NA1_16": None,
    }


async def test_ingestion_with_timelines_off_marks_nothing(
    clean_db, settings, session_factory, riot
) -> None:
    ctx = make_ctx(settings.model_copy(update={"timelines": False}), session_factory, riot)
    async with session_scope(session_factory) as s:
        await ingest_match_json(ctx, s, make_match_json("NA1_20", start=recent(5)))
    assert (await _states(session_factory))["NA1_20"][0] is None


# --- crawler backlog ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def plenty_of_disk(monkeypatch):
    monkeypatch.setattr(crawler_module, "_free_gib", lambda _path: 1000.0)


def _crawler(ctx, *, sleep=None, stop=None, poll_active=None) -> Crawler:
    stop = stop or asyncio.Event()

    async def fast_sleep(_seconds: float) -> bool:
        await asyncio.sleep(0)
        return stop.is_set()

    return Crawler(
        ctx,
        stop,
        poll_active or asyncio.Event(),
        budget=CrawlBudget(ctx.riot),
        sleep=sleep or fast_sleep,
        clock=lambda: 1000.0,
    )


async def _store(ctx, raw: dict, *, source: str = "roster", rollup: int | None = None) -> str:
    async with session_scope(ctx.session_factory) as s:
        await ingest_match_json(ctx, s, raw, enqueue_events=False, source=source)
        match_id = raw["metadata"]["matchId"]
        values = {"timeline_state": "pending"}
        if rollup is not None:
            values["champ_rollup"] = rollup
        await s.execute(update(Match).where(Match.match_id == match_id).values(**values))
    return match_id


async def _timeline_rows(session_factory, match_id: str) -> dict[int, MatchTimelinePlayer]:
    async with session_factory() as s:
        rows = await s.scalars(
            select(MatchTimelinePlayer).where(MatchTimelinePlayer.match_id == match_id)
        )
        return {row.participant_id: row for row in rows}


async def test_backlog_stores_timelines_and_hands_them_to_the_rollup(
    ctx, riot, session_factory
) -> None:
    counted = make_match_json("NA1_30", start=recent(5))
    fresh = make_match_json("NA1_31", start=recent(4))
    await _store(ctx, counted, rollup=1)
    await _store(ctx, fresh, rollup=0)
    riot.add_timeline(make_timeline_json(counted))
    riot.add_timeline(make_timeline_json(fresh))

    crawler = _crawler(ctx)
    report = await crawler.step()

    assert (report.timelines_tried, report.timelines_stored) == (2, 2)
    states = await _states(session_factory)
    assert states["NA1_30"] == ("ok", 0, 3)  # counted without a timeline -> 3
    assert states["NA1_31"] == ("ok", 0, 0)  # not counted yet: the rollup sees it with one
    rows = await _timeline_rows(session_factory, "NA1_30")
    assert set(rows) == set(range(1, 11))
    plan = timeline_plan(counted, 1)
    assert rows[1].purchases == plan.purchases
    assert rows[1].purchase_s == plan.purchase_s
    assert rows[1].skill_order == plan.skill_order
    assert crawler.timelines_fetched == 2 and crawler.timelines_fetched_today == 2
    heartbeat = crawler.heartbeat()
    assert heartbeat["timelines_fetched_today"] == 2 and heartbeat["timelines_pending"] == 0

    # nothing pending any more: no further timeline calls
    await crawler.step()
    assert len(riot.calls_to("match_timeline")) == 2


async def test_backlog_404_marks_missing(ctx, riot, session_factory) -> None:
    await _store(ctx, make_match_json("NA1_40", start=recent(5)), rollup=1)
    report = await _crawler(ctx).step()
    assert report.timelines_stored == 0
    assert (await _states(session_factory))["NA1_40"] == ("missing", 0, 1)
    assert await _timeline_rows(session_factory, "NA1_40") == {}


async def test_backlog_gives_up_after_three_failures(ctx, riot, session_factory) -> None:
    await _store(ctx, make_match_json("NA1_50", start=recent(5)))
    riot.fail("match_timeline", RiotUnavailable("HTTP 503"), times=None)
    crawler = _crawler(ctx)
    for attempts in (1, 2):
        report = await crawler.step()
        assert (await _states(session_factory))["NA1_50"][:2] == ("pending", attempts)
        assert report.errors and "timeline NA1_50" in report.errors[0]
    await crawler.step()
    assert (await _states(session_factory))["NA1_50"][:2] == ("failed", 3)
    await crawler.step()
    assert len(riot.calls_to("match_timeline")) == 3


async def test_invalid_payloads_count_as_attempts(ctx, riot, session_factory) -> None:
    raw = make_match_json("NA1_51", start=recent(5))
    await _store(ctx, raw)
    broken = make_timeline_json(raw)
    broken["info"]["frames"][1]["events"].append(
        {"type": "ITEM_PURCHASED", "timestamp": 70_000, "participantId": 1, "itemId": None}
    )
    riot.add_timeline(broken)
    await _crawler(ctx).step()
    assert (await _states(session_factory))["NA1_51"][:2] == ("pending", 1)
    assert await _timeline_rows(session_factory, "NA1_51") == {}


async def test_rate_limits_and_key_errors_are_not_attempts(ctx, riot, session_factory) -> None:
    raw = make_match_json("NA1_60", start=recent(5))
    await _store(ctx, raw)
    riot.add_timeline(make_timeline_json(raw))
    crawler = _crawler(ctx)

    riot.fail("match_timeline", RiotRateLimited(retry_after=3))
    with pytest.raises(RiotRateLimited):
        await crawler.step()
    riot.fail("match_timeline", RiotForbidden("expired"))
    with pytest.raises(RiotForbidden):
        await crawler.step()
    assert (await _states(session_factory))["NA1_60"][:2] == ("pending", 0)

    await crawler.step()
    assert (await _states(session_factory))["NA1_60"][:2] == ("ok", 0)


async def test_puuid_mismatch_fails_at_once(ctx, riot, session_factory) -> None:
    raw = make_match_json("NA1_70", start=recent(5))
    await _store(ctx, raw, rollup=1)
    players = [p["puuid"] for p in raw["info"]["participants"]]
    riot.add_timeline(make_timeline_json(raw, puuids=[*players[:9], "stranger"]))
    await _crawler(ctx).step()
    assert (await _states(session_factory))["NA1_70"] == ("failed", 0, 1)
    assert await _timeline_rows(session_factory, "NA1_70") == {}


async def test_roster_games_come_first_newest_first_and_before_the_crawl(
    ctx, riot, session_factory, monkeypatch
) -> None:
    await _store(ctx, make_match_json("NA1_81", start=recent(30)), source="crawl")
    await _store(ctx, make_match_json("NA1_82", start=recent(3)), source="crawl")
    await _store(ctx, make_match_json("NA1_83", start=recent(20)))
    await _store(ctx, make_match_json("NA1_84", start=recent(40)))
    # already fetched / not sampled games are not in the backlog
    ok = await _store(ctx, make_match_json("NA1_85", start=recent(2)))
    async with session_scope(session_factory) as s:
        await s.execute(update(Match).where(Match.match_id == ok).values(timeline_state="ok"))
    # a crawlable player, so the step goes on to crawl after the timelines
    stranger = make_match_json("NA1_86", [spec("stranger-1", "S", "NA1")], start=recent(1))
    riot.add_match(stranger)
    async with session_scope(session_factory) as s:
        s.add(CrawlPlayer(puuid="stranger-1", found_via="match"))

    monkeypatch.setattr(crawler_module, "TIMELINE_BATCH", 3)
    crawler = _crawler(ctx)
    await crawler.step()

    fetched = [c.args[0] for c in riot.calls_to("match_timeline")]
    assert fetched == ["NA1_83", "NA1_84", "NA1_82"]
    methods = [c.method for c in riot.calls if c.method != "league_exp_entries"]
    assert methods[:3] == ["match_timeline"] * 3
    assert "match_ids_by_puuid" in methods[3:]
    assert crawler.timelines_pending == 1

    await crawler.step()
    fetched = [c.args[0] for c in riot.calls_to("match_timeline")]
    assert fetched[3] == "NA1_81"


async def test_timeline_fetches_wait_for_the_budget_gate(ctx, riot, session_factory) -> None:
    await _store(ctx, make_match_json("NA1_90", start=recent(5)))
    stop = asyncio.Event()
    poll_active = asyncio.Event()
    poll_active.set()  # a poll tick is running: the crawler must not send anything
    waits = 0

    async def sleep(_seconds: float) -> bool:
        nonlocal waits
        waits += 1
        if waits >= 3:
            stop.set()
        await asyncio.sleep(0)
        return stop.is_set()

    crawler = _crawler(ctx, sleep=sleep, stop=stop, poll_active=poll_active)
    with pytest.raises(crawler_module._Stopped):
        await crawler.step()
    assert riot.calls_to("match_timeline") == []

    # no headroom left over the reserve: same
    poll_active.clear()
    stop.clear()
    waits = 0
    riot.headroom = 0
    with pytest.raises(crawler_module._Stopped):
        await crawler.step()
    assert riot.calls_to("match_timeline") == []
    assert (await _states(session_factory))["NA1_90"][:2] == ("pending", 0)


async def test_demo_games_and_disabled_timelines_make_no_calls(
    clean_db, settings, session_factory, riot
) -> None:
    ctx = make_ctx(settings, session_factory, riot)
    raw = make_match_json("DEMO_3", start=recent(5))
    await _store(ctx, raw)
    await _crawler(ctx).step()
    assert (await _states(session_factory))["DEMO_3"][0] == "missing"

    await _store(ctx, make_match_json("NA1_91", start=recent(5)))
    off = make_ctx(settings.model_copy(update={"timelines": False}), session_factory, riot)
    await _crawler(off).step()
    assert riot.calls_to("match_timeline") == []
    assert (await _states(session_factory))["NA1_91"][0] == "pending"


async def test_crawled_games_are_sampled_for_timelines(ctx, riot, session_factory) -> None:
    for number in (300, 301):
        riot.add_match(make_match_json(f"NA1_{number}", [spec("stranger-2")], start=recent(2)))
    async with session_scope(session_factory) as s:
        s.add(CrawlPlayer(puuid="stranger-2", found_via="match"))
    crawler = _crawler(ctx)
    await crawler.step()
    states = await _states(session_factory)
    assert states["NA1_300"][0] == "pending" and states["NA1_301"][0] is None
    # the next step fetches it before crawling anyone else
    riot.add_timeline(make_timeline_json(riot.matches["NA1_300"]))
    await crawler.step()
    assert (await _states(session_factory))["NA1_300"][0] == "ok"


async def test_heartbeat_restores_todays_timeline_count(ctx, session_factory) -> None:
    crawler = _crawler(ctx)
    crawler.timelines_fetched_today = 7
    await crawler.write_heartbeat()
    async with session_factory() as s:
        state = await s.scalar(select(AppState.value).where(AppState.key == STATE_KEY))
    assert state["timelines_fetched_today"] == 7

    again = _crawler(ctx)
    await again._restore()
    assert again.timelines_fetched_today == 7


# --- crawl status ------------------------------------------------------------------------------


async def test_crawl_status_counts_timeline_states(empty_frontier, session_factory, cli_env):  # noqa: F811
    from tests.test_ai_support import insert_matches

    raws = [make_match_json(f"NA1_{900 + i}", start=recent(10)) for i in range(5)]
    ids = await insert_matches(session_factory, copy.deepcopy(raws))
    states = ["pending", "pending", "ok", "missing", "failed"]
    async with session_factory() as s:
        for match_id, state in zip(ids, states, strict=True):
            await s.execute(
                update(Match).where(Match.match_id == match_id).values(timeline_state=state)
            )
        await s.commit()
    result = await asyncio.to_thread(CliRunner().invoke, app, ["crawl", "status"])
    assert result.exit_code == 0, result.output
    assert "match timelines: 2 pending, 1 ok, 1 missing, 1 failed" in result.output
