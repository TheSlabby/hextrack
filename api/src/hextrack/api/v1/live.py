"""Live games of roster players (spectator-v5, refreshed by the worker)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from hextrack.api.deps import OptionalScorerDep, SessionDep, SettingsDep
from hextrack.api.schemas import LiveGames
from hextrack.stats import live, queries

router = APIRouter(prefix="/live", tags=["live"])


@router.get(
    "",
    response_model=LiveGames,
    summary="Games roster players are in right now (as of the worker's last check)",
)
async def get_live_games(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
) -> LiveGames:
    version = await queries.resolve_model_version(session, scorer)
    return await live.live_games(
        session,
        settings,
        request.app.state.ddragon,
        model_version=version,
        now=datetime.now(UTC),
    )
