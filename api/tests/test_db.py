"""Schema smoke tests: mapped rows insert cleanly and constraints behave."""

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from hextrack.db.models import AppState, Match, MatchParticipant, RankSnapshot, Summoner
from hextrack.ingest.mapping import map_match
from hextrack.rank import rank_value


async def test_insert_mapped_match(session, match_sample):
    mapped = map_match(match_sample)
    await session.execute(insert(Match).values(**mapped.match))
    await session.execute(insert(MatchParticipant), mapped.participants)
    await session.commit()

    match = await session.get(Match, mapped.match_id)
    assert match is not None and match.game_start.tzinfo is not None
    count = await session.scalar(
        select(func.count())
        .select_from(MatchParticipant)
        .where(MatchParticipant.match_id == mapped.match_id)
    )
    assert count == 10
    row = await session.scalar(
        select(MatchParticipant).where(MatchParticipant.riot_id_game_name == "Wardy")
    )
    assert row is not None
    assert row.control_wards == 12 and row.items[6] == 3364 and row.ai_score is None
    assert row.cs == row.total_minions_killed + row.neutral_minions_killed


async def test_summoner_riot_id_is_case_insensitive_unique(session):
    session.add(Summoner(puuid="a", game_name="Hex Walker", tag_line="NA1", platform="na1"))
    await session.commit()
    session.add(Summoner(puuid="b", game_name="hex walker", tag_line="na1", platform="na1"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
    # a different platform is a different account
    session.add(Summoner(puuid="c", game_name="hex walker", tag_line="na1", platform="euw1"))
    await session.commit()


async def test_rank_snapshot_and_app_state(session):
    session.add(Summoner(puuid="p", game_name="P", tag_line="NA1", platform="na1"))
    session.add(
        RankSnapshot(
            puuid="p",
            queue_type="RANKED_SOLO_5x5",
            tier="MASTER",
            rank=None,
            lp=120,
            wins=50,
            losses=40,
            rank_value=rank_value("MASTER", None, 120),
        )
    )
    session.add(AppState(key="poller", value={"running": True}))
    await session.commit()
    snap = await session.scalar(select(RankSnapshot))
    assert snap is not None and snap.taken_at is not None and snap.is_heartbeat is False
    state = await session.get(AppState, "poller")
    assert state is not None and state.value == {"running": True}
