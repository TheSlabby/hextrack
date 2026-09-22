"""Curated friends roster management (owner: B2).

The roster is the set of ``summoners`` rows with ``is_tracked``; the poller keeps them
fresh and only they produce bot events. Functions run in the caller's session and do not
commit.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import Summoner
from hextrack.db.repo import summoners as summoners_repo
from hextrack.ingest import service
from hextrack.ingest.context import IngestContext
from hextrack.riot.errors import RiotNotFound
from hextrack.riotid import InvalidRiotId, RiotId, parse_riot_id

logger = logging.getLogger(__name__)


class RosterError(Exception):
    """The Riot ID could not be added (invalid format or unknown account)."""


def _parse(riot_id: str) -> RiotId:
    try:
        return parse_riot_id(riot_id)
    except InvalidRiotId as exc:
        raise RosterError(str(exc)) from exc


async def _resolve(ctx: IngestContext, session: AsyncSession, rid: RiotId) -> Summoner:
    """The stored summoner for ``rid``, creating (and refreshing) it through Riot."""
    platform = ctx.settings.riot_platform
    found = await summoners_repo.find_by_riot_id(
        session, rid.game_name, rid.tag_line, platform=platform
    )
    if found is not None:
        if found.is_tracked:
            return found
        # Stored but not tracked (looked up once, legacy-imported, untracked earlier): take
        # a fresh standing before tracking starts, so the first poll compares against
        # today's rank instead of announcing a months-old promotion.
        return await service.refresh_summoner(ctx, session, found.puuid)
    try:
        account = await ctx.riot.account_by_riot_id(rid.game_name, rid.tag_line)
    except RiotNotFound as exc:
        raise RosterError(f"no Riot account named {rid}") from exc
    try:
        async with session.begin_nested():
            known = await summoners_repo.get_by_puuid(session, account.puuid)
            summoner = await service.store_identity(
                ctx,
                session,
                puuid=account.puuid,
                game_name=account.game_name or rid.game_name,
                tag_line=account.tag_line or rid.tag_line,
                platform=known.platform if known is not None else platform,
            )
            if known is None:
                # Icon, level and a first rank snapshot, taken before tracking starts so
                # the first poll never announces a "tier change".
                summoner = await service.refresh_summoner(ctx, session, summoner.puuid)
    except RiotNotFound as exc:
        raise RosterError(f"{rid} has no League of Legends profile") from exc
    return summoner


async def add_to_roster(ctx: IngestContext, session: AsyncSession, riot_id: str) -> Summoner:
    """Resolve ``riot_id`` ("Name#TAG"), upsert the summoner, set ``is_tracked=True`` and
    ``tracked_since`` (kept if already tracked). Idempotent. Raises RosterError for an
    invalid Riot ID or unknown account; other RiotErrors propagate.

    A player who is not tracked yet is refreshed first (whether they were stored already or
    not), so their first poll as a roster member compares against a standing from today and
    the bot does not announce a rank change from months ago.

    Starting to track someone clears ``backfilled_at`` so the poller runs a season backfill
    for them on its next tick.
    """
    summoner = await _resolve(ctx, session, _parse(riot_id))
    if not summoner.is_tracked:
        summoner.is_tracked = True
        summoner.tracked_since = datetime.now(UTC)
        summoner.backfilled_at = None
        # Their watermark (if any) only covers the recent games an earlier lookup fetched;
        # the backfill re-anchors it at the season start.
        summoner.synced_through = None
        await session.flush([summoner])
        logger.info("now tracking %s", summoner.riot_id)
    return summoner


async def remove_from_roster(session: AsyncSession, riot_id: str) -> bool:
    """Untrack (data is kept). Returns False when no tracked summoner matched. Raises
    RosterError for an invalid Riot ID."""
    rid = _parse(riot_id)
    rows = await summoners_repo.find_all_by_riot_id(
        session, rid.game_name, rid.tag_line, tracked_only=True
    )
    for summoner in rows:
        summoner.is_tracked = False
        summoner.tracked_since = None
        logger.info("stopped tracking %s", summoner.riot_id)
    if rows:
        await session.flush(rows)
    return bool(rows)


async def list_roster(session: AsyncSession) -> list[Summoner]:
    """Tracked summoners ordered by game_name (case-insensitive)."""
    return await summoners_repo.list_tracked(session)
