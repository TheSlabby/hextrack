"""Champion pages: champion list, one champion's stats / builds / runes / matchups, and the
roster on a champion. The SQL lives in :mod:`hextrack.stats.champions.read`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Request

from hextrack.api.deps import (
    SAFE_TEXT,
    ApiError,
    OptionalScorerDep,
    SessionDep,
    SettingsDep,
    error_responses,
)
from hextrack.api.schemas import (
    ChampionDetail,
    ChampionList,
    ChampionPatches,
    ChampionPlayer,
    ChampionRole,
    ChampionSquad,
    LeaderboardQueue,
)
from hextrack.stats import queries
from hextrack.stats.champions import player, read

router = APIRouter(prefix="/champions", tags=["champions"])

#: Validated like every other puuid path segment: a NUL byte would otherwise reach asyncpg
#: as invalid UTF-8 and fail the summoner lookup with a 500.
Puuid = Annotated[str, Path(min_length=1, max_length=100, pattern=SAFE_TEXT)]


def _unknown_patch(patch: str) -> ApiError:
    return ApiError(
        400,
        f"Unknown patch {patch[:20]!r}: use recent, season or a patch with games",
        code="unknown_patch",
    )


def _champion_not_found() -> ApiError:
    return ApiError(404, "No games on this champion", code="champion_not_found")


@router.get(
    "/patches",
    response_model=ChampionPatches,
    summary="Patches with champion data this season (for the patch picker)",
)
async def get_champion_patches(session: SessionDep, settings: SettingsDep) -> ChampionPatches:
    return await read.champion_patches(session)


@router.get(
    "",
    response_model=ChampionList,
    summary="Every champion's games, win / pick / ban rate and roles in a patch window",
    responses=error_responses(400),
)
async def get_champions(
    session: SessionDep,
    settings: SettingsDep,
    patch: str = "recent",
    queue: LeaderboardQueue = "all",
) -> ChampionList:
    try:
        return await read.champion_list(session, patch=patch, queue=queue)
    except read.UnknownPatch as exc:
        raise _unknown_patch(patch) from exc


@router.get(
    "/{champion}",
    response_model=ChampionDetail,
    summary="One champion: stats by role, builds, runes, spells, skills, lane matchups",
    responses=error_responses(400, 404),
)
async def get_champion(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    champion: str,
    patch: str = "recent",
    queue: LeaderboardQueue = "all",
    role: ChampionRole | None = None,
) -> ChampionDetail:
    try:
        return await read.champion_detail(
            session,
            champion=champion,
            patch=patch,
            queue=queue,
            role=role,
            ddragon=getattr(request.app.state, "ddragon", None),
        )
    except read.UnknownPatch as exc:
        raise _unknown_patch(patch) from exc
    except read.ChampionNotFound as exc:
        raise _champion_not_found() from exc


@router.get(
    "/{champion}/squad",
    response_model=ChampionSquad,
    summary="Roster players on this champion this season",
    responses=error_responses(404),
)
async def get_champion_squad(
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    champion: str,
    queue: LeaderboardQueue = "all",
) -> ChampionSquad:
    # Only the active model's scores (or the loaded model's) count, as on the leaderboard.
    version = await queries.resolve_model_version(session, scorer)
    try:
        return await read.champion_squad(
            session, settings, champion=champion, queue=queue, model_version=version
        )
    except read.ChampionNotFound as exc:
        raise _champion_not_found() from exc


@router.get(
    "/{champion}/players/{puuid}",
    response_model=ChampionPlayer,
    responses=error_responses(404),
    summary="A roster player's games on this champion this season, next to everyone's",
)
async def get_champion_player(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    champion: str,
    puuid: Puuid,
    queue: LeaderboardQueue = "all",
) -> ChampionPlayer:
    version = await queries.resolve_model_version(session, scorer)
    try:
        return await player.champion_player(
            session,
            settings,
            champion=champion,
            puuid=puuid,
            queue=queue,
            model_version=version,
            ddragon=getattr(request.app.state, "ddragon", None),
        )
    except read.ChampionNotFound as exc:
        raise _champion_not_found() from exc
    except player.PlayerNotFound as exc:
        raise ApiError(404, "Not a roster player", code="player_not_found") from exc
