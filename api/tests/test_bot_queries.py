"""Bot database reads: season LP deltas (Master+ math), roster lookup, app_state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.bot import queries
from hextrack.db.models import Match, MatchParticipant, RankSnapshot, Summoner
from hextrack.ingest.mapping import map_match
from hextrack.rank import RANKED_FLEX_SR, RANKED_SOLO_5x5, rank_value
from tests.factories import make_match_json, spec

SEASON = datetime(2026, 1, 8, 20, 0, tzinfo=UTC)


async def add_summoner(
    session: AsyncSession,
    puuid: str,
    game_name: str,
    tag_line: str = "NA1",
    *,
    tracked: bool = True,
    icon: int | None = None,
) -> Summoner:
    summoner = Summoner(
        puuid=puuid,
        game_name=game_name,
        tag_line=tag_line,
        platform="na1",
        profile_icon_id=icon,
        is_tracked=tracked,
        tracked_since=SEASON if tracked else None,
        last_refreshed_at=SEASON,
    )
    session.add(summoner)
    await session.flush()
    return summoner


async def add_snapshot(
    session: AsyncSession,
    puuid: str,
    tier: str,
    rank: str | None,
    lp: int,
    taken_at: datetime,
    *,
    queue_type: str = RANKED_SOLO_5x5,
    wins: int = 10,
    losses: int = 10,
) -> RankSnapshot:
    snapshot = RankSnapshot(
        puuid=puuid,
        queue_type=queue_type,
        tier=tier,
        rank=rank,
        lp=lp,
        wins=wins,
        losses=losses,
        rank_value=rank_value(tier, rank, lp),
        taken_at=taken_at,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def seed_ladder(session: AsyncSession) -> None:
    """Tracked players covering the interesting rank_value cases."""
    day = timedelta(days=1)
    # Diamond I -> Master: LPBot's tier*400 + division*100 formula reported +375 here.
    await add_summoner(session, "p-master", "Climber")
    await add_snapshot(session, "p-master", "GOLD", "I", 50, SEASON - 10 * day)  # last season
    await add_snapshot(session, "p-master", "DIAMOND", "I", 75, SEASON + day)
    await add_snapshot(session, "p-master", "DIAMOND", "I", 90, SEASON + 5 * day)
    await add_snapshot(session, "p-master", "MASTER", None, 50, SEASON + 20 * day)
    # Master -> Grandmaster share one ladder.
    await add_summoner(session, "p-gm", "Apex")
    await add_snapshot(session, "p-gm", "MASTER", None, 200, SEASON + 2 * day)
    await add_snapshot(session, "p-gm", "GRANDMASTER", None, 450, SEASON + 9 * day)
    # Demotion.
    await add_summoner(session, "p-down", "Faller")
    await add_snapshot(session, "p-down", "PLATINUM", "II", 50, SEASON + day)
    await add_snapshot(session, "p-down", "PLATINUM", "III", 80, SEASON + 3 * day)
    # Legacy LPBot rows store division "I" for apex tiers.
    await add_summoner(session, "p-legacy", "Legacy")
    await add_snapshot(session, "p-legacy", "MASTER", "I", 10, SEASON + day)
    await add_snapshot(session, "p-legacy", "CHALLENGER", "I", 900, SEASON + 30 * day)
    # Excluded: untracked, pre-season only, flex only.
    await add_summoner(session, "p-untracked", "Stranger", tracked=False)
    await add_snapshot(session, "p-untracked", "IRON", "IV", 0, SEASON + day)
    await add_snapshot(session, "p-untracked", "BRONZE", "IV", 0, SEASON + 2 * day)
    await add_summoner(session, "p-old", "Retired")
    await add_snapshot(session, "p-old", "GOLD", "II", 10, SEASON - day)
    await add_summoner(session, "p-flex", "FlexOnly")
    await add_snapshot(
        session, "p-flex", "SILVER", "II", 0, SEASON + day, queue_type=RANKED_FLEX_SR
    )
    await add_snapshot(
        session, "p-flex", "GOLD", "II", 0, SEASON + 2 * day, queue_type=RANKED_FLEX_SR
    )


async def test_season_lp_deltas_use_rank_value(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await seed_ladder(session)
        deltas = await queries.season_lp_deltas(
            session, since=SEASON, until=SEASON + timedelta(days=60)
        )
    by_puuid = {d.puuid: d for d in deltas}
    assert set(by_puuid) == {"p-master", "p-gm", "p-down", "p-legacy"}
    assert by_puuid["p-master"].delta == 75  # 2775 -> 2850
    assert by_puuid["p-master"].start_value == 2775
    assert by_puuid["p-master"].end_value == 2850
    assert by_puuid["p-gm"].delta == 250
    assert by_puuid["p-down"].delta == -70
    assert by_puuid["p-legacy"].delta == 890
    assert by_puuid["p-master"].riot_id == "Climber#NA1"
    # ordered by name
    assert [d.game_name for d in deltas] == ["Apex", "Climber", "Faller", "Legacy"]


async def test_season_lp_deltas_respect_until(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await seed_ladder(session)
        deltas = await queries.season_lp_deltas(
            session, since=SEASON, until=SEASON + timedelta(days=6)
        )
    by_puuid = {d.puuid: d.delta for d in deltas}
    assert by_puuid["p-master"] == 15  # Diamond I 75 -> 90; the Master snapshot is later
    assert by_puuid["p-gm"] == 0  # only the baseline is in the window
    assert "p-legacy" in by_puuid


async def test_season_lp_deltas_flex_queue(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await seed_ladder(session)
        deltas = await queries.season_lp_deltas(
            session, since=SEASON, until=SEASON + timedelta(days=60), queue_type=RANKED_FLEX_SR
        )
    assert [(d.puuid, d.delta) for d in deltas] == [("p-flex", 400)]


def test_snapshot_value_falls_back_to_the_stored_value() -> None:
    assert queries.snapshot_value("GOLD", "II", 10, 0) == rank_value("GOLD", "II", 10)
    assert queries.snapshot_value("WOOD", "II", 10, 1234) == 1234
    assert queries.snapshot_value("GOLD", None, 10, 999) == 999


async def test_latest_rank(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await seed_ladder(session)
        latest = await queries.latest_rank(session, "p-master")
        flex = await queries.latest_rank(session, "p-flex", RANKED_FLEX_SR)
        none = await queries.latest_rank(session, "p-flex")
    assert latest is not None and (latest.tier, latest.lp) == ("MASTER", 50)
    assert flex is not None and flex.tier == "GOLD"
    assert none is None


async def test_latest_rank_with_season_start_drops_a_stale_standing(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """With ``season_start`` the bot reports what the website reports: a snapshot from before
    the season, or one league-v4 has stopped returning, means unranked, not last season's tier."""
    day = timedelta(days=1)
    async with session_factory() as session:
        # Refreshed today, but their newest snapshot is from last season: unranked now.
        stale = await add_summoner(session, "p-stale", "Old Rank")
        stale.last_refreshed_at = datetime.now(UTC)
        await add_snapshot(session, "p-stale", "GOLD", "I", 50, SEASON - 10 * day)
        # Refreshed today with a snapshot from this refresh: still their standing.
        current = await add_summoner(session, "p-current", "Fresh Rank")
        current.last_refreshed_at = datetime.now(UTC)
        await add_snapshot(session, "p-current", "EMERALD", "IV", 40, datetime.now(UTC))
        await session.flush()

        assert await queries.latest_rank(session, "p-stale", season_start=SEASON) is None
        # Without season_start the old behaviour (newest row, whatever its age) is kept.
        legacy = await queries.latest_rank(session, "p-stale")
        assert legacy is not None and legacy.tier == "GOLD"
        fresh = await queries.latest_rank(session, "p-current", season_start=SEASON)
        assert fresh is not None and fresh.tier == "EMERALD"


