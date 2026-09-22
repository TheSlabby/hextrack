"""Database reads (and the two small app_state writes) used by the Discord bot.

The bot never calls Riot: every name, icon and rank it shows comes from these queries.
Functions take an open :class:`AsyncSession` and never commit; callers own the transaction.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, case, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import AppState, MatchParticipant, RankSnapshot, Summoner
from hextrack.rank import RANKED_SOLO_5x5, rank_value
from hextrack.riotid import InvalidRiotId, format_riot_id, parse_any
from hextrack.stats.queries import is_current_rank

logger = logging.getLogger(__name__)

#: Discord allows at most 25 autocomplete choices.
MAX_CHOICES = 25


# --- summoners ----------------------------------------------------------------------------


async def get_summoners(session: AsyncSession, puuids: Iterable[str]) -> dict[str, Summoner]:
    """``puuid -> Summoner`` for the puuids we know (unknown ones are simply absent)."""
    wanted = {p for p in puuids if p}
    if not wanted:
        return {}
    rows = await session.scalars(select(Summoner).where(Summoner.puuid.in_(wanted)))
    return {row.puuid: row for row in rows}


def _search_text(value: str) -> str:
    """Lower-case, NFC, collapsed-whitespace form comparable with Postgres ``lower()``."""
    return " ".join(unicodedata.normalize("NFC", value).split()).lower()


async def search_roster(
    session: AsyncSession, current: str, *, limit: int = MAX_CHOICES
) -> list[Summoner]:
    """Tracked summoners whose ``Name#TAG`` contains ``current`` (case-insensitive).

    Prefix matches come first, then alphabetical by name. An empty ``current`` lists the
    roster alphabetically. Used by the ``/lp`` autocomplete.
    """
    riot_id = func.lower(func.concat(Summoner.game_name, "#", Summoner.tag_line))
    stmt = select(Summoner).where(Summoner.is_tracked.is_(True))
    needle = _search_text(current)
    order: list[Any] = []
    if needle:
        stmt = stmt.where(riot_id.contains(needle, autoescape=True))
        order.append(case((riot_id.startswith(needle, autoescape=True), 0), else_=1))
    order += [func.lower(Summoner.game_name), func.lower(Summoner.tag_line), Summoner.puuid]
    rows = await session.scalars(stmt.order_by(*order).limit(max(1, min(limit, MAX_CHOICES))))
    return list(rows)


async def resolve_tracked(session: AsyncSession, value: str) -> Summoner | None:
    """Find the tracked summoner a ``/lp`` argument refers to.

    Accepts, in order: an exact puuid, ``Name#TAG`` or the URL slug ``Name-TAG``
    (case-insensitive), or a bare game name when exactly one tracked player has it.
    """
    text = value.strip()
    if not text:
        return None
    tracked = Summoner.is_tracked.is_(True)

    by_puuid = await session.scalar(select(Summoner).where(tracked, Summoner.puuid == text))
    if by_puuid is not None:
        return by_puuid

    try:
        riot_id = parse_any(text)
    except InvalidRiotId:
        riot_id = None
    if riot_id is not None:
        match = await session.scalar(
            select(Summoner)
            .where(
                tracked,
                func.lower(Summoner.game_name) == func.lower(riot_id.game_name),
                func.lower(Summoner.tag_line) == func.lower(riot_id.tag_line),
            )
            .order_by(Summoner.puuid)
            .limit(1)
        )
        if match is not None:
            return match

    name = " ".join(unicodedata.normalize("NFC", text).split())
    same_name = list(
        await session.scalars(
            select(Summoner)
            .where(tracked, func.lower(Summoner.game_name) == func.lower(name))
            .limit(2)
        )
    )
    return same_name[0] if len(same_name) == 1 else None


# --- ranks --------------------------------------------------------------------------------


async def latest_rank(
    session: AsyncSession,
    puuid: str,
    queue_type: str = RANKED_SOLO_5x5,
    *,
    season_start: datetime | None = None,
) -> RankSnapshot | None:
    """Current rank snapshot for ``puuid`` in ``queue_type``, or None when unranked there.

    With ``season_start`` the snapshot has to still be the player's standing
    (:func:`hextrack.stats.queries.is_current_rank`): one from before the season, or older
    than the summoner's last refresh by more than the rank heartbeat (league-v4 returned no
    entry for that queue), means unranked, exactly as the website reports it. Without it the
    newest snapshot is returned whatever its age.
    """
    snapshot: RankSnapshot | None = await session.scalar(
        select(RankSnapshot)
        .where(RankSnapshot.puuid == puuid, RankSnapshot.queue_type == queue_type)
        .order_by(RankSnapshot.taken_at.desc(), RankSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None or season_start is None:
        return snapshot
    last_refreshed_at = await session.scalar(
        select(Summoner.last_refreshed_at).where(Summoner.puuid == puuid)
    )
    if is_current_rank(
        snapshot,
        last_refreshed_at=last_refreshed_at,
        season_start=season_start,
        now=datetime.now(UTC),
    ):
        return snapshot
    return None


@dataclass(frozen=True, slots=True)
class LpDelta:
    """Season-to-date change of one tracked player's ladder position."""

    puuid: str
    game_name: str
    tag_line: str
    start_value: int
    end_value: int

    @property
    def delta(self) -> int:
        return self.end_value - self.start_value

    @property
    def riot_id(self) -> str:
        return format_riot_id(self.game_name, self.tag_line)


