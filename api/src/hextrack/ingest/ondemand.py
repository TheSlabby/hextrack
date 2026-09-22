"""Any-player lookup and the op.gg-style "Update" button (owner: B2).

Both entry points serve an HTTP request, so they hold the database as briefly as they can:
the rank refresh is committed before any match is fetched (it takes a per-summoner advisory
lock and the summoner row, which the worker needs too), and every match is ingested in its
own transaction. A Riot call is never made with an open write transaction around it.

Public traffic is throttled twice over, because these endpoints need no authentication and
spend the shared Riot key: :class:`OnDemandGuard` bounds how many requests may be inside the
Riot part at once, and the client's own budget (``RIOT_ONDEMAND_RATE_LIMITS``) bounds how
much of the key they may take. Riot IDs that cannot exist, and recent "no such account"
answers, never reach Riot at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import Summoner
from hextrack.db.repo import summoners as summoners_repo
from hextrack.ingest import service
from hextrack.ingest.context import IngestContext
from hextrack.riot.errors import RiotNotFound, RiotRateLimited, RiotUnavailable
from hextrack.riotid import (
    is_plausible_riot_id,
    normalize_game_name,
    normalize_tag_line,
    riot_id_key,
)

logger = logging.getLogger(__name__)

#: "unavailable" is only produced by the API layer (Riot key missing/rejected for a stored
#: player); refresh_on_demand itself never returns it.
RefreshStatus = Literal["ok", "cooldown", "partial", "unavailable"]

#: Stop ingesting inline (status ``partial``) once the Riot limiter would make the next
#: request wait longer than this; the user gets an answer instead of a hanging request.
MAX_LIMITER_WAIT_SECONDS: Final = 5.0
#: Most match ids one request may list. Two pages of 100: an Update click on a player who
#: stopped playing for months must not page through a whole season before it answers.
MAX_LISTED_IDS: Final = 200
#: Riot lookups running at once in this process; the rest is turned away straight away.
MAX_CONCURRENT_LOOKUPS: Final = 2
#: How long a request waits for a slot before it gives up.
GUARD_WAIT_SECONDS: Final = 0.5
#: How long "no such Riot account" is remembered, so retyping a name is free.
MISS_TTL_SECONDS: Final = 600.0
#: Riot IDs kept in that negative cache.
MISS_CACHE_SIZE: Final = 512


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class RefreshOutcome:
    #: ok: fully refreshed; cooldown: refused, still within the cooldown window;
    #: partial: rank refreshed but more than ``ondemand_max_matches`` new matches remain
    #: (or Riot's rate limit stopped the inline ingest early).
    status: RefreshStatus
    new_matches: int
    #: New match ids discovered but not ingested yet.
    pending: int
    #: When the next refresh will be accepted (tz-aware UTC).
    next_allowed_at: datetime
    message: str


class MissCache:
    """Riot IDs Riot said it does not know, remembered for :data:`MISS_TTL_SECONDS`.

    Every miss otherwise costs one account-v1 request, so a stream of made-up names (or one
    impatient visitor) eats the key's budget.
    """

    __slots__ = ("_entries", "_ttl", "_clock")

    def __init__(
        self, ttl: float = MISS_TTL_SECONDS, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._entries: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._ttl = ttl
        self._clock = clock

    def _now(self) -> float:
        return float(self._clock())

    def hit(self, key: tuple[str, str]) -> bool:
        expires = self._entries.get(key)
        if expires is None:
            return False
        if expires <= self._now():
            self._entries.pop(key, None)
            return False
        return True

    def add(self, key: tuple[str, str]) -> None:
        self._entries.pop(key, None)
        self._entries[key] = self._now() + self._ttl
        while len(self._entries) > MISS_CACHE_SIZE:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()


@dataclass(slots=True)
class OnDemandGuard:
    """Caps how many requests may be doing Riot work at once in this process.

    Without it a burst of lookups parks a pooled database connection each (and a Riot call
    each) until the pool runs out and every endpoint, ``/health`` included, starts failing.
    """

    limit: int = MAX_CONCURRENT_LOOKUPS
    wait: float = GUARD_WAIT_SECONDS
    _semaphore: asyncio.Semaphore | None = field(default=None, init=False, repr=False)

    def _sem(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(max(self.limit, 1))
        return self._semaphore

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        semaphore = self._sem()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self.wait)
        except TimeoutError:
            logger.info("on-demand lookup turned away: %d already running", self.limit)
            raise RiotRateLimited(
                "HexTrack is busy looking up other players; try again in a moment",
                retry_after=2.0,
            ) from None
        try:
            yield
        finally:
            semaphore.release()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}es" if word.endswith("ch") else f"{n} {word}s"


async def get_or_resolve_summoner(
    ctx: IngestContext, session: AsyncSession, game_name: str, tag_line: str
) -> Summoner | None:
    """Look up a Riot ID case-insensitively in the DB; if unknown, resolve it through
    account-v1 + summoner-v4, insert it and run a first bounded refresh. Returns None
    when Riot has no such account (or it has no League profile). Other RiotErrors
    propagate, and nothing is left in the session in that case."""
    summoner, _first_refresh = await resolve_summoner(ctx, session, game_name, tag_line)
    return summoner


async def resolve_summoner(
    ctx: IngestContext, session: AsyncSession, game_name: str, tag_line: str
) -> tuple[Summoner | None, RefreshOutcome | None]:
    """:func:`get_or_resolve_summoner` that also returns the outcome of the first bounded
    refresh when this call created the player (None when it was already stored), so an
    Update click on a never-seen player can report what the lookup ingested instead of
    an immediate cooldown."""
    name, tag = normalize_game_name(game_name), normalize_tag_line(tag_line)
    if not name or not tag:
        return None, None
    platform = ctx.settings.riot_platform
    found = await summoners_repo.find_by_riot_id(session, name, tag, platform=platform)
    if found is not None:
        return found, None
    # Nothing stored: from here on the request costs Riot requests.
    key = riot_id_key(name, tag)
    if not is_plausible_riot_id(name, tag) or ctx.lookup_misses.hit(key):
        return None, None
    # Hold no transaction (and no pooled connection) across the Riot calls that follow.
    await session.rollback()

    async with ctx.ondemand_guard.slot():
        try:
            account = await ctx.riot.account_by_riot_id(name, tag)
        except RiotNotFound:
            ctx.lookup_misses.add(key)
            return None, None
        try:
            async with session.begin_nested():
                known = await summoners_repo.get_by_puuid(session, account.puuid)
                summoner = await service.store_identity(
                    ctx,
                    session,
                    puuid=account.puuid,
                    game_name=account.game_name or name,
                    tag_line=account.tag_line or tag,
                    platform=known.platform if known is not None else platform,
                )
                new_player = known is None
                if new_player:
                    # A brand-new player: fill icon, level and rank before any match work.
                    await service.refresh_summoner(ctx, session, summoner.puuid)
        except RiotNotFound:
            logger.info("%s#%s has an account but no League profile", name, tag)
            ctx.lookup_misses.add(key)
            return None, None
        puuid = account.puuid
        await session.commit()
        first_refresh = (
            await _ingest_bounded(ctx, session, puuid, _next_allowed_at(ctx, _utcnow()))
            if new_player
            else None
        )
    return await summoners_repo.get_by_puuid(session, puuid), first_refresh


async def refresh_on_demand(
    ctx: IngestContext, session: AsyncSession, puuid: str
) -> RefreshOutcome:
    """Refresh rank and ingest up to ``ondemand_max_matches`` new matches inline unless the
    summoner was refreshed within ``ondemand_cooldown_seconds``.

    A known player's Riot ID is re-read through account-v1 as well, so an explicit update
    picks up renames. Status ``partial`` when more new matches remain than were ingested,
    including when the Riot limiter would wait more than :data:`MAX_LIMITER_WAIT_SECONDS`
    or Riot rate limited / failed a match request midway (what was ingested so far is
    kept). Errors from the rank refresh propagate.
    """
    cooldown = timedelta(seconds=ctx.settings.ondemand_cooldown_seconds)
    now = _utcnow()
    summoner = await summoners_repo.get_by_puuid(session, puuid)
    if summoner is not None and summoner.last_refreshed_at is not None and cooldown:
        next_allowed_at = summoner.last_refreshed_at + cooldown
        if now < next_allowed_at:
            wait = math.ceil((next_allowed_at - now).total_seconds())
            return RefreshOutcome(
                status="cooldown",
                new_matches=0,
                pending=0,
                next_allowed_at=next_allowed_at,
                message=f"Updated recently; try again in {wait}s",
            )
    await session.rollback()  # no open transaction while Riot is called
    async with ctx.ondemand_guard.slot():
        return await _refresh_bounded(ctx, session, puuid, verify_identity=summoner is not None)


def _next_allowed_at(ctx: IngestContext, refreshed_at: datetime) -> datetime:
    return refreshed_at + timedelta(seconds=ctx.settings.ondemand_cooldown_seconds)


async def _refresh_bounded(
    ctx: IngestContext, session: AsyncSession, puuid: str, *, verify_identity: bool
) -> RefreshOutcome:
    """Rank refresh plus at most ``ondemand_max_matches`` new matches, no cooldown check."""
    summoner = await service.refresh_summoner(ctx, session, puuid, verify_identity=verify_identity)
    next_allowed_at = _next_allowed_at(ctx, summoner.last_refreshed_at or _utcnow())
    # Commit before touching Riot again: this transaction holds the per-summoner advisory
    # lock and the summoner row, which the worker needs to ingest the very same game.
    await session.commit()
    return await _ingest_bounded(ctx, session, puuid, next_allowed_at)


async def _ingest_bounded(
    ctx: IngestContext, session: AsyncSession, puuid: str, next_allowed_at: datetime
) -> RefreshOutcome:
    """Ingest at most ``ondemand_max_matches`` of the player's missing matches, newest first
    and one transaction each, then move their discovery watermark up over what is stored."""
    settings = ctx.settings
    interrupted: str | None = None
    try:
        discovery = await service.discover(
            ctx, session, puuid, backfill=False, max_ids=MAX_LISTED_IDS
        )
    except (RiotRateLimited, RiotUnavailable) as exc:
        # The rank refresh is committed; the poller (or the next click) lists the matches.
        await session.rollback()
        logger.info("on-demand: could not list matches for %s: %s", puuid, exc)
        return RefreshOutcome(
            status="partial",
            new_matches=0,
            pending=0,
            next_allowed_at=next_allowed_at,
            message="Updated rank; Riot API is busy, new matches will follow shortly",
        )
    await session.rollback()  # end the read transaction: Riot calls follow

    created = 0
    processed = 0
    resolved: set[str] = set()
    for match_id in discovery.missing:
        if processed >= settings.ondemand_max_matches:
            break
        if ctx.riot.limiter_wait_estimate() > MAX_LIMITER_WAIT_SECONDS:
            interrupted = "Riot API is busy"
            break
        try:
            result = await service.ingest_match(ctx, session, match_id)
            await session.commit()
        except RiotRateLimited:
            await session.rollback()
            interrupted = "Riot API rate limit reached"
            break
        except RiotUnavailable:
            await session.rollback()
            interrupted = "Riot API is unavailable"
            break
        except BaseException:
            await session.rollback()
            raise
        processed += 1
        resolved.add(match_id)
        if result is not None and result.created:
            created += 1

    await service.advance_sync(session, discovery, resolved)
    await session.commit()

    pending = len(discovery.missing) - processed
    if pending == 0:
        message = f"Updated: {_plural(created, 'new match')}" if created else "Already up to date"
        status: RefreshStatus = "ok"
    else:
        reason = f"{interrupted}; " if interrupted else ""
        message = (
            f"Updated rank and {_plural(created, 'new match')}; "
            f"{reason}{_plural(pending, 'match')} still to fetch"
        )
        status = "partial"
    return RefreshOutcome(
        status=status,
        new_matches=created,
        pending=pending,
        next_allowed_at=next_allowed_at,
        message=message,
    )