async def seed_roster(session: AsyncSession) -> None:
    await add_summoner(session, "p1", "Hex Walker", "NA1")
    await add_summoner(session, "p2", "Walker Two", "NA1")
    await add_summoner(session, "p3", "TheSlab", "333")
    await add_summoner(session, "p4", "hex walker", "EUW")
    await add_summoner(session, "p5", "Hexed", "NA1", tracked=False)
    await add_summoner(session, "p6", "100%Tilt", "NA1")


async def test_search_roster(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await seed_roster(session)
        everyone = await queries.search_roster(session, "")
        walker = await queries.search_roster(session, "WALKER")
        hex_ = await queries.search_roster(session, "hex")
        tag = await queries.search_roster(session, "#333")
        percent = await queries.search_roster(session, "%")
        underscore = await queries.search_roster(session, "_")
        limited = await queries.search_roster(session, "", limit=2)

    def names(rows: list[Summoner]) -> list[str]:
        return [r.riot_id for r in rows]

    assert names(everyone) == [
        "100%Tilt#NA1",
        "hex walker#EUW",
        "Hex Walker#NA1",
        "TheSlab#333",
        "Walker Two#NA1",
    ]
    # prefix matches ("Walker Two") come before substring matches
    assert names(walker) == ["Walker Two#NA1", "hex walker#EUW", "Hex Walker#NA1"]
    assert names(hex_) == ["hex walker#EUW", "Hex Walker#NA1"]  # "Hexed" is not tracked
    assert names(tag) == ["TheSlab#333"]
    assert names(percent) == ["100%Tilt#NA1"]  # LIKE wildcards are escaped
    assert underscore == []
    assert len(limited) == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("p3", "p3"),
        ("TheSlab#333", "p3"),
        ("theslab#333", "p3"),
        ("  TheSlab # 333 ", "p3"),
        ("TheSlab-333", "p3"),
        ("theslab", "p3"),  # unique bare name
        ("Hex Walker#NA1", "p1"),
        ("hex walker#euw", "p4"),
        ("hex walker", None),  # ambiguous bare name
        ("Hexed#NA1", None),  # not tracked
        ("Nobody#NA1", None),
        ("", None),
    ],
)
async def test_resolve_tracked(
    clean_db: None,
    session_factory: async_sessionmaker[AsyncSession],
    value: str,
    expected: str | None,
) -> None:
    async with session_factory() as session:
        await seed_roster(session)
        found = await queries.resolve_tracked(session, value)
    assert (found.puuid if found else None) == expected


