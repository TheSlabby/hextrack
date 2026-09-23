"""Summoner profile, on-demand refresh, match history and rank history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.api.deps import (
    RIOT_ERRORS,
    SAFE_TEXT,
    ApiError,
    CtxDep,
    OptionalScorerDep,
    SessionDep,
    error_responses,
)
from hextrack.api.schemas import MatchPage, QueueType, RankHistory, RefreshResult, SummonerProfile
from hextrack.db.models import Summoner
from hextrack.ingest import ondemand
from hextrack.ingest.context import IngestContext
from hextrack.riot.errors import RiotForbidden, RiotKeyMissing
from hextrack.riotid import InvalidRiotId, RiotId, parse_riot_id
from hextrack.stats import aggregate, present, queries
from hextrack.stats.role_percentile import ROLE_PERCENTILES

router = APIRouter(prefix="/summoners", tags=["summoners"])

#: Most queue ids one match-history request may filter on.
MAX_QUEUE_FILTERS = 10
#: Largest queue id accepted: Riot's ids are small, and anything above int32 overflows the
#: bind parameter instead of returning an empty page.
MAX_QUEUE_ID = 2**31 - 1
GameName = Annotated[
    str, Path(min_length=1, max_length=32, pattern=SAFE_TEXT, description="Riot ID game name")
]
TagLine = Annotated[
    str, Path(min_length=1, max_length=8, pattern=SAFE_TEXT, description="Riot ID tag line")
]
Puuid = Annotated[str, Path(min_length=1, max_length=100, pattern=SAFE_TEXT)]


def parse_path_riot_id(game_name: str, tag_line: str) -> RiotId:
    """Validate a Riot ID taken from two path segments; 400 ``invalid_riot_id`` if bad."""
    try:
        return parse_riot_id(f"{game_name}#{tag_line}")
    except InvalidRiotId as exc:
        raise ApiError(400, str(exc), "invalid_riot_id") from exc


async def require_summoner(session: AsyncSession, puuid: str) -> None:
    """404 ``not_found`` unless ``puuid`` is a known summoner."""
    if not await queries.summoner_exists(session, puuid):
        raise ApiError(404, "Summoner not found", "not_found")


async def _resolve_summoner(session: AsyncSession, ctx: IngestContext, riot_id: RiotId) -> Summoner:
    """Known summoner from the DB, else resolve it through Riot (inserting it); 404 when
    Riot has no such account. Riot errors propagate to the global handlers."""
    summoner = await queries.find_summoner_by_riot_id(
        session, riot_id.game_name, riot_id.tag_line, platform=ctx.settings.riot_platform
    )
    if summoner is not None:
        return summoner
    summoner = await ondemand.get_or_resolve_summoner(
        ctx, session, riot_id.game_name, riot_id.tag_line
    )
    if summoner is None:
        raise ApiError(404, f"No Riot account named {riot_id}", "not_found")
    await session.commit()
    return summoner


async def _resolve_with_outcome(
    session: AsyncSession, ctx: IngestContext, riot_id: RiotId
) -> tuple[Summoner, ondemand.RefreshOutcome | None]:
    """:func:`_resolve_summoner` plus the first bounded refresh's outcome when this request
    created the player (None for a player already stored)."""
    summoner = await queries.find_summoner_by_riot_id(
        session, riot_id.game_name, riot_id.tag_line, platform=ctx.settings.riot_platform
    )
    if summoner is not None:
        return summoner, None
    resolved, first_refresh = await ondemand.resolve_summoner(
        ctx, session, riot_id.game_name, riot_id.tag_line
    )
    if resolved is None:
        raise ApiError(404, f"No Riot account named {riot_id}", "not_found")
    await session.commit()
    return resolved, first_refresh


def _unavailable_outcome(exc: RiotKeyMissing | RiotForbidden) -> ondemand.RefreshOutcome:
    reason = (
        "Riot API key is not configured"
        if isinstance(exc, RiotKeyMissing)
        else "Riot rejected the API key (expired?)"
    )
    return ondemand.RefreshOutcome(
        status="unavailable",
        new_matches=0,
        pending=0,
        next_allowed_at=datetime.now(UTC),
        message=f"{reason}; showing stored data",
    )


async def _build_profile(
    session: AsyncSession, ctx: IngestContext, summoner: Summoner
) -> SummonerProfile:
    version = await queries.resolve_model_version(session, ctx.scorer, puuid=summoner.puuid)
    return await aggregate.summoner_profile(
        session, ctx.settings, summoner, model_version=version, now=datetime.now(UTC)
    )


@router.get(
    "/by-riot-id/{game_name}/{tag_line}",
    response_model=SummonerProfile,
    summary="Profile by Riot ID (resolves unknown players through Riot)",
    responses=error_responses(400, 404, *RIOT_ERRORS),
)
async def get_summoner_profile(
    game_name: GameName, tag_line: TagLine, session: SessionDep, ctx: CtxDep
) -> SummonerProfile:
    riot_id = parse_path_riot_id(game_name, tag_line)
    summoner = await _resolve_summoner(session, ctx, riot_id)
    return await _build_profile(session, ctx, summoner)


@router.post(
    "/by-riot-id/{game_name}/{tag_line}/refresh",
    response_model=RefreshResult,
    summary="Update button: refresh rank and ingest new matches (rate limited per player)",
    responses=error_responses(400, 404, *RIOT_ERRORS),
)
async def refresh_summoner(
    game_name: GameName, tag_line: TagLine, session: SessionDep, ctx: CtxDep
) -> RefreshResult:
    riot_id = parse_path_riot_id(game_name, tag_line)
    summoner, first_refresh = await _resolve_with_outcome(session, ctx, riot_id)
    # Kept as a plain str: a rollback below expires the ORM instance.
    puuid = summoner.puuid
    # A never-seen player was just resolved with a first bounded refresh: report that
    # instead of the cooldown it would otherwise hit straight away.
    if first_refresh is not None:
        outcome = first_refresh
    else:
        try:
            outcome = await ondemand.refresh_on_demand(ctx, session, puuid)
        except (RiotKeyMissing, RiotForbidden) as exc:
            # A stored player degrades to their stored profile; only lookups of players
            # HexTrack has never seen need Riot and answer 503 riot_key.
            await session.rollback()
            outcome = _unavailable_outcome(exc)
    await session.commit()
    # The refresh may have written through another session: reload before reporting.
    refreshed = await session.get(Summoner, puuid, populate_existing=True)
    if refreshed is None:
        raise ApiError(404, "Summoner not found", "not_found")
    return RefreshResult(
        status=outcome.status,
        new_matches=outcome.new_matches,
        pending=outcome.pending,
        next_allowed_at=outcome.next_allowed_at,
        message=outcome.message,
        profile=await _build_profile(session, ctx, refreshed),
    )


@router.get(
    "/{puuid}/matches",
    response_model=MatchPage,
    summary="Match history, newest first (cursor paginated)",
    responses=error_responses(400, 404),
)
async def list_summoner_matches(
    puuid: Puuid,
    session: SessionDep,
    scorer: OptionalScorerDep,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    queue: Annotated[
        list[Annotated[int, Field(ge=0, le=MAX_QUEUE_ID)]] | None,
        Query(
            max_length=MAX_QUEUE_FILTERS,
            description="Filter by queue id; repeat the parameter to match any of several "
            "(e.g. queue=400&queue=430 for normals)",
        ),
    ] = None,
) -> MatchPage:
    await require_summoner(session, puuid)
    try:
        position = queries.decode_cursor(cursor) if cursor else None
    except queries.InvalidCursor as exc:
        raise ApiError(400, "Invalid cursor", "invalid_cursor") from exc
    version = await queries.resolve_model_version(session, scorer, puuid=puuid)
    table = await ROLE_PERCENTILES.ensure_loaded(session, model_version=version)
    return await queries.match_page(
        session, puuid, cursor=position, limit=limit, queue=queue, role_percentiles=table
    )


@router.get(
    "/{puuid}/ranks",
    response_model=RankHistory,
    summary="Rank snapshots for one queue, oldest first",
    responses=error_responses(404),
)
async def get_rank_history(
    puuid: Puuid,
    session: SessionDep,
    queue: QueueType = "RANKED_SOLO_5x5",
) -> RankHistory:
    await require_summoner(session, puuid)
    snapshots = await queries.rank_history(session, puuid, queue)
    points = [point for s in snapshots if (point := present.rank_point(s)) is not None]
    return RankHistory(puuid=puuid, queue_type=queue, points=points)
