"""Bot outbox (``bot_events``) writes and counts.

Payload validation and the event vocabulary live in :mod:`hextrack.ingest.events`; this
module only touches the table.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import BotEvent


async def insert_event(session: AsyncSession, kind: str, payload: dict[str, Any]) -> BotEvent:
    """Add a pending event (flushed so its id is assigned; not committed)."""
    event = BotEvent(kind=kind, payload=payload, attempts=0)
    session.add(event)
    await session.flush([event])
    return event


async def count_pending(session: AsyncSession, kind: str | None = None) -> int:
    """Unprocessed events, optionally of one kind."""
    stmt = select(func.count()).select_from(BotEvent).where(BotEvent.processed_at.is_(None))
    if kind is not None:
        stmt = stmt.where(BotEvent.kind == kind)
    return int(await session.scalar(stmt) or 0)