async def test_get_summoners(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await seed_roster(session)
        found = await queries.get_summoners(session, ["p1", "p5", "missing", ""])
        assert await queries.get_summoners(session, []) == {}
    assert set(found) == {"p1", "p5"}


async def test_ai_scores(clean_db: None, session_factory: async_sessionmaker[AsyncSession]) -> None:
    raw = make_match_json("NA1_900", [spec("p1", "Hex Walker", "NA1"), spec("p2")])
    mapped = map_match(raw)
    async with session_factory() as session:
        session.add(Match(**mapped.match))
        await session.flush()
        for row in mapped.participants:
            participant = MatchParticipant(**row)
            if row["puuid"] == "p1":
                participant.ai_score = 0.71
            session.add(participant)
        await session.flush()
        scores = await queries.ai_scores(
            session, [("NA1_900", "p1"), ("NA1_900", "p2"), ("NA1_404", "p1")]
        )
        assert await queries.ai_scores(session, []) == {}
    assert scores == {("NA1_900", "p1"): pytest.approx(0.71)}


async def test_app_state_helpers(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session, session.begin():
        assert await queries.get_state(session, "bot_test") is None
        assert await queries.lock_state(session, "bot_test") == {}
        await queries.put_state(session, "bot_test", {"a": 1})
        assert await queries.lock_state(session, "bot_test") == {"a": 1}
        await queries.put_state(session, "bot_test", {"a": 2, "b": [1, 2]})
    async with session_factory() as session:
        assert await queries.get_state(session, "bot_test") == {"a": 2, "b": [1, 2]}
