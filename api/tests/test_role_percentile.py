"""Score within role: percentile math, the population, the cache and the API fields."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from hextrack.db.models import MatchParticipant
from hextrack.stats import role_percentile
from hextrack.stats.role_percentile import (
    EMPTY_TABLE,
    RolePercentileCache,
    RolePercentileTable,
    mean_percentiles,
    percentile_of,
)
from tests.factories import filler_specs, make_match_json, spec
from tests.fakes import install_fakes
from tests.test_api_support import StubScorer, add_match, add_model, add_summoner

A, B = "puuid-rp-a", "puuid-rp-b"
SEASON = datetime(2026, 3, 1, 20, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _scores(raw: dict, values: list[float]) -> dict[str, float]:
    """Slot i gets values[i] (slots 0-4 blue TOP..UTILITY, 5-9 red TOP..UTILITY)."""
    return {p["puuid"]: values[i] for i, p in enumerate(raw["info"]["participants"])}


async def _seed_population(session, *, other_version: bool = True) -> None:
    """Two ranked games: TOP scores 0.1, 0.3 (game 1) and 0.5, 0.7 (game 2), and so on for
    every position; plus games that must NOT count (``other_version`` False leaves out the
    game scored by v0, which makes a v1 table provisional)."""
    first = make_match_json("NA1_1", start=SEASON)
    await add_match(
        session, first, scores=_scores(first, [0.1, 0.2, 0.3, 0.4, 0.5, 0.3, 0.4, 0.5, 0.6, 0.7])
    )
    second = make_match_json("NA1_2", start=SEASON + timedelta(hours=1), queue_id=440)
    await add_match(
        session, second, scores=_scores(second, [0.5, 0.5, 0.5, 0.5, 0.5, 0.7, 0.7, 0.7, 0.7, 0.7])
    )
    # Not in the population: a normal game, a remake, another model version, unscored lines,
    # and UNKNOWN positions.
    normal = make_match_json("NA1_3", queue_id=400, start=SEASON)
    await add_match(session, normal, scores=_scores(normal, [0.01] * 10))
    remake = make_match_json("NA1_4", duration_s=200, start=SEASON)
    await add_match(session, remake, scores=_scores(remake, [0.02] * 10))
    if other_version:
        other = make_match_json("NA1_5", start=SEASON)
        await add_match(session, other, scores=_scores(other, [0.03] * 10), model_version="v0")
    await add_match(session, make_match_json("NA1_6", start=SEASON))
    unknown = make_match_json(
        "NA1_7",
        [spec(f"unk-{i}", teamPosition="") for i in range(10)],
        start=SEASON,
    )
    await add_match(session, unknown, scores=_scores(unknown, [0.04] * 10))
    await session.commit()


# --- pure math -------------------------------------------------------------------------------


def test_percentile_of_counts_strictly_lower_scores():
    population = [0.1, 0.2, 0.3, 0.4]
    assert percentile_of(population, 0.25) == 50.0
    assert percentile_of(population, 0.3) == 50.0  # equal scores are not "worse"
    assert percentile_of(population, 0.1) == 0.0
    assert percentile_of(population, 0.05) == 0.0
    assert percentile_of(population, 0.4) == 75.0
    assert percentile_of(population, 0.99) == 100.0
    assert percentile_of([0.1, 0.2, 0.3], 0.25) == pytest.approx(66.67)
    assert percentile_of([], 0.5) is None


def test_table_lookups():
    table = RolePercentileTable(version="v1", scores={"TOP": [0.1, 0.5], "UTILITY": [0.2]})
    assert table.percentile("TOP", 0.3) == 50.0
    assert table.percentile("UTILITY", 0.9) == 100.0
    assert table.percentile("UNKNOWN", 0.3) is None
    assert table.percentile("", 0.3) is None
    assert table.percentile(None, 0.3) is None
    assert table.percentile("TOP", None) is None
    assert table.percentile("JUNGLE", 0.3) is None  # a position with no scored games
    assert table.for_row("TOP", 0.3, "v1") == 50.0
    assert table.for_row("TOP", 0.3, "v0") is None
    assert table.for_row("TOP", 0.3, None) is None
    assert table.size == 3
    assert EMPTY_TABLE.percentile("TOP", 0.5) is None
    assert EMPTY_TABLE.for_row("TOP", 0.5, None) is None


def test_mean_percentiles_skips_lines_without_one():
    table = RolePercentileTable(version="v1", scores={"TOP": [0.1, 0.5], "MIDDLE": [0.2, 0.4]})
    rows = [
        ("a", "TOP", 0.3),  # 50
        ("a", "MIDDLE", 0.9),  # 100
        ("a", "UNKNOWN", 0.9),  # skipped
        ("b", "TOP", None),  # skipped
    ]
    assert mean_percentiles(rows, table) == {"a": 75.0}


# --- population and cache --------------------------------------------------------------------


async def test_population_is_ranked_non_remake_active_model_known_positions(session):
    await _seed_population(session)
    cache = RolePercentileCache()
    table = await cache.ensure_loaded(session, model_version="v1")
    assert table.version == "v1"
    assert dict(table.scores) == {
        "TOP": [0.1, 0.3, 0.5, 0.7],
        "JUNGLE": [0.2, 0.4, 0.5, 0.7],
        "MIDDLE": [0.3, 0.5, 0.5, 0.7],
        "BOTTOM": [0.4, 0.5, 0.6, 0.7],
        "UTILITY": [0.5, 0.5, 0.7, 0.7],
    }
    assert table.percentile("TOP", 0.5) == 50.0
    assert cache.percentile("UTILITY", 0.7) == 50.0  # the cache answers from its latest table
    assert cache.version == "v1"


async def test_ensure_loaded_defaults_to_the_active_model(session):
    await _seed_population(session)
    cache = RolePercentileCache()
    table = await cache.ensure_loaded(session)
    assert table is EMPTY_TABLE and cache.loads == 0  # no ai_models row is active

    await add_model(session, "v0", active=True)
    await session.commit()
    table = await cache.ensure_loaded(session)
    assert table.version == "v0" and table.scores["TOP"] == [0.03, 0.03]
    assert await cache.ensure_loaded(session, model_version=None) is EMPTY_TABLE


async def test_cache_refreshes_after_15_minutes_or_a_version_change(session):
    await _seed_population(session, other_version=False)
    clock = FakeClock()
    cache = RolePercentileCache(clock=clock)
    first = await cache.ensure_loaded(session, model_version="v1")
    assert cache.loads == 1 and not first.provisional

    # New scored games do not show up until the table expires.
    extra = make_match_json("NA1_8", start=SEASON + timedelta(days=1))
    await add_match(session, extra, scores=_scores(extra, [0.9] * 10))
    await session.commit()
    clock.now += role_percentile.REFRESH_SECONDS - 1
    assert await cache.ensure_loaded(session, model_version="v1") is first
    assert cache.loads == 1

    clock.now += 1
    refreshed = await cache.ensure_loaded(session, model_version="v1")
    assert cache.loads == 2
    assert refreshed.scores["TOP"] == [0.1, 0.3, 0.5, 0.7, 0.9, 0.9]

    # Another model version is a different population, loaded straight away ...
    other = await cache.ensure_loaded(session, model_version="v0")
    assert cache.loads == 3 and other.version == "v0" and other.scores == {}
    # ... and switching back reuses the still-fresh v1 table.
    assert await cache.ensure_loaded(session, model_version="v1") is refreshed
    assert cache.loads == 3

    cache.invalidate()
    assert cache.table is EMPTY_TABLE
    await cache.ensure_loaded(session, model_version="v1")
    assert cache.loads == 4


async def test_half_rescored_population_is_provisional(session):
    """While stored rows still carry another version's score (a model was just activated
    and the rescore is running), the table is only reused for a minute: a population read
    mid-rescore must not stand for 15 minutes."""
    await _seed_population(session)  # NA1_5 is still scored by v0
    clock = FakeClock()
    cache = RolePercentileCache(clock=clock)
    partial = await cache.ensure_loaded(session, model_version="v1")
    assert partial.pending == 10 and partial.provisional
    assert partial.scores["TOP"] == [0.1, 0.3, 0.5, 0.7]

    clock.now += role_percentile.PROVISIONAL_SECONDS - 1
    assert await cache.ensure_loaded(session, model_version="v1") is partial

    # The rescore finishes: NA1_5 now carries v1 scores.
    await session.execute(
        update(MatchParticipant)
        .where(MatchParticipant.match_id == "NA1_5")
        .values(model_version="v1", ai_score=0.9)
    )
    await session.commit()
    clock.now += 1
    complete = await cache.ensure_loaded(session, model_version="v1")
    assert cache.loads == 2 and not complete.provisional
    assert complete.scores["TOP"] == [0.1, 0.3, 0.5, 0.7, 0.9, 0.9]

    # A complete table is kept for the full 15 minutes.
    clock.now += role_percentile.REFRESH_SECONDS - 1
    assert await cache.ensure_loaded(session, model_version="v1") is complete


async def test_cache_reloads_for_another_engine(session, settings):
    from hextrack.db.engine import make_async_engine, make_session_factory

    await _seed_population(session)
    cache = RolePercentileCache()
    await cache.ensure_loaded(session, model_version="v1")
    engine = make_async_engine(settings)
    try:
        async with make_session_factory(engine)() as other_session:
            await cache.ensure_loaded(other_session, model_version="v1")
            assert cache.loads == 2
            await cache.ensure_loaded(other_session, model_version="v1")
            assert cache.loads == 2
    finally:
        await engine.dispose()


async def test_concurrent_requests_load_once(session, session_factory):
    await _seed_population(session)
    cache = RolePercentileCache()

    async def lookup() -> float | None:
        async with session_factory() as own:
            table = await cache.ensure_loaded(own, model_version="v1")
            return table.percentile("TOP", 0.5)

    results = await asyncio.gather(*(lookup() for _ in range(8)))
    assert results == [50.0] * 8
    assert cache.loads == 1


# --- API fields ------------------------------------------------------------------------------


async def _seed_players(session) -> None:
    """A (tracked, TOP) and B (tracked, UTILITY) on the blue team of two ranked games;
    a normal game where A has an UNKNOWN position."""
    await add_summoner(session, A, "Alpha", "NA1", tracked=True)
    await add_summoner(session, B, "Bravo", "NA1", tracked=True)
    for n, start in ((1, SEASON), (2, SEASON + timedelta(hours=1))):
        slots = [spec(A, "Alpha", "NA1"), *filler_specs(f"NA1_{n}", 3, offset=1)]
        slots += [spec(B, "Bravo", "NA1")] + filler_specs(f"NA1_{n}", 5, offset=5)
        raw = make_match_json(f"NA1_{n}", slots, start=start)
        values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.3, 0.4, 0.5, 0.6, 0.7] if n == 1 else [0.5] * 10
        await add_match(session, raw, scores=_scores(raw, values))
    unknown = make_match_json(
        "NA1_3",
        [spec(A, "Alpha", "NA1", teamPosition="")],
        start=SEASON + timedelta(hours=2),
        queue_id=400,
    )
    await add_match(session, unknown, scores=_scores(unknown, [0.9] * 10))
    await session.commit()


async def test_match_history_and_detail_carry_role_percentiles(client, session):
    await add_model(session, "v1", active=True)
    await _seed_players(session)
    # TOP population: 0.1, 0.3 (game 1), 0.5, 0.5 (game 2).
    body = (await client.get(f"/api/v1/summoners/{A}/matches")).json()
    by_match = {item["match_id"]: item for item in body["items"]}
    assert by_match["NA1_1"]["me"]["ai_role_percentile"] == 0.0
    assert by_match["NA1_2"]["me"]["ai_role_percentile"] == 50.0
    # UNKNOWN position -> null, even though the line is scored.
    unknown_me = by_match["NA1_3"]["me"]
    assert unknown_me["ai_score"] == pytest.approx(0.9)
    assert unknown_me["team_position"] == "UNKNOWN"
    assert unknown_me["ai_role_percentile"] is None

    detail = (await client.get("/api/v1/matches/NA1_1")).json()
    lines = {p["puuid"]: p for team in detail["teams"] for p in team["participants"]}
    # UTILITY population: B 0.5 and red 0.7 (game 1), B 0.5 and red 0.5 (game 2).
    red_utility = next(
        p for p in lines.values() if p["team_id"] == 200 and p["team_position"] == "UTILITY"
    )
    assert red_utility["ai_role_percentile"] == 75.0
    assert lines[B]["ai_role_percentile"] == 0.0
    assert all(p["ai_role_percentile"] is not None for p in lines.values())


async def test_other_model_versions_and_unscored_lines_have_no_percentile(client, session):
    await add_model(session, "v2", active=True)
    await _seed_players(session)  # every score is from v1
    body = (await client.get(f"/api/v1/summoners/{A}/matches")).json()
    assert all(item["me"]["ai_role_percentile"] is None for item in body["items"])
    profile = (await client.get("/api/v1/summoners/by-riot-id/Alpha/NA1")).json()
    assert profile["stats"]["avg_ai_role_percentile"] is None


async def test_profile_and_leaderboard_average_role_percentiles(client, session):
    await add_model(session, "v1", active=True)
    await _seed_players(session)
    # A (TOP): 0.0 and 50.0 -> 25.0; the normal game does not count (not ranked).
    # B (UTILITY): 0.5 twice, and no UTILITY line scored lower -> 0.0.
    profile = (await client.get("/api/v1/summoners/by-riot-id/Alpha/NA1")).json()
    assert profile["stats"]["avg_ai_role_percentile"] == 25.0

    board = {e["puuid"]: e for e in (await client.get("/api/v1/leaderboard")).json()["entries"]}
    assert board[A]["avg_ai_role_percentile"] == 25.0
    assert board[B]["avg_ai_role_percentile"] == 0.0


async def test_loaded_scorer_counts_as_the_active_model(app, client, session):
    await _seed_players(session)  # no ai_models row
    body = (await client.get(f"/api/v1/summoners/{A}/matches")).json()
    # Without any active model, history falls back to the player's latest scored version.
    assert {item["me"]["ai_role_percentile"] for item in body["items"]} == {0.0, 50.0, None}

    detail = (await client.get("/api/v1/matches/NA1_2")).json()
    assert all(
        p["ai_role_percentile"] is None for team in detail["teams"] for p in team["participants"]
    )
    board = (await client.get("/api/v1/leaderboard")).json()
    assert all(e["avg_ai_role_percentile"] is None for e in board["entries"])

    install_fakes(app, scorer=StubScorer("v1"))
    detail = (await client.get("/api/v1/matches/NA1_2")).json()
    assert all(
        p["ai_role_percentile"] is not None
        for team in detail["teams"]
        for p in team["participants"]
    )
    board = {e["puuid"]: e for e in (await client.get("/api/v1/leaderboard")).json()["entries"]}
    assert board[A]["avg_ai_role_percentile"] == 25.0
