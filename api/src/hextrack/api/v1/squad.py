"""Friend-group route: duo synergy grid and who carries whom.

Owner: builder of features 1 + 2 (squad); the SQL lives in :mod:`hextrack.stats.squad`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from hextrack.api.deps import ApiError, OptionalScorerDep, SessionDep, SettingsDep, error_responses
from hextrack.api.schemas import (
    LeaderboardQueue,
    SquadPairs,
    StackGamePage,
    StackQueue,
    StackSummary,
    StatsSince,
)
from hextrack.stats import queries, squad, stacks

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


StackSize = Annotated[int, Query(ge=3, le=5, description="Fewest roster players on one team")]


@router.get(
    "/stacks",
    response_model=StackSummary,
    summary="Stacks (games the squad played together): record, awards, lineups, highlights",
)
async def get_stack_summary(
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    since: StatsSince = "season",
    queue: StackQueue = "all",
    size: StackSize = 5,
) -> StackSummary:
    version = await queries.resolve_model_version(session, scorer)
    return await stacks.stack_summary(
        session, settings, since=since, queue=queue, size=size, model_version=version
    )


@router.get(
    "/stacks/games",
    response_model=StackGamePage,
    summary="Stacked games, newest first (cursor paginated)",
    responses=error_responses(400),
)
async def get_stack_games(
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    since: StatsSince = "season",
    queue: StackQueue = "all",
    size: StackSize = 5,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> StackGamePage:
    try:
        position = queries.decode_cursor(cursor) if cursor else None
    except queries.InvalidCursor as exc:
        raise ApiError(400, "Invalid cursor", "invalid_cursor") from exc
    version = await queries.resolve_model_version(session, scorer)
    return await stacks.stack_games(
        session,
        settings,
        since=since,
        queue=queue,
        size=size,
        model_version=version,
        cursor=position,
        limit=limit,
    )


@router.get(
    "/recent",
    response_model=StackGamePage,
    summary="The roster's most recent games, newest first (cursor paginated)",
    responses=error_responses(400),
)
async def get_recent_games(
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> StackGamePage:
    """Every game a roster player played (the same rows as the Stacks page with a minimum of
    one roster player): all queues except Arena and customs, remakes excluded. Friends on the
    same team share a row, with the stack verdict when there are two or more."""
    try:
        position = queries.decode_cursor(cursor) if cursor else None
    except queries.InvalidCursor as exc:
        raise ApiError(400, "Invalid cursor", "invalid_cursor") from exc
    version = await queries.resolve_model_version(session, scorer)
    return await stacks.stack_games(
        session,
        settings,
        since="all",
        queue="all",
        size=1,
        model_version=version,
        cursor=position,
        limit=limit,
    )
