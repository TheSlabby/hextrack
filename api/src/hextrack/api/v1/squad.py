"""Friend-group route: duo synergy grid and who carries whom.

Owner: builder of features 1 + 2 (squad); the SQL lives in :mod:`hextrack.stats.squad`.
"""

from __future__ import annotations

from fastapi import APIRouter

from hextrack.api.deps import OptionalScorerDep, SessionDep, SettingsDep
from hextrack.api.schemas import LeaderboardQueue, SquadPairs, StatsSince
from hextrack.stats import queries, squad

router = APIRouter(prefix="/squad", tags=["squad"])


@router.get(
    "/pairs",
    response_model=SquadPairs,
    summary="Duo synergy and who carries whom for every pair of tracked players",
)
async def get_squad_pairs(
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    since: StatsSince = "season",
    queue: LeaderboardQueue = "all",
) -> SquadPairs:
    # Only the active model's scores (or the loaded model's) count, as on the leaderboard.
    version = await queries.resolve_model_version(session, scorer)
    return await squad.squad_pairs(
        session, settings, since=since, queue=queue, model_version=version
    )