def snapshot_value(tier: str, rank: str | None, lp: int, stored: int) -> int:
    """:func:`hextrack.rank.rank_value` of a snapshot, falling back to the stored column
    when the row has a tier or division this version does not know."""
    try:
        return rank_value(tier, rank, lp)
    except ValueError:
        logger.warning("rank snapshot with unknown standing %r %r; using stored value", tier, rank)
        return stored


async def season_lp_deltas(
    session: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
    queue_type: str = RANKED_SOLO_5x5,
) -> list[LpDelta]:
    """LP change since ``since`` for every tracked player (LPBot ``getLPDiff``).

    The baseline is the player's first snapshot taken at or after ``since``; the end is
    their latest snapshot at or before ``until`` (default: now). Players with no snapshot
    in that window are left out. Both ends go through :func:`rank_value`, so Master,
    Grandmaster and Challenger share one LP ladder that starts where Diamond I 100 LP ends.
    """
    until = until or datetime.now(UTC)
    window = and_(RankSnapshot.queue_type == queue_type, RankSnapshot.taken_at <= until)
    cols = (
        RankSnapshot.puuid,
        RankSnapshot.tier,
        RankSnapshot.rank,
        RankSnapshot.lp,
        RankSnapshot.rank_value,
    )
    first = (
        select(*cols)
        .where(window, RankSnapshot.taken_at >= since)
        .distinct(RankSnapshot.puuid)
        .order_by(RankSnapshot.puuid, RankSnapshot.taken_at.asc(), RankSnapshot.id.asc())
        .subquery("first_snapshot")
    )
    last = (
        select(*cols)
        .where(window)
        .distinct(RankSnapshot.puuid)
        .order_by(RankSnapshot.puuid, RankSnapshot.taken_at.desc(), RankSnapshot.id.desc())
        .subquery("last_snapshot")
    )
    stmt = (
        select(
            Summoner.puuid,
            Summoner.game_name,
            Summoner.tag_line,
            first.c.tier,
            first.c.rank,
            first.c.lp,
            first.c.rank_value,
            last.c.tier,
            last.c.rank,
            last.c.lp,
            last.c.rank_value,
        )
        .join(first, first.c.puuid == Summoner.puuid)
        .join(last, last.c.puuid == Summoner.puuid)
        .where(Summoner.is_tracked.is_(True))
        .order_by(func.lower(Summoner.game_name), Summoner.puuid)
    )
    result = await session.execute(stmt)
    deltas: list[LpDelta] = []
    for row in result.all():
        (puuid, game_name, tag_line, t0, r0, lp0, v0, t1, r1, lp1, v1) = tuple(row)
        deltas.append(
            LpDelta(
                puuid=puuid,
                game_name=game_name,
                tag_line=tag_line,
                start_value=snapshot_value(t0, r0, lp0, v0),
                end_value=snapshot_value(t1, r1, lp1, v1),
            )
        )
    return deltas


# --- AI scores ----------------------------------------------------------------------------


async def ai_scores(
    session: AsyncSession, keys: Iterable[tuple[str, str]]
) -> dict[tuple[str, str], float]:
    """``(match_id, puuid) -> ai_score`` for the scored participant rows among ``keys``."""
    wanted = {k for k in keys if k[0] and k[1]}
    if not wanted:
        return {}
    rows = await session.execute(
        select(MatchParticipant.match_id, MatchParticipant.puuid, MatchParticipant.ai_score).where(
            tuple_(MatchParticipant.match_id, MatchParticipant.puuid).in_(list(wanted)),
            MatchParticipant.ai_score.is_not(None),
        )
    )
    return {(m, p): float(s) for m, p, s in rows.all()}


# --- app_state ----------------------------------------------------------------------------


async def get_state(session: AsyncSession, key: str) -> dict[str, Any] | None:
    value = await session.scalar(select(AppState.value).where(AppState.key == key))
    return dict(value) if value is not None else None


async def put_state(session: AsyncSession, key: str, value: dict[str, Any]) -> None:
    """Insert or replace ``app_state[key]``."""
    stmt = pg_insert(AppState).values(key=key, value=value)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[AppState.key],
            set_={"value": stmt.excluded.value, "updated_at": func.now()},
        )
    )


async def lock_state(session: AsyncSession, key: str) -> dict[str, Any]:
    """Row-lock ``app_state[key]`` (creating it as ``{}``) for the rest of the transaction
    and return its value. Serialises read-modify-write sections across processes."""
    await session.execute(
        pg_insert(AppState)
        .values(key=key, value={})
        .on_conflict_do_nothing(index_elements=[AppState.key])
    )
    value = await session.scalar(
        select(AppState.value).where(AppState.key == key).with_for_update()
    )
    return dict(value or {})
