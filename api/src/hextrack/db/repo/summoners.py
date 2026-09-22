"""Summoner lookups and writes.

Riot IDs are compared with Postgres ``lower()`` on both sides, the same expression the
``uq_summoners_riot_id_lower`` index uses, so "exists?" checks and the unique constraint
always agree.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import ColumnElement, Text, any_, bindparam, exists, func, select, update
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import MatchParticipant, Summoner
from hextrack.riotid import normalize_game_name, normalize_tag_line


def _riot_id_clause(game_name: str, tag_line: str) -> ColumnElement[bool]:
    name = normalize_game_name(game_name)
    tag = normalize_tag_line(tag_line)
    return (func.lower(Summoner.game_name) == func.lower(name)) & (
        func.lower(Summoner.tag_line) == func.lower(tag)
    )


async def get_by_puuid(session: AsyncSession, puuid: str) -> Summoner | None:
    """The summoner row, freshly loaded (identity-map state is overwritten)."""
    return await session.get(Summoner, puuid, populate_existing=True)


async def find_by_riot_id(
    session: AsyncSession,
    game_name: str,
    tag_line: str,
    *,
    platform: str | None = None,
) -> Summoner | None:
    """Case-insensitive Riot ID lookup. With ``platform=None`` any platform matches
    (tracked rows first)."""
    stmt = select(Summoner).where(_riot_id_clause(game_name, tag_line))
    if platform is not None:
        stmt = stmt.where(Summoner.platform == platform.lower())
    stmt = stmt.order_by(Summoner.is_tracked.desc(), Summoner.puuid).limit(1)
    result = await session.scalars(stmt, execution_options={"populate_existing": True})
    return result.first()


async def find_all_by_riot_id(
    session: AsyncSession, game_name: str, tag_line: str, *, tracked_only: bool = False
) -> list[Summoner]:
    """Every row (on any platform) whose Riot ID matches case-insensitively."""
    stmt = select(Summoner).where(_riot_id_clause(game_name, tag_line))
    if tracked_only:
        stmt = stmt.where(Summoner.is_tracked.is_(True))
    result = await session.scalars(
        stmt.order_by(Summoner.platform), execution_options={"populate_existing": True}
    )
    return list(result)


async def find_riot_id_holder(
    session: AsyncSession,
    game_name: str,
    tag_line: str,
    platform: str,
    *,
    exclude_puuid: str,
) -> Summoner | None:
    """Another account currently stored under this Riot ID (a stale name after a rename)."""
    stmt = (
        select(Summoner)
        .where(_riot_id_clause(game_name, tag_line))
        .where(Summoner.platform == platform.lower())
        .where(Summoner.puuid != exclude_puuid)
        .limit(1)
    )
    result = await session.scalars(stmt, execution_options={"populate_existing": True})
    return result.first()


async def upsert_summoner(
    session: AsyncSession,
    *,
    puuid: str,
    game_name: str,
    tag_line: str,
    platform: str,
    profile_icon_id: int | None = None,
    summoner_level: int | None = None,
) -> Summoner:
    """Insert or update by puuid and return the fresh ORM row.

    Name, tag and platform are always overwritten (Riot IDs change); icon and level are
    only overwritten when a value is given. The caller must make sure no *other* puuid
    holds the Riot ID (see :func:`find_riot_id_holder`), otherwise the unique index raises.
    """
    values = {
        "puuid": puuid,
        "game_name": normalize_game_name(game_name),
        "tag_line": normalize_tag_line(tag_line),
        "platform": platform.lower(),
        "profile_icon_id": profile_icon_id,
        "summoner_level": summoner_level,
    }
    stmt = insert(Summoner).values(**values)
    excluded = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=[Summoner.puuid],
        set_={
            "game_name": excluded.game_name,
            "tag_line": excluded.tag_line,
            "platform": excluded.platform,
            "profile_icon_id": func.coalesce(excluded.profile_icon_id, Summoner.profile_icon_id),
            "summoner_level": func.coalesce(excluded.summoner_level, Summoner.summoner_level),
            "updated_at": func.now(),
        },
    ).returning(Summoner)
    result = await session.scalars(stmt, execution_options={"populate_existing": True})
    return result.one()


async def list_tracked(session: AsyncSession) -> list[Summoner]:
    """The roster, ordered by game name then tag (case-insensitive)."""
    stmt = (
        select(Summoner)
        .where(Summoner.is_tracked.is_(True))
        .order_by(func.lower(Summoner.game_name), func.lower(Summoner.tag_line), Summoner.puuid)
    )
    result = await session.scalars(stmt, execution_options={"populate_existing": True})
    return list(result)


async def touch_last_seen(session: AsyncSession, puuids: Collection[str], seen_at: datetime) -> int:
    """Advance ``last_seen`` to ``seen_at`` for the known summoners among ``puuids`` (never
    moves it backwards). Returns the number of rows updated.

    Rows are locked in puuid order (``ORDER BY ... FOR UPDATE``): the worker and an HTTP
    request ingesting the same game touch the same friends, and taking their row locks in a
    fixed order keeps those two transactions from deadlocking on each other.
    """
    if not puuids:
        return 0
    targets = (
        select(Summoner.puuid)
        .where(Summoner.puuid == any_(bindparam("puuids", list(puuids), type_=ARRAY(Text))))
        .where((Summoner.last_seen.is_(None)) | (Summoner.last_seen < seen_at))
        .order_by(Summoner.puuid)
        .with_for_update()
        .scalar_subquery()
    )
    stmt = (
        update(Summoner)
        .where(Summoner.puuid.in_(targets))
        .values(last_seen=seen_at)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


async def known_among(session: AsyncSession, puuids: Collection[str]) -> dict[str, Summoner]:
    """``{puuid: Summoner}`` for every stored summoner among ``puuids`` (one query)."""
    if not puuids:
        return {}
    stmt = select(Summoner).where(
        Summoner.puuid == any_(bindparam("puuids", list(puuids), type_=ARRAY(Text)))
    )
    result = await session.scalars(stmt, execution_options={"populate_existing": True})
    return {s.puuid: s for s in result}


async def get_synced_through(session: AsyncSession, puuid: str) -> datetime | None:
    """The match-discovery watermark: every ranked game of this player between the season
    start (or their first covered game) and this instant is stored. None when discovery has
    never completed a pass for them."""
    return await session.scalar(select(Summoner.synced_through).where(Summoner.puuid == puuid))


async def advance_synced_through(
    session: AsyncSession, puuid: str, at: datetime
) -> datetime | None:
    """Move the watermark forward (never backwards). Returns the new value, or None when
    the stored watermark was already at least ``at``."""
    stmt = (
        update(Summoner)
        .where(Summoner.puuid == puuid)
        .where((Summoner.synced_through.is_(None)) | (Summoner.synced_through < at))
        .values(synced_through=at)
        .returning(Summoner.synced_through)
        .execution_options(synchronize_session=False)
    )
    return await session.scalar(stmt)


async def mark_backfilled(session: AsyncSession, puuids: Collection[str], at: datetime) -> int:
    """Set ``backfilled_at`` for ``puuids``. Returns the number of rows updated."""
    if not puuids:
        return 0
    stmt = (
        update(Summoner)
        .where(Summoner.puuid == any_(bindparam("puuids", list(puuids), type_=ARRAY(Text))))
        .values(backfilled_at=at)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


async def has_matches(session: AsyncSession, puuid: str) -> bool:
    """True when at least one match is stored for ``puuid``."""
    stmt = select(exists().where(MatchParticipant.puuid == puuid))
    return bool(await session.scalar(stmt))
