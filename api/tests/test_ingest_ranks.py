"""ingest.service.refresh_summoner: profile upsert, rank snapshot policy, tier events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from hextrack.db.models import RankSnapshot, Summoner
from hextrack.ingest import service
from hextrack.ingest.service import refresh_summoner, snapshot_action
from hextrack.rank import MASTER_BASE, rank_value
from hextrack.riot.errors import RiotForbidden, RiotNotFound
from hextrack.riot.schemas import LeagueEntryDto
from tests.test_ingest_support import IngestFakeRiot, count, events_of, make_ctx, snapshots_of

SOLO = "RANKED_SOLO_5x5"
FLEX = "RANKED_FLEX_SR"


@pytest.fixture
def riot(settings) -> IngestFakeRiot:
    riot = IngestFakeRiot(settings)
    riot.add_account("Hex Walker", "NA1", puuid="p1", profile_icon_id=4568, level=312)
    return riot


@pytest.fixture
def ctx(clean_db, settings, session_factory, riot):
    return make_ctx(settings, session_factory, riot)


async def _track(session, puuid: str = "p1") -> None:
    await session.execute(
        update(Summoner)
        .where(Summoner.puuid == puuid)
        .values(is_tracked=True, tracked_since=datetime.now(UTC))
    )
    await session.commit()


async def _backdate(session, puuid: str, hours: float) -> None:
    await session.execute(
        update(RankSnapshot)
        .where(RankSnapshot.puuid == puuid)
        .values(taken_at=RankSnapshot.taken_at - timedelta(hours=hours))
    )
    await session.commit()


async def test_unknown_puuid_is_created_via_account_v1(ctx, riot, session):
    summoner = await refresh_summoner(ctx, session, "p1")
    await session.commit()

    assert (summoner.game_name, summoner.tag_line, summoner.platform) == (
        "Hex Walker",
        "NA1",
        "na1",
    )
    assert (summoner.profile_icon_id, summoner.summoner_level) == (4568, 312)
    assert summoner.last_refreshed_at is not None
    assert summoner.is_tracked is False
    assert len(riot.calls_to("account_by_puuid")) == 1

    # known name + tag: account-v1 is not called again; profile changes are picked up
    riot.add_account("Hex Walker", "NA1", puuid="p1", profile_icon_id=1, level=313)
    first_refresh = summoner.last_refreshed_at
    again = await refresh_summoner(ctx, session, "p1")
    await session.commit()
    assert len(riot.calls_to("account_by_puuid")) == 1
    assert (again.profile_icon_id, again.summoner_level) == (1, 313)
    assert again.last_refreshed_at >= first_refresh


async def test_riot_failure_writes_nothing(ctx, riot, session):
    riot.fail("league_entries_by_puuid", RiotForbidden("expired", status=403))
    with pytest.raises(RiotForbidden):
        await refresh_summoner(ctx, session, "p1")
    await session.rollback()
    assert await count(session, Summoner) == 0

    with pytest.raises(RiotNotFound):
        await refresh_summoner(ctx, session, "nobody")


async def test_snapshot_only_on_change(ctx, riot, session):
    riot.add_league_entry("p1", SOLO, "GOLD", "II", 45, wins=30, losses=25)
    riot.add_league_entry("p1", FLEX, "SILVER", "I", 10, wins=5, losses=5)

    for _ in range(3):
        await refresh_summoner(ctx, session, "p1")
        await session.commit()

    solo = await snapshots_of(session, "p1", SOLO)
    flex = await snapshots_of(session, "p1", FLEX)
    assert len(solo) == 1 and len(flex) == 1
    snap = solo[0]
    assert (snap.tier, snap.rank, snap.lp, snap.wins, snap.losses) == ("GOLD", "II", 45, 30, 25)
    assert snap.rank_value == rank_value("GOLD", "II", 45)
    assert snap.is_heartbeat is False

    riot.add_league_entry("p1", SOLO, "GOLD", "II", 63, wins=31, losses=25)
    await refresh_summoner(ctx, session, "p1")
    await session.commit()
    solo = await snapshots_of(session, "p1", SOLO)
    assert [s.lp for s in solo] == [45, 63]
    assert len(await snapshots_of(session, "p1", FLEX)) == 1


async def test_wins_losses_change_is_recorded(ctx, riot, session):
    riot.add_league_entry("p1", SOLO, "GOLD", "IV", 0, wins=10, losses=10)
    await refresh_summoner(ctx, session, "p1")
    riot.add_league_entry("p1", SOLO, "GOLD", "IV", 0, wins=10, losses=11)  # demotion shield
    await refresh_summoner(ctx, session, "p1")
    await session.commit()
    assert [s.losses for s in await snapshots_of(session, "p1", SOLO)] == [10, 11]


async def test_heartbeat_after_24_hours(ctx, riot, session):
    riot.add_league_entry("p1", SOLO, "PLATINUM", "III", 12)
    await refresh_summoner(ctx, session, "p1")
    await session.commit()

    await _backdate(session, "p1", hours=23)
    await refresh_summoner(ctx, session, "p1")
    await session.commit()
    assert len(await snapshots_of(session, "p1", SOLO)) == 1

    await _backdate(session, "p1", hours=2)  # newest row is now 25h old
    await refresh_summoner(ctx, session, "p1")
    await session.commit()
    rows = await snapshots_of(session, "p1", SOLO)
    assert [r.is_heartbeat for r in rows] == [False, True]
    assert rows[1].rank_value == rows[0].rank_value

    # the heartbeat itself resets the 24h clock
    await refresh_summoner(ctx, session, "p1")
    await session.commit()
    assert len(await snapshots_of(session, "p1", SOLO)) == 2


async def test_master_plus_has_no_division_and_shared_ladder(ctx, riot, session):
    riot.add_league_entry("p1", SOLO, "MASTER", None, 120)  # Riot sends rank "I"
    await refresh_summoner(ctx, session, "p1")
    riot.add_league_entry("p1", SOLO, "GRANDMASTER", None, 410)
    await refresh_summoner(ctx, session, "p1")
    await session.commit()

    master, gm = await snapshots_of(session, "p1", SOLO)
    assert (master.tier, master.rank, master.rank_value) == ("MASTER", None, MASTER_BASE + 120)
    assert (gm.tier, gm.rank, gm.rank_value) == ("GRANDMASTER", None, MASTER_BASE + 410)
    assert gm.rank_value > rank_value("DIAMOND", "I", 99)


async def test_non_summoners_rift_queues_and_bad_entries_are_ignored(ctx, riot, session):
    riot.league_entries["p1"] = [
        LeagueEntryDto(queueType="CHERRY", tier="GOLD", rank="I", leaguePoints=1, wins=1, losses=1),
        LeagueEntryDto(queueType=SOLO, tier="WOOD", rank="I", leaguePoints=1, wins=1, losses=1),
        LeagueEntryDto(queueType=FLEX, tier="GOLD", rank="V", leaguePoints=1, wins=1, losses=1),
    ]
    await refresh_summoner(ctx, session, "p1")
    await session.commit()
    assert await count(session, RankSnapshot) == 0


async def test_tier_up_and_down_events_for_tracked_players(ctx, riot, session):
    riot.add_league_entry("p1", SOLO, "GOLD", "I", 90, wins=40, losses=35)
    await refresh_summoner(ctx, session, "p1")
    await session.commit()
    await _track(session)

    riot.add_league_entry("p1", SOLO, "GOLD", "I", 99, wins=41, losses=35)  # same tier
    await refresh_summoner(ctx, session, "p1")
    riot.add_league_entry("p1", SOLO, "PLATINUM", "IV", 5, wins=42, losses=35)
    await refresh_summoner(ctx, session, "p1")
    riot.add_league_entry("p1", SOLO, "GOLD", "I", 75, wins=42, losses=36)
    await refresh_summoner(ctx, session, "p1")
    await session.commit()

    rows = await events_of(session)
    assert [e.kind for e in rows] == ["tier_up", "tier_down"]
    up = rows[0].payload
    previous_taken_at = up.pop("previous_taken_at")
    # The standing the change is measured against, so a consumer can spot a stale compare.
    assert datetime.now(UTC) - datetime.fromisoformat(previous_taken_at) < timedelta(minutes=5)
    assert up == {
        "puuid": "p1",
        "game_name": "Hex Walker",
        "tag_line": "NA1",
        "platform": "na1",
        "profile_icon_id": 4568,
        "queue_type": SOLO,
        "old": {"tier": "GOLD", "rank": "I", "lp": 99},
        "new": {"tier": "PLATINUM", "rank": "IV", "lp": 5},
        "wins": 42,
        "losses": 35,
        "rank_value": rank_value("PLATINUM", "IV", 5),
        "old_tier": "GOLD",
        "old_rank": "I",
        "new_tier": "PLATINUM",
        "new_rank": "IV",
        "lp": 5,
    }
    assert rows[1].payload["old"] == {"tier": "PLATINUM", "rank": "IV", "lp": 5}
    assert rows[1].payload["new"] == {"tier": "GOLD", "rank": "I", "lp": 75}


async def test_no_tier_events_for_untracked_or_first_sighting(ctx, riot, session):
    riot.add_league_entry("p1", SOLO, "SILVER", "I", 90)
    await refresh_summoner(ctx, session, "p1")  # first sighting (untracked)
    riot.add_league_entry("p1", SOLO, "GOLD", "IV", 0)
    await refresh_summoner(ctx, session, "p1")  # tier change, but untracked
    await session.commit()
    await _track(session)
    riot.add_league_entry("p1", FLEX, "EMERALD", "II", 50)
    await refresh_summoner(ctx, session, "p1")  # first flex snapshot, tracked
    await session.commit()
    assert await events_of(session) == []


def test_snapshot_action_policy():
    now = datetime(2026, 9, 21, 12, tzinfo=UTC)
    state = service.RankState(SOLO, "GOLD", "II", 45, 30, 25, rank_value("GOLD", "II", 45))
    prev = RankSnapshot(
        tier="GOLD", rank="II", lp=45, wins=30, losses=25, taken_at=now - timedelta(hours=1)
    )
    assert snapshot_action(None, state, now) == "change"
    assert snapshot_action(prev, state, now) is None
    prev.taken_at = now - timedelta(hours=24)
    assert snapshot_action(prev, state, now) == "heartbeat"
    prev.lp = 44
    assert snapshot_action(prev, state, now) == "change"


async def test_tier_events_need_a_recent_standing_to_compare_against(ctx, riot, session):
    """A tier change measured against a months-old snapshot (the worker was down, a legacy
    import, a season reset) is recorded but never announced."""
    riot.add_league_entry("p1", SOLO, "SILVER", "I", 90)
    await refresh_summoner(ctx, session, "p1")
    await session.commit()
    await _track(session)
    await _backdate(session, "p1", hours=72)

    riot.add_league_entry("p1", SOLO, "GOLD", "IV", 10)
    await refresh_summoner(ctx, session, "p1")
    await session.commit()

    assert [s.tier for s in await snapshots_of(session, "p1", SOLO)] == ["SILVER", "GOLD"]
    assert await events_of(session) == []


async def test_placements_after_a_season_reset_are_not_announced(ctx, riot, session):
    """The first ranked snapshot of a new season is compared against last season's rank,
    which is not a promotion."""
    riot.add_league_entry("p1", SOLO, "BRONZE", "IV", 94)
    await refresh_summoner(ctx, session, "p1")
    await session.commit()
    await _track(session)
    # A new season started two hours ago; last season's snapshot is from just before it
    # (recent enough that only the season boundary keeps this quiet).
    await _backdate(session, "p1", hours=4)
    ctx.settings = ctx.settings.model_copy(
        update={"season_start": datetime.now(UTC) - timedelta(hours=2)}
    )

    riot.add_league_entry("p1", SOLO, "SILVER", "IV", 12)
    await refresh_summoner(ctx, session, "p1")
    await session.commit()

    assert [s.tier for s in await snapshots_of(session, "p1", SOLO)] == ["BRONZE", "SILVER"]
    assert await events_of(session) == []
