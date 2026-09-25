"""Read side of live games: the worker's ``app_state`` snapshot (see ingest/live.py) joined
with the roster, stored ranks and season numbers, champion names from Data Dragon."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.api.schemas import LiveGames
from hextrack.config import Settings
from hextrack.riot.ddragon import DDragon


async def live_games(
    session: AsyncSession,
    settings: Settings,
    ddragon: DDragon,
    *,
    model_version: str | None,
    now: datetime,
) -> LiveGames:
    """Current roster games; empty when the snapshot is stale (worker down)."""
    raise NotImplementedError
