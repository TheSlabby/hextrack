"""Match and participant writes used by ingestion (idempotent inserts, AI score writes)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Text, any_, bindparam, func, select, update
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import Match, MatchParticipant


async def existing_match_ids(session: AsyncSession, match_ids: Sequence[str]) -> set[str]:
    """The subset of ``match_ids`` already stored, in one ``= ANY(:ids)`` query."""
    if not match_ids:
        return set()
    stmt = select(Match.match_id).where(
        Match.match_id == any_(bindparam("match_ids", list(match_ids), type_=ARRAY(Text)))
    )
    return set(await session.scalars(stmt))


async def match_exists(session: AsyncSession, match_id: str) -> bool:
    return bool(await existing_match_ids(session, [match_id]))


async def match_starts(session: AsyncSession, match_ids: Sequence[str]) -> dict[str, datetime]:
    """``{match_id: game_start}`` for the stored subset of ``match_ids`` (one query)."""
    if not match_ids:
        return {}
    stmt = select(Match.match_id, Match.game_start).where(
        Match.match_id == any_(bindparam("match_ids", list(match_ids), type_=ARRAY(Text)))
    )
    return {row[0]: row[1] for row in (await session.execute(stmt)).all()}


async def has_games(session: AsyncSession, puuid: str) -> bool:
    """True when at least one stored match includes ``puuid``."""
    stmt = select(MatchParticipant.match_id).where(MatchParticipant.puuid == puuid).limit(1)
    return await session.scalar(stmt) is not None


async def insert_match(session: AsyncSession, row: Mapping[str, Any]) -> bool:
    """``INSERT ... ON CONFLICT DO NOTHING``; True when the row was created."""
    stmt = (
        insert(Match)
        .values(**row)
        .on_conflict_do_nothing(index_elements=[Match.match_id])
        .returning(Match.match_id)
    )
    created = await session.scalar(stmt)
    return created is not None


async def insert_participants(session: AsyncSession, rows: Sequence[Mapping[str, Any]]) -> None:
    """Insert participant rows, skipping any (match_id, puuid) that already exists."""
    if not rows:
        return
    stmt = insert(MatchParticipant).on_conflict_do_nothing(
        index_elements=[MatchParticipant.match_id, MatchParticipant.puuid]
    )
    await session.execute(stmt, [dict(r) for r in rows])


@dataclass(frozen=True, slots=True)
class StoredMatch:
    """What ingestion needs to know about an already stored match (``raw`` not loaded)."""

    match_id: str
    scored_at: datetime | None
    model_version: str | None
    participants: int


async def stored_match(session: AsyncSession, match_id: str) -> StoredMatch | None:
    """Scoring state and participant count of a stored match, or None when unknown."""
    stmt = (
        select(
            Match.match_id,
            Match.scored_at,
            Match.model_version,
            func.count(MatchParticipant.puuid),
        )
        .outerjoin(MatchParticipant, MatchParticipant.match_id == Match.match_id)
        .where(Match.match_id == match_id)
        .group_by(Match.match_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return StoredMatch(
        match_id=row[0], scored_at=row[1], model_version=row[2], participants=int(row[3])
    )


async def write_scores(
    session: AsyncSession,
    match_id: str,
    scores: Mapping[str, float],
    *,
    model_version: str,
    scored_at: datetime,
    complete: bool,
) -> None:
    """Store ``{puuid: ai_score}`` for one match's participants.

    ``complete`` marks the match itself as scored by ``model_version`` (only when every
    participant received a score).
    """
    if scores:
        await session.execute(
            update(MatchParticipant).execution_options(synchronize_session=False),
            [
                {
                    "match_id": match_id,
                    "puuid": puuid,
                    "ai_score": float(score),
                    "ai_scored_at": scored_at,
                    "model_version": model_version,
                }
                for puuid, score in scores.items()
            ],
        )
    if complete:
        await session.execute(
            update(Match)
            .where(Match.match_id == match_id)
            .values(scored_at=scored_at, model_version=model_version)
            .execution_options(synchronize_session=False)
        )
