"""Personal insight routes: sessions (tilt), schedule (best time to play), matchups
(nemesis champions) and luck (unlucky losses / lucky wins).

The SQL and the rules live in :mod:`hextrack.stats.insights`. Every route checks the
summoner exists (404) and resolves the model version the same way as the profile
(``queries.resolve_model_version(session, scorer, puuid=puuid)``).
"""

from __future__ import annotations

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Path, Query

from hextrack.api.deps import (
    SAFE_TEXT,
    ApiError,
    OptionalScorerDep,
    SessionDep,
    SettingsDep,
    error_responses,
)
from hextrack.api.schemas import (
    LeaderboardQueue,
    LuckInsights,
    MatchupInsights,
    ScheduleInsights,
    SessionInsights,
    StatsSince,
)
from hextrack.api.v1.summoners import require_summoner
from hextrack.stats import insights, queries
from hextrack.stats.filters import MATCHUP_MIN_GAMES_DEFAULT

router = APIRouter(prefix="/summoners", tags=["insights"])

Puuid = Annotated[str, Path(min_length=1, max_length=100, pattern=SAFE_TEXT)]
#: IANA zone names: letters, digits, "_", "+", "-" and "/" (e.g. America/Argentina/Buenos_Aires,
#: Etc/GMT+5).
TZ_PATTERN = r"^[A-Za-z0-9_+\-/]+$"
DEFAULT_TZ = "America/Chicago"


def parse_tz(tz: str) -> ZoneInfo:
    """The ZoneInfo for an IANA name; 400 ``invalid_tz`` when it is unknown."""
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ApiError(400, f"Unknown time zone: {tz}", "invalid_tz") from exc


@router.get(
    "/{puuid}/insights/sessions",
    response_model=SessionInsights,
    summary="Tilt detector: win rate and AI Score by game number within a play session",
    responses=error_responses(404),
)
async def get_session_insights(
    puuid: Puuid,
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    since: StatsSince = "season",
    queue: LeaderboardQueue = "all",
    gap_minutes: Annotated[
        int,
        Query(
            ge=10,
            le=180,
            description="Largest break (minutes) between one game's end and the next "
            "game's start that still counts as the same session",
        ),
    ] = 45,
) -> SessionInsights:
    await require_summoner(session, puuid)
    model_version = await queries.resolve_model_version(session, scorer, puuid=puuid)
    return await insights.session_insights(
        session,
        settings,
        puuid,
        since=since,
        queue=queue,
        gap_minutes=gap_minutes,
        model_version=model_version,
    )


@router.get(
    "/{puuid}/insights/schedule",
    response_model=ScheduleInsights,
    summary="Best time to play: win rate by day of week and hour (in the given time zone)",
    responses=error_responses(400, 404),
)
async def get_schedule_insights(
    puuid: Puuid,
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    since: StatsSince = "season",
    queue: LeaderboardQueue = "all",
    tz: Annotated[
        str,
        Query(
            min_length=1,
            max_length=64,
            pattern=TZ_PATTERN,
            description="IANA time zone for day of week / hour (the browser's zone)",
        ),
    ] = DEFAULT_TZ,
) -> ScheduleInsights:
    zone = parse_tz(tz)  # 400 before 404, so a bad zone is reported for any player
    await require_summoner(session, puuid)
    model_version = await queries.resolve_model_version(session, scorer, puuid=puuid)
    return await insights.schedule_insights(
        session,
        settings,
        puuid,
        since=since,
        queue=queue,
        tz=zone,
        model_version=model_version,
    )


@router.get(
    "/{puuid}/insights/matchups",
    response_model=MatchupInsights,
    summary="Nemesis champions: record against each enemy champion in the player's lane",
    responses=error_responses(404),
)
async def get_matchup_insights(
    puuid: Puuid,
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    since: StatsSince = "season",
    queue: LeaderboardQueue = "all",
    min_games: Annotated[
        int, Query(ge=1, le=20, description="Fewest games against a champion to list it")
    ] = MATCHUP_MIN_GAMES_DEFAULT,
) -> MatchupInsights:
    await require_summoner(session, puuid)
    model_version = await queries.resolve_model_version(session, scorer, puuid=puuid)
    return await insights.matchup_insights(
        session,
        settings,
        puuid,
        since=since,
        queue=queue,
        min_games=min_games,
        model_version=model_version,
    )


@router.get(
    "/{puuid}/insights/luck",
    response_model=LuckInsights,
    summary="Unlucky losses (high score, lost) and lucky wins (low score, won)",
    responses=error_responses(404),
)
async def get_luck_insights(
    puuid: Puuid,
    session: SessionDep,
    settings: SettingsDep,
    scorer: OptionalScorerDep,
    since: StatsSince = "season",
    queue: LeaderboardQueue = "all",
    limit: Annotated[int, Query(ge=1, le=20, description="Games per list")] = 5,
) -> LuckInsights:
    await require_summoner(session, puuid)
    model_version = await queries.resolve_model_version(session, scorer, puuid=puuid)
    return await insights.luck_insights(
        session,
        settings,
        puuid,
        since=since,
        queue=queue,
        limit=limit,
        model_version=model_version,
    )
