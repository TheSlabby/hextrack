"""Champion pages: champion list, one champion's stats / builds / runes / matchups, and the
roster on a champion."""

from __future__ import annotations

from fastapi import APIRouter

from hextrack.api.deps import OptionalScorerDep, SessionDep, SettingsDep
from hextrack.api.schemas import (
    ChampionDetail,
    ChampionList,
    ChampionPatches,
    ChampionRole,
    ChampionSquad,
    LeaderboardQueue,
)

router = APIRouter(prefix="/champions", tags=["champions"])


@router.get(
    "/patches",
    response_model=ChampionPatches,
    summary="Patches with champion data this season (for the patch picker)",
)
async def get_champion_patches(session: SessionDep, settings: SettingsDep) -> ChampionPatches:
    raise NotImplementedError


@router.get(
    "",
    response_model=ChampionList,
    summary="Every champion's games, win / pick / ban rate and roles in a patch window",
)
async def get_champions(
    session: SessionDep,
    settings: SettingsDep,
    patch: str = "recent",
    queue: LeaderboardQueue = "all",
) -> ChampionList:
    raise NotImplementedError


@router.get(
    "/{champion}",
    response_model=ChampionDetail,
    summary="One champion: stats by role, builds, runes, spells, skills, lane matchups",
)
async def get_champion(
    session: SessionDep,
    settings: SettingsDep,
    champion: str,
    patch: str = "recent",
    queue: LeaderboardQueue = "all",
    role: ChampionRole | None = None,
) -> ChampionDetail:
    raise NotImplementedError


@router.get(
    "/{champion}/squad",
    response_model=ChampionSquad,
    summary="Roster players on this champion this season",
)
async def get_champion_squad(
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    champion: str,
    queue: LeaderboardQueue = "all",
) -> ChampionSquad:
    raise NotImplementedError
