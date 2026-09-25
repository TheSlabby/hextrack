"""Stacks: games where several roster players were on the same team (a full squad is 5).

A stack is a ``(match_id, team_id)`` with at least ``size`` tracked players, in any stored
queue except Arena and customs (``queue="flex"``: Ranked Flex only), remakes excluded.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.api.schemas import StackGamePage, StackQueue, StackSummary, StatsSince
from hextrack.config import Settings
from hextrack.stats.queries import MatchCursor

#: A lineup needs this many games together to be "best lineup".
STACK_LINEUP_MIN_GAMES = 5


async def stack_summary(
    session: AsyncSession,
    settings: Settings,
    *,
    since: StatsSince,
    queue: StackQueue,
    size: int,
    model_version: str | None,
) -> StackSummary:
    """Record, averages, per-player numbers, lineups, awards and highlight games."""
    raise NotImplementedError  # stats/stacks.py: implemented in the next step


async def stack_games(
    session: AsyncSession,
    settings: Settings,
    *,
    since: StatsSince,
    queue: StackQueue,
    size: int,
    model_version: str | None,
    cursor: MatchCursor | None,
    limit: int,
) -> StackGamePage:
    """Stacks newest first, paged by match (both teams of a match stay on one page)."""
    raise NotImplementedError
