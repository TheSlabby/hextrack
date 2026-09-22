"""ingest.ondemand: any-player lookup and the Update button (cooldown / partial)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from hextrack.db.engine import session_scope
from hextrack.db.models import RankSnapshot, Summoner
from hextrack.ingest import ondemand, service
from hextrack.ingest.ondemand import get_or_resolve_summoner, refresh_on_demand
from hextrack.ingest.service import store_identity
from hextrack.riot.errors import (
    RiotBadResponse,
    RiotForbidden,
    RiotNotFound,
    RiotRateLimited,
    RiotUnavailable,
)
from tests.factories import match_series
from tests.test_ingest_support import (
    IngestFakeRiot,
    count,
    make_ctx,
    snapshots_of,
    stored_match_ids,
)


@pytest.fixture
def riot(settings) -> IngestFakeRiot:
    riot = IngestFakeRiot(settings)
    riot.add_account("Faker Fan", "KR1", puuid="fan", profile_icon_id=588, level=77)
    riot.add_league_entry("fan", "RANKED_SOLO_5x5", "EMERALD", "III", 41)
    return riot


@pytest.fixture
def ctx(clean_db, settings, session_factory, riot):
    tuned = settings.model_copy(
        update={"ondemand_cooldown_seconds": 120, "ondemand_max_matches": 3, "poll_match_count": 20}
    )
    return make_ctx(tuned, session_factory, riot)


def _add_games(riot: IngestFakeRiot, n: int) -> list[str]:
    series = match_series("fan", n, game_name="Faker Fan", tag_line="KR1")
    for raw in series:
        riot.add_match(raw)
    return [r["metadata"]["matchId"] for r in reversed(series)]  # newest first


async def _age_refresh(session, seconds: float) -> None:
    await session.execute(
        update(Summoner).values(
            last_refreshed_at=Summoner.last_refreshed_at - timedelta(seconds=seconds)
        )
    )
    await session.commit()


# --- resolve ---------------------------------------------------------------------------------


async def test_unknown_player_is_resolved_and_refreshed(ctx, riot, session):
    newest = _add_games(riot, 5)

    summoner = await get_or_resolve_summoner(ctx, session, "  faker   FAN ", "kr1")
    await session.commit()

    assert summoner is not None
    assert (summoner.puuid, summoner.game_name, summoner.tag_line) == ("fan", "Faker Fan", "KR1")
    assert (summoner.profile_icon_id, summoner.summoner_level) == (588, 77)
    assert summoner.is_tracked is False and summoner.last_refreshed_at is not None
    assert len(await snapshots_of(session, "fan")) == 1
    # first bounded refresh: the 3 newest matches only
    assert await stored_match_ids(session) == set(newest[:3])
    assert riot.calls_to("account_by_puuid") == []


async def test_known_player_is_served_from_the_db(ctx, riot, session):
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    riot.calls.clear()

    summoner = await get_or_resolve_summoner(ctx, session, "FAKER FAN", "kr1")

    assert summoner is not None and summoner.puuid == "fan"
    assert riot.calls == []


async def test_unknown_riot_id_returns_none(ctx, riot, session):
    assert await get_or_resolve_summoner(ctx, session, "Nobody", "NA1") is None
    assert await get_or_resolve_summoner(ctx, session, "   ", "NA1") is None
    assert await count(session, Summoner) == 0


async def test_account_without_league_profile_returns_none(ctx, riot, session):
    riot.add_account("Valorant Only", "VAL", puuid="val")
    del riot.summoners["val"]

    assert await get_or_resolve_summoner(ctx, session, "Valorant Only", "VAL") is None
    await session.commit()
    assert await count(session, Summoner) == 0


async def test_riot_errors_propagate_and_leave_nothing(ctx, riot, session):
    riot.fail("league_entries_by_puuid", RiotForbidden("Forbidden", status=403))
    with pytest.raises(RiotForbidden):
        await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    assert await count(session, Summoner) == 0

    riot.fail("account_by_riot_id", RiotRateLimited(retry_after=2))
    with pytest.raises(RiotRateLimited):
        await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")


async def test_renamed_player_keeps_their_row(ctx, riot, session):
    session.add(
        Summoner(puuid="fan", game_name="Old Name", tag_line="OLD", platform="na1", is_tracked=True)
    )
    await session.commit()

    summoner = await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()

    assert summoner is not None and summoner.puuid == "fan"
    assert (summoner.game_name, summoner.tag_line, summoner.is_tracked) == (
        "Faker Fan",
        "KR1",
        True,
    )
    assert await count(session, Summoner) == 1


async def test_update_button_picks_up_renames(ctx, riot, session):
    session.add(Summoner(puuid="fan", game_name="Old Name", tag_line="OLD", platform="na1"))
    await session.commit()

    outcome = await refresh_on_demand(ctx, session, "fan")
    await session.commit()

    assert outcome.status == "ok"
    fan = await session.get(Summoner, "fan", populate_existing=True)
    assert fan is not None and (fan.game_name, fan.tag_line) == ("Faker Fan", "KR1")
    assert len(riot.calls_to("account_by_puuid")) == 1


async def test_store_identity_frees_a_stale_riot_id(ctx, riot, session):
    # "old" used to be Faker Fan#KR1 and renamed to Moved On#NEW; "fan" took the name.
    riot.add_account("Moved On", "NEW", puuid="old")
    session.add(Summoner(puuid="old", game_name="faker fan", tag_line="kr1", platform="na1"))
    await session.commit()

    await store_identity(ctx, session, puuid="fan", game_name="Faker Fan", tag_line="KR1")
    await session.commit()

    old = await session.get(Summoner, "old", populate_existing=True)
    fan = await session.get(Summoner, "fan", populate_existing=True)
    assert old is not None and (old.game_name, old.tag_line) == ("Moved On", "NEW")
    assert fan is not None and (fan.game_name, fan.tag_line) == ("Faker Fan", "KR1")


async def test_store_identity_parks_the_riot_id_of_a_deleted_account(ctx, riot, session):
    session.add(Summoner(puuid="gone1234x", game_name="Faker Fan", tag_line="KR1", platform="na1"))
    await session.commit()

    await store_identity(ctx, session, puuid="fan", game_name="Faker Fan", tag_line="KR1")
    await session.commit()

    gone = await session.get(Summoner, "gone1234x", populate_existing=True)
    assert gone is not None and gone.tag_line == "KR1~gone1234"
    found = await get_or_resolve_summoner(ctx, session, "faker fan", "kr1")
    assert found is not None and found.puuid == "fan"


async def test_conflicting_riot_id_reports_bad_response(ctx, riot, session):
    riot.add_account("Faker Fan", "KR1", puuid="twin")  # Riot says both own the name
    session.add(Summoner(puuid="twin", game_name="Faker Fan", tag_line="KR1", platform="na1"))
    await session.commit()
    with pytest.raises(RiotBadResponse):
        await store_identity(ctx, session, puuid="fan", game_name="Faker Fan", tag_line="KR1")


# --- refresh / cooldown / partial ------------------------------------------------------------


async def test_cooldown_blocks_repeat_refreshes(ctx, riot, session):
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    riot.calls.clear()

    outcome = await refresh_on_demand(ctx, session, "fan")

    assert outcome.status == "cooldown"
    assert outcome.new_matches == 0 and outcome.pending == 0
    summoner = await session.get(Summoner, "fan")
    assert summoner is not None and summoner.last_refreshed_at is not None
    assert outcome.next_allowed_at == summoner.last_refreshed_at + timedelta(seconds=120)
    assert "try again in" in outcome.message
    assert riot.calls == []

    await _age_refresh(session, 121)
    outcome = await refresh_on_demand(ctx, session, "fan")
    assert outcome.status == "ok"
    assert outcome.message == "Already up to date"
    assert outcome.next_allowed_at > datetime.now(UTC) + timedelta(seconds=110)


async def test_zero_cooldown_always_refreshes(ctx, riot, session):
    ctx.settings = ctx.settings.model_copy(update={"ondemand_cooldown_seconds": 0})
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    outcome = await refresh_on_demand(ctx, session, "fan")
    assert outcome.status == "ok"


async def test_partial_when_more_matches_remain(ctx, riot, session):
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    newest = _add_games(riot, 5)
    await _age_refresh(session, 500)

    outcome = await refresh_on_demand(ctx, session, "fan")
    await session.commit()

    assert (outcome.status, outcome.new_matches, outcome.pending) == ("partial", 3, 2)
    assert "2 matches still to fetch" in outcome.message
    assert await stored_match_ids(session) == set(newest[:3])

    await _age_refresh(session, 500)
    outcome = await refresh_on_demand(ctx, session, "fan")
    assert (outcome.status, outcome.new_matches, outcome.pending) == ("ok", 2, 0)
    assert outcome.message == "Updated: 2 new matches"


async def test_partial_when_the_limiter_is_backed_up(ctx, riot, session):
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    _add_games(riot, 2)
    await _age_refresh(session, 500)
    riot.wait_estimate = ondemand.MAX_LIMITER_WAIT_SECONDS + 1

    outcome = await refresh_on_demand(ctx, session, "fan")

    assert (outcome.status, outcome.new_matches, outcome.pending) == ("partial", 0, 2)
    assert "busy" in outcome.message
    # rank was still refreshed
    summoner = await session.get(Summoner, "fan", populate_existing=True)
    assert summoner is not None
    assert datetime.now(UTC) - summoner.last_refreshed_at < timedelta(seconds=30)


@pytest.mark.parametrize("error", [RiotRateLimited(retry_after=5), RiotUnavailable("502")])
async def test_partial_when_riot_fails_midway(ctx, riot, session, error):
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    newest = _add_games(riot, 3)
    await _age_refresh(session, 500)
    real_match = riot.match
    calls = 0

    async def flaky(match_id: str):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error
        return await real_match(match_id)

    riot.match = flaky  # type: ignore[method-assign]
    outcome = await refresh_on_demand(ctx, session, "fan")
    await session.commit()

    assert (outcome.status, outcome.new_matches, outcome.pending) == ("partial", 1, 2)
    assert await stored_match_ids(session) == {newest[0]}


async def test_refresh_errors_propagate(ctx, riot, session):
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    await _age_refresh(session, 500)
    riot.fail("summoner_by_puuid", RiotUnavailable("down"))
    with pytest.raises(RiotUnavailable):
        await refresh_on_demand(ctx, session, "fan")


async def test_refresh_of_unknown_puuid_creates_it(ctx, riot, session):
    outcome = await refresh_on_demand(ctx, session, "fan")
    assert outcome.status == "ok"
    assert (await session.get(Summoner, "fan")) is not None
    with pytest.raises(RiotNotFound):
        await refresh_on_demand(ctx, session, "ghost")


# --- gaps, watermark and budget --------------------------------------------------------------


async def test_repeated_updates_fill_a_gap_bigger_than_one_click(ctx, riot, session):
    """The Update button ingests a bounded number of matches, newest first. Every later
    click lists the same range again, so the older half of a gap is never skipped: before
    the watermark existed, discovery stopped at the first page holding a stored id and
    those games were lost for good ("Already up to date" with games missing)."""
    ctx.settings = ctx.settings.model_copy(
        update={
            "backfill_count": 3,
            "poll_match_count": 3,
            "ondemand_max_matches": 2,
            "ondemand_cooldown_seconds": 0,
        }
    )
    # One old game already stored (a legacy import), then 7 new ones at Riot.
    old = match_series("fan", 1, game_name="Faker Fan", tag_line="KR1")[0]
    riot.add_match(old)
    await service.ingest_match_json(ctx, session, old)
    session.add(Summoner(puuid="fan", game_name="Faker Fan", tag_line="KR1", platform="na1"))
    await session.commit()
    newest = _add_games(riot, 8)  # includes the stored one, newest first

    for _ in range(6):
        outcome = await refresh_on_demand(ctx, session, "fan")
        await session.commit()
        if outcome.status == "ok":
            break

    assert outcome.status == "ok" and outcome.pending == 0
    assert await stored_match_ids(session) == set(newest)
    # Everything is stored, so discovery has a watermark now and lists only from there.
    summoner = await session.get(Summoner, "fan", populate_existing=True)
    assert summoner is not None and summoner.synced_through is not None
    assert await service.discover_matches(ctx, session, "fan", backfill=False) == []


async def test_watermark_survives_a_rate_limit_in_the_middle_of_a_gap(ctx, riot, session):
    ctx.settings = ctx.settings.model_copy(
        update={"backfill_count": 3, "ondemand_max_matches": 10, "ondemand_cooldown_seconds": 0}
    )
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    ids = _add_games(riot, 5)
    real_match = riot.match
    calls = 0

    async def flaky(match_id: str):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RiotRateLimited(retry_after=5)
        return await real_match(match_id)

    riot.match = flaky  # type: ignore[method-assign]
    first = await refresh_on_demand(ctx, session, "fan")
    await session.commit()
    assert first.status == "partial" and await stored_match_ids(session) == set(ids[:2])
    # Nothing is written off: the two games below the failure are still missing.
    summoner = await session.get(Summoner, "fan", populate_existing=True)
    assert summoner is not None and summoner.synced_through is None

    riot.match = real_match  # type: ignore[method-assign]
    second = await refresh_on_demand(ctx, session, "fan")
    await session.commit()
    assert second.status == "ok"
    assert await stored_match_ids(session) == set(ids)


async def test_update_does_not_page_a_whole_season(ctx, riot, session):
    """A player who comes back after months has a season of games between their last stored
    one and now. One click lists two pages of 100 and answers, instead of walking the whole
    season 20 ids at a time (50 requests out of a budget of 100 per two minutes)."""
    ctx.settings = ctx.settings.model_copy(
        update={"backfill_count": 100, "ondemand_max_matches": 2, "ondemand_cooldown_seconds": 0}
    )
    _add_games(riot, 1)  # one old game, fetched by the first lookup
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    _add_games(riot, 250)  # ...then a season of games while nobody looked
    riot.calls.clear()

    outcome = await refresh_on_demand(ctx, session, "fan")
    await session.commit()

    listings = riot.calls_to("match_ids_by_puuid")
    assert len(listings) == ondemand.MAX_LISTED_IDS // ctx.settings.backfill_count == 2
    assert outcome.status == "partial" and outcome.new_matches == 2
    assert outcome.pending == ondemand.MAX_LISTED_IDS - 2


async def test_rank_is_committed_before_any_match_is_fetched(ctx, riot, session, session_factory):
    """The refresh holds the per-summoner advisory lock and the summoner row; keeping them
    while matches are fetched is what deadlocks the worker (and blocks its whole tick)."""
    ctx.settings = ctx.settings.model_copy(update={"ondemand_cooldown_seconds": 0})
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    before = (await session.get(Summoner, "fan", populate_existing=True)).last_refreshed_at
    riot.add_league_entry("fan", "RANKED_SOLO_5x5", "DIAMOND", "IV", 3)
    _add_games(riot, 1)
    gate = riot.block("match")

    task = asyncio.create_task(refresh_on_demand(ctx, session, "fan"))
    try:
        await asyncio.wait_for(riot.entered["match"].wait(), 5)
        # Another connection already sees this refresh while the match is still being
        # fetched: the advisory lock and the summoner row are free for the worker.
        async with session_factory() as other:
            summoner = await other.get(Summoner, "fan")
            assert summoner is not None and summoner.last_refreshed_at > before
            tiers = await other.scalars(
                select(RankSnapshot.tier).where(RankSnapshot.puuid == "fan")
            )
            assert "DIAMOND" in set(tiers)
    finally:
        gate.set()
        await asyncio.wait_for(task, 5)
    await session.commit()
    assert await stored_match_ids(session)


async def test_unknown_riot_id_is_only_asked_once(ctx, riot, session):
    """A 404 is remembered for a while: retyping a name (or a stream of made-up ones) must
    not spend one Riot request each time."""
    assert await get_or_resolve_summoner(ctx, session, "Nobody Here", "NA1") is None
    assert await get_or_resolve_summoner(ctx, session, "nobody here", "na1") is None
    assert len(riot.calls_to("account_by_riot_id")) == 1

    ctx.lookup_misses.clear()
    assert await get_or_resolve_summoner(ctx, session, "Nobody Here", "NA1") is None
    assert len(riot.calls_to("account_by_riot_id")) == 2


async def test_impossible_riot_ids_never_reach_riot(ctx, riot, session):
    for name, tag in (("ab", "NA1"), ("A" * 17, "NA1"), ("Someone", "N"), ("Someone", "N/A")):
        assert await get_or_resolve_summoner(ctx, session, name, tag) is None
    assert riot.calls == []


async def test_concurrent_lookups_are_capped(ctx, riot, session, session_factory):
    """Riot work runs a couple of requests at a time; the rest is turned away at once
    instead of parking a database connection each."""
    ctx.ondemand_guard = ondemand.OnDemandGuard(limit=1, wait=0.01)
    riot.add_account("Second Player", "NA2", puuid="second")
    gate = riot.block("summoner_by_puuid")

    first = asyncio.create_task(get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1"))
    try:
        await asyncio.wait_for(riot.entered["summoner_by_puuid"].wait(), 5)
        async with session_factory() as other:
            with pytest.raises(RiotRateLimited):
                await get_or_resolve_summoner(ctx, other, "Second Player", "NA2")
    finally:
        gate.set()
        await asyncio.wait_for(first, 5)


async def test_the_worker_can_ingest_the_same_game_while_an_update_runs(
    ctx, riot, session, session_factory, settings
):
    """Both sides ingest the game a friend just played: the request while the user waits,
    the worker on its next tick. The request used to hold the per-summoner advisory lock and
    the summoner row for its whole inline ingest, so the two transactions deadlocked (and
    Postgres killed one of them) over the same match insert and the same friends' rows."""
    ctx.settings = ctx.settings.model_copy(update={"ondemand_cooldown_seconds": 0})
    await get_or_resolve_summoner(ctx, session, "Faker Fan", "KR1")
    await session.commit()
    (match_id,) = _add_games(riot, 1)
    worker_riot = IngestFakeRiot(settings)
    worker_riot.matches = dict(riot.matches)
    worker_ctx = make_ctx(ctx.settings, session_factory, worker_riot)
    gate = riot.block("match")

    update = asyncio.create_task(refresh_on_demand(ctx, session, "fan"))
    try:
        await asyncio.wait_for(riot.entered["match"].wait(), 5)
        # The worker's own transaction runs to completion while the request is mid-fetch.
        async with session_scope(session_factory) as worker_session:
            result = await asyncio.wait_for(
                service.ingest_match(worker_ctx, worker_session, match_id), 5
            )
        assert result is not None and result.created
    finally:
        gate.set()
    outcome = await asyncio.wait_for(update, 5)
    assert outcome.status == "ok"
    assert await stored_match_ids(session) == {match_id}
