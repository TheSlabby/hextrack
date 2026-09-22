"""Roster leaderboard route."""

from __future__ import annotations

from fastapi import APIRouter

from hextrack.api.deps import OptionalScorerDep, SessionDep, SettingsDep
from hextrack.api.schemas import Leaderboard, LeaderboardQueue
from hextrack.stats import aggregate, queries

router = APIRouter(tags=["leaderboard"])


@router.get(
    "/leaderboard",
    response_model=Leaderboard,
    summary="Season leaderboard of the tracked roster",
)
async def get_leaderboard(
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    queue: LeaderboardQueue = "all",
) -> Leaderboard:
    # Only one model version's scores are averaged: the active one (or the loaded model).
    version = await queries.resolve_model_version(session, scorer)
    return await aggregate.leaderboard(session, settings, queue=queue, model_version=version)
