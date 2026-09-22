"""Tracked roster routes; writes require the admin bearer token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response

from hextrack.api.deps import (
    RIOT_ERRORS,
    SAFE_TEXT,
    AdminDep,
    ApiError,
    CtxDep,
    SessionDep,
    error_responses,
)
from hextrack.api.schemas import RosterEntry
from hextrack.api.v1.summoners import parse_path_riot_id
from hextrack.db.models import Summoner
from hextrack.ingest import roster
from hextrack.stats import queries

router = APIRouter(prefix="/roster", tags=["roster"])

GameName = Annotated[str, Path(min_length=1, max_length=32, pattern=SAFE_TEXT)]
TagLine = Annotated[str, Path(min_length=1, max_length=8, pattern=SAFE_TEXT)]


def _entry(summoner: Summoner) -> RosterEntry:
    return RosterEntry(
        puuid=summoner.puuid,
        game_name=summoner.game_name,
        tag_line=summoner.tag_line,
        tracked_since=summoner.tracked_since,
        profile_icon_id=summoner.profile_icon_id,
    )


@router.get("", response_model=list[RosterEntry], summary="Tracked players")
async def list_roster(session: SessionDep) -> list[RosterEntry]:
    return [_entry(s) for s in await queries.tracked_summoners(session)]


@router.put(
    "/{game_name}/{tag_line}",
    response_model=RosterEntry,
    summary="Start tracking a player (admin)",
    responses=error_responses(400, 401, 403, 404, *RIOT_ERRORS),
)
async def add_roster_entry(
    game_name: GameName,
    tag_line: TagLine,
    _admin: AdminDep,
    session: SessionDep,
    ctx: CtxDep,
) -> RosterEntry:
    riot_id = parse_path_riot_id(game_name, tag_line)
    try:
        summoner = await roster.add_to_roster(ctx, session, str(riot_id))
    except roster.RosterError as exc:
        raise ApiError(404, str(exc) or f"No Riot account named {riot_id}", "not_found") from exc
    await session.commit()
    return _entry(summoner)


@router.delete(
    "/{game_name}/{tag_line}",
    status_code=204,
    response_class=Response,
    summary="Stop tracking a player (admin); match data is kept",
    responses=error_responses(400, 401, 403, 404),
)
async def remove_roster_entry(
    game_name: GameName,
    tag_line: TagLine,
    _admin: AdminDep,
    session: SessionDep,
) -> Response:
    riot_id = parse_path_riot_id(game_name, tag_line)
    try:
        removed = await roster.remove_from_roster(session, str(riot_id))
    except roster.RosterError as exc:
        raise ApiError(400, str(exc), "invalid_riot_id") from exc
    if not removed:
        raise ApiError(404, f"{riot_id} is not on the roster", "not_found")
    await session.commit()
    return Response(status_code=204)
