"""Records route: single-game records for the roster or one player, plus pentakills.

Owner: builder of feature 6 (records); the SQL lives in :mod:`hextrack.stats.records`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from hextrack.api.deps import (
    SAFE_TEXT,
    OptionalScorerDep,
    SessionDep,
    SettingsDep,
    error_responses,
)
from hextrack.api.schemas import LeaderboardQueue, Records, StatsSince
from hextrack.api.v1.summoners import require_summoner
from hextrack.stats import queries, records

router = APIRouter(tags=["records"])


@router.get(
    "/records",
    response_model=Records,
    summary="Single-game records (roster, or one player with ?puuid=) and pentakills",
    responses=error_responses(404),
)
async def get_records(
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    since: StatsSince = "season",
    queue: LeaderboardQueue = "all",
    puuid: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            pattern=SAFE_TEXT,
            description="Only this player's games (scope 'player'); omit for the roster",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=10, description="Entries per category")] = 3,
) -> Records:
    if puuid is not None:
        await require_summoner(session, puuid)
    version = await queries.resolve_model_version(session, scorer)
    return await records.records(
        session,
        settings,
        since=since,
        queue=queue,
        puuid=puuid,
        limit=limit,
        model_version=version,
    )
