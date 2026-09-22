"""GET /search: search over known summoners."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from hextrack.api.deps import SAFE_TEXT, SessionDep, SettingsDep
from hextrack.api.schemas import SummonerSearchResult
from hextrack.rank import RANKED_SOLO_5x5
from hextrack.stats import present, queries

router = APIRouter(tags=["search"])


@router.get(
    "/search",
    response_model=list[SummonerSearchResult],
    summary="Search known summoners by game name (accepts 'Name#TAG'); tracked players first",
)
async def search_summoners(
    session: SessionDep,
    settings: SettingsDep,
    q: Annotated[str, Query(min_length=1, max_length=64, pattern=SAFE_TEXT)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> list[SummonerSearchResult]:
    summoners = await queries.search_summoners(session, q, limit=limit)
    ranks = await queries.current_rank_snapshots(
        session,
        [s.puuid for s in summoners],
        season_start=settings.season_start,
        queue_types=(RANKED_SOLO_5x5,),
    )
    results = []
    for summoner in summoners:
        solo = present.rank_entry(ranks.get(summoner.puuid, {}).get(RANKED_SOLO_5x5))
        results.append(
            SummonerSearchResult(
                puuid=summoner.puuid,
                game_name=summoner.game_name,
                tag_line=summoner.tag_line,
                profile_icon_id=summoner.profile_icon_id,
                summoner_level=summoner.summoner_level,
                is_tracked=summoner.is_tracked,
                solo_tier=solo.tier if solo is not None else None,
                solo_rank=solo.rank if solo is not None else None,
            )
        )
    return results
