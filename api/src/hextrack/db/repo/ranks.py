"""Rank snapshot reads and inserts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import RankSnapshot


async def latest_snapshot(
    session: AsyncSession, puuid: str, queue_type: str
) -> RankSnapshot | None:
    """Newest snapshot (change or heartbeat) for one queue."""
    stmt = (
        select(RankSnapshot)
        .where(RankSnapshot.puuid == puuid, RankSnapshot.queue_type == queue_type)
        .order_by(RankSnapshot.taken_at.desc(), RankSnapshot.id.desc())
        .limit(1)
    )
    result = await session.scalars(stmt)
    return result.first()


async def latest_snapshots(session: AsyncSession, puuid: str) -> dict[str, RankSnapshot]:
    """``{queue_type: newest snapshot}`` for every queue the player has history in."""
    stmt = (
        select(RankSnapshot)
        .where(RankSnapshot.puuid == puuid)
        .distinct(RankSnapshot.queue_type)
        .order_by(RankSnapshot.queue_type, RankSnapshot.taken_at.desc(), RankSnapshot.id.desc())
    )
    result = await session.scalars(stmt)
    return {snap.queue_type: snap for snap in result}


async def insert_snapshot(
    session: AsyncSession,
    *,
    puuid: str,
    queue_type: str,
    tier: str,
    rank: str | None,
    lp: int,
    wins: int,
    losses: int,
    rank_value: int,
    taken_at: datetime,
    is_heartbeat: bool,
) -> RankSnapshot:
    """Add one snapshot row (flushed so its id is assigned)."""
    snapshot = RankSnapshot(
        puuid=puuid,
        queue_type=queue_type,
        tier=tier,
        rank=rank,
        lp=lp,
        wins=wins,
        losses=losses,
        rank_value=rank_value,
        taken_at=taken_at,
        is_heartbeat=is_heartbeat,
    )
    session.add(snapshot)
    await session.flush([snapshot])
    return snapshot
