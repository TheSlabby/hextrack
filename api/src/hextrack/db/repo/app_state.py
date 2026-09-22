"""``app_state`` key/value rows (worker and bot heartbeats)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import AppState


async def get_state(session: AsyncSession, key: str) -> dict[str, Any] | None:
    """The JSON value stored under ``key``, or None."""
    value = await session.scalar(select(AppState.value).where(AppState.key == key))
    return dict(value) if value is not None else None


async def set_state(session: AsyncSession, key: str, value: dict[str, Any]) -> None:
    """Replace the value under ``key`` (upsert)."""
    stmt = insert(AppState).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AppState.key],
        set_={"value": stmt.excluded.value, "updated_at": func.now()},
    )
    await session.execute(stmt)


async def merge_state(session: AsyncSession, key: str, patch: dict[str, Any]) -> None:
    """Shallow-merge ``patch`` into the value under ``key`` (JSONB ``||``; upsert)."""
    stmt = insert(AppState).values(key=key, value=patch)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AppState.key],
        set_={"value": AppState.value.op("||")(stmt.excluded.value), "updated_at": func.now()},
    )
    await session.execute(stmt)
