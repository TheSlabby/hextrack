"""Match and participant writes used by ingestion (idempotent inserts, AI score writes)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import Text, any_, bindparam, case, func, select, update
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import Match, MatchParticipant, MatchTimelinePlayer

#: ``matches.source`` of games stored by the data crawler, and of every other game.
CRAWL_SOURCE: Final = "crawl"
ROSTER_SOURCE: Final = "roster"


async def existing_match_ids(
    session: AsyncSession, match_ids: Sequence[str], *, count_crawled: bool = True
) -> set[str]:
    """The subset of ``match_ids`` already stored, in one ``= ANY(:ids)`` query. With
    ``count_crawled=False`` a game only the data crawler stored does not count: roster and
    lookup ingestion still has to promote it (:func:`promote_crawled_match`)."""
    if not match_ids:
        return set()
    stmt = select(Match.match_id).where(
        Match.match_id == any_(bindparam("match_ids", list(match_ids), type_=ARRAY(Text)))
    )
    if not count_crawled:
        stmt = stmt.where(Match.source != CRAWL_SOURCE)
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
    source: str = ROSTER_SOURCE


async def stored_match(session: AsyncSession, match_id: str) -> StoredMatch | None:
    """Scoring state, source and participant count of a stored match, or None when
    unknown."""
    stmt = (
        select(
            Match.match_id,
            Match.scored_at,
            Match.model_version,
            func.count(MatchParticipant.puuid),
            Match.source,
        )
        .outerjoin(MatchParticipant, MatchParticipant.match_id == Match.match_id)
        .where(Match.match_id == match_id)
        .group_by(Match.match_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return StoredMatch(
        match_id=row[0],
        scored_at=row[1],
        model_version=row[2],
        participants=int(row[3]),
        source=row[4],
    )


async def promote_crawled_match(session: AsyncSession, match_id: str) -> dict[str, Any] | None:
    """Turn a game the data crawler stored into a roster game (``source = 'roster'``) and
    return its stored payload; None when it is not (or no longer) a crawled game, e.g.
    because another process promoted it first."""
    stmt = (
        update(Match)
        .where(Match.match_id == match_id, Match.source == CRAWL_SOURCE)
        .values(source=ROSTER_SOURCE)
        .returning(Match.raw)
    )
    return await session.scalar(stmt)


async def request_timeline(session: AsyncSession, match_id: str) -> None:
    """Queue a game for the timeline backlog (``timeline_state = 'pending'``) unless it
    already has a timeline state (fetched, queued or given up)."""
    await session.execute(
        update(Match)
        .where(Match.match_id == match_id, Match.timeline_state.is_(None))
        .values(timeline_state="pending")
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


# --- match timelines (the crawler's backlog step) -------------------------------------------


async def pending_timelines(session: AsyncSession, limit: int) -> list[str]:
    """Up to ``limit`` match ids waiting for a timeline: roster games first, then crawled
    ones, newest first within each (both through ``ix_matches_timeline_pending``)."""
    ids: list[str] = []
    for source in ("roster", "crawl"):
        room = limit - len(ids)
        if room <= 0:
            break
        stmt = (
            select(Match.match_id)
            .where(Match.timeline_state == "pending", Match.source == source)
            .order_by(Match.game_start.desc())
            .limit(room)
        )
        ids.extend(await session.scalars(stmt))
    return ids


async def participant_ids(session: AsyncSession, match_id: str) -> dict[str, int]:
    """``{puuid: participant_id}`` of a stored match."""
    stmt = select(MatchParticipant.puuid, MatchParticipant.participant_id).where(
        MatchParticipant.match_id == match_id
    )
    return {row[0]: int(row[1]) for row in (await session.execute(stmt)).all()}


async def store_timeline(
    session: AsyncSession, match_id: str, rows: Sequence[Mapping[str, Any]]
) -> bool:
    """Insert ``match_timeline_players`` rows (ON CONFLICT DO NOTHING) and mark the match's
    timeline "ok". A match the champion rollup already counted without its timeline
    (``champ_rollup = 1``) moves to 3 in the same statement, so the rollup worker adds the
    timeline kinds exactly once. Returns False (nothing written) when the match is no longer
    pending."""
    marked = await session.scalar(
        update(Match)
        .where(Match.match_id == match_id, Match.timeline_state == "pending")
        .values(
            timeline_state="ok",
            champ_rollup=case((Match.champ_rollup == 1, 3), else_=Match.champ_rollup),
        )
        .returning(Match.match_id)
        .execution_options(synchronize_session=False)
    )
    if marked is None:
        return False
    if rows:
        stmt = insert(MatchTimelinePlayer).on_conflict_do_nothing(
            index_elements=[MatchTimelinePlayer.match_id, MatchTimelinePlayer.participant_id]
        )
        await session.execute(stmt, [dict(r) for r in rows])
    return True


async def set_timeline_state(session: AsyncSession, match_id: str, state: str) -> None:
    """Give up on a pending timeline ("missing" or "failed")."""
    await session.execute(
        update(Match)
        .where(Match.match_id == match_id, Match.timeline_state == "pending")
        .values(timeline_state=state)
        .execution_options(synchronize_session=False)
    )


async def timeline_attempt_failed(
    session: AsyncSession, match_id: str, *, max_attempts: int
) -> str | None:
    """Count a failed timeline fetch; the match becomes "failed" at ``max_attempts``.
    Returns the new state (None when the match was not pending)."""
    attempts = Match.timeline_attempts + 1
    return await session.scalar(
        update(Match)
        .where(Match.match_id == match_id, Match.timeline_state == "pending")
        .values(
            timeline_attempts=attempts,
            timeline_state=case((attempts >= max_attempts, "failed"), else_="pending"),
        )
        .returning(Match.timeline_state)
        .execution_options(synchronize_session=False)
    )


async def timeline_state_counts(session: AsyncSession) -> dict[str, int]:
    """``{timeline_state: matches}`` over sampled matches (NULL = not sampled is left out)."""
    stmt = (
        select(Match.timeline_state, func.count())
        .where(Match.timeline_state.is_not(None))
        .group_by(Match.timeline_state)
    )
    return {str(row[0]): int(row[1]) for row in (await session.execute(stmt)).all()}


async def count_pending_timelines(session: AsyncSession) -> int:
    """Matches waiting for a timeline (an index-only count on the partial index)."""
    stmt = select(func.count()).select_from(Match).where(Match.timeline_state == "pending")
    return int(await session.scalar(stmt) or 0)
