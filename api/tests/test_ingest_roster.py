"""ingest.roster: add / remove / list tracked players."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hextrack.db.models import Summoner
from hextrack.ingest.roster import RosterError, add_to_roster, list_roster, remove_from_roster
from hextrack.riot.errors import RiotRateLimited
from tests.test_ingest_support import IngestFakeRiot, count, events_of, make_ctx, snapshots_of


@pytest.fixture
def riot(settings) -> IngestFakeRiot:
    riot = IngestFakeRiot(settings)
    riot.add_account("Hex Walker", "NA1", puuid="hex", profile_icon_id=4568, level=312)
    riot.add_account("alpha", "0001", puuid="alpha")
    riot.add_league_entry("hex", "RANKED_SOLO_5x5", "DIAMOND", "IV", 12)
    return riot


@pytest.fixture
def ctx(clean_db, settings, session_factory, riot):
    return make_ctx(settings, session_factory, riot)


async def test_add_resolves_refreshes_and_tracks(ctx, riot, session):
    summoner = await add_to_roster(ctx, session, "hex walker#na1")
    await session.commit()

    assert summoner.puuid == "hex"
    assert (summoner.game_name, summoner.tag_line) == ("Hex Walker", "NA1")
    assert summoner.is_tracked is True and summoner.tracked_since is not None
    assert summoner.backfilled_at is None
    assert (summoner.profile_icon_id, summoner.summoner_level) == (4568, 312)
    snaps = await snapshots_of(session, "hex")
    assert [s.tier for s in snaps] == ["DIAMOND"]
    assert await events_of(session) == []


async def test_add_is_idempotent_and_keeps_tracked_since(ctx, riot, session):
    first = await add_to_roster(ctx, session, "Hex Walker#NA1")
    await session.commit()
    since = first.tracked_since
    riot.calls.clear()

    again = await add_to_roster(ctx, session, "HEX WALKER#na1")
    await session.commit()

    assert again.puuid == "hex" and again.tracked_since == since
    assert riot.calls == []  # served from the DB
    assert await count(session, Summoner) == 1


async def test_add_known_untracked_player_refreshes_and_starts_a_backfill(ctx, riot, session):
    """A player who was already stored (looked up once, legacy-imported) gets a fresh
    standing before tracking starts, so the first poll cannot announce an old rank change,
    and their season is backfilled from scratch."""
    riot.add_league_entry("alpha", "RANKED_SOLO_5x5", "SILVER", "II", 30)
    session.add(
        Summoner(
            puuid="alpha",
            game_name="alpha",
            tag_line="0001",
            platform="na1",
            backfilled_at=datetime(2026, 2, 1, tzinfo=UTC),
            synced_through=datetime(2026, 2, 1, tzinfo=UTC),
        )
    )
    await session.commit()

    summoner = await add_to_roster(ctx, session, "Alpha#0001")
    await session.commit()

    assert summoner.is_tracked and summoner.backfilled_at is None
    assert summoner.synced_through is None
    assert summoner.last_refreshed_at is not None
    assert [s.tier for s in await snapshots_of(session, "alpha")] == ["SILVER"]
    # Rank was re-read, but no account-v1 lookup was needed.
    assert {c.method for c in riot.calls} == {"summoner_by_puuid", "league_entries_by_puuid"}
    assert await events_of(session) == []


async def test_add_rejects_bad_riot_ids(ctx, riot, session):
    with pytest.raises(RosterError, match="Name#TAG"):
        await add_to_roster(ctx, session, "no tag here")
    with pytest.raises(RosterError, match="no Riot account"):
        await add_to_roster(ctx, session, "Nobody#NA1")
    riot.add_account("Valorant Only", "VAL", puuid="val")
    del riot.summoners["val"]
    with pytest.raises(RosterError, match="League"):
        await add_to_roster(ctx, session, "Valorant Only#VAL")
    await session.commit()
    assert await count(session, Summoner) == 0


async def test_add_propagates_other_riot_errors(ctx, riot, session):
    riot.fail("account_by_riot_id", RiotRateLimited(retry_after=1))
    with pytest.raises(RiotRateLimited):
        await add_to_roster(ctx, session, "Hex Walker#NA1")


async def test_remove_untracks_but_keeps_data(ctx, riot, session):
    await add_to_roster(ctx, session, "Hex Walker#NA1")
    await session.commit()

    assert await remove_from_roster(session, "hex WALKER#NA1") is True
    await session.commit()
    summoner = await session.get(Summoner, "hex", populate_existing=True)
    assert summoner is not None
    assert summoner.is_tracked is False and summoner.tracked_since is None
    assert len(await snapshots_of(session, "hex")) == 1

    assert await remove_from_roster(session, "Hex Walker#NA1") is False
    assert await remove_from_roster(session, "Nobody#NA1") is False
    with pytest.raises(RosterError):
        await remove_from_roster(session, "bad")


async def test_list_roster_is_sorted_case_insensitively(ctx, riot, session):
    riot.add_account("bravo", "NA1", puuid="bravo")
    for rid in ("Hex Walker#NA1", "bravo#NA1", "alpha#0001"):
        await add_to_roster(ctx, session, rid)
    session.add(Summoner(puuid="x", game_name="Aaron", tag_line="NA1", platform="na1"))
    await session.commit()

    names = [s.game_name for s in await list_roster(session)]
    assert names == ["alpha", "bravo", "Hex Walker"]
