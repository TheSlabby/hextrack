"""Helpers shared by the ``test_ingest_*`` modules (this module holds no tests).

* :class:`StubScorer`: a deterministic stand-in for ``hextrack_ai.inference.Scorer``.
* :class:`IngestFakeRiot`: :class:`tests.fakes.FakeRiotClient` that can serve corrupt match
  bodies and block calls until released.
* :func:`recent`: a game start that ended well inside ``GAME_EVENT_MAX_AGE``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.config import Settings
from hextrack.db.models import BotEvent, Match, MatchParticipant, RankSnapshot
from hextrack.ingest.context import IngestContext
from hextrack.riot.schemas import SummonerDto
from tests.fakes import FakeRiotClient


class StubScorer:
    """Scores participant ``i`` (in payload order) as ``0.05 + 0.09 * i``."""

    def __init__(self, version: str = "test-model-1", *, fail: bool = False) -> None:
        self.version = version
        self.meta: dict[str, Any] = {}
        self.feature_names = ["kills", "deaths", "assists"]
        self.fail = fail
        self.calls: list[tuple[int, int]] = []

    def score_match(
        self, game_duration_seconds: int, participants: Sequence[Mapping[str, Any]]
    ) -> dict[str, float]:
        self.calls.append((game_duration_seconds, len(participants)))
        if self.fail:
            raise RuntimeError("model exploded")
        return {p["puuid"]: round(0.05 + 0.09 * i, 4) for i, p in enumerate(participants)}


class IngestFakeRiot(FakeRiotClient):
    """FakeRiotClient that can return corrupt bodies from ``match`` and block methods."""

    def __init__(self, settings: Settings | None = None, **kwargs: Any) -> None:
        super().__init__(settings, **kwargs)
        self.corrupt: dict[str, Any] = {}
        self.gates: dict[str, asyncio.Event] = {}
        self.entered: dict[str, asyncio.Event] = {}

    def block(self, method: str) -> asyncio.Event:
        """Make ``method`` wait until the returned event is set."""
        gate = asyncio.Event()
        self.gates[method] = gate
        self.entered[method] = asyncio.Event()
        return gate

    async def _gate(self, method: str) -> None:
        gate = self.gates.get(method)
        if gate is not None:
            self.entered[method].set()
            await gate.wait()

    async def summoner_by_puuid(self, puuid: str) -> SummonerDto:
        await self._gate("summoner_by_puuid")
        return await super().summoner_by_puuid(puuid)

    async def match(self, match_id: str) -> dict[str, Any]:
        await self._gate("match")
        if match_id in self.corrupt:
            self._enter("match", match_id)
            return self.corrupt[match_id]
        return await super().match(match_id)


def recent(hours_ago: float = 1.0) -> datetime:
    """A game start ``hours_ago`` hours before now (30-minute games end inside 6 h)."""
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).replace(microsecond=0)


def make_ctx(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    riot: Any,
    scorer: Any | None = None,
) -> IngestContext:
    return IngestContext(
        settings=settings, session_factory=session_factory, riot=riot, scorer=scorer
    )


async def count(session: AsyncSession, model: type, *where: Any) -> int:
    stmt = select(func.count()).select_from(model)
    for clause in where:
        stmt = stmt.where(clause)
    return int(await session.scalar(stmt) or 0)


async def events_of(session: AsyncSession, kind: str | None = None) -> list[BotEvent]:
    stmt = select(BotEvent).order_by(BotEvent.id)
    if kind is not None:
        stmt = stmt.where(BotEvent.kind == kind)
    return list(await session.scalars(stmt))


async def snapshots_of(
    session: AsyncSession, puuid: str, queue_type: str = "RANKED_SOLO_5x5"
) -> list[RankSnapshot]:
    stmt = (
        select(RankSnapshot)
        .where(RankSnapshot.puuid == puuid, RankSnapshot.queue_type == queue_type)
        .order_by(RankSnapshot.taken_at, RankSnapshot.id)
    )
    return list(await session.scalars(stmt, execution_options={"populate_existing": True}))


async def stored_match_ids(session: AsyncSession) -> set[str]:
    return set(await session.scalars(select(Match.match_id)))


async def participants_of(session: AsyncSession, match_id: str) -> list[MatchParticipant]:
    stmt = (
        select(MatchParticipant)
        .where(MatchParticipant.match_id == match_id)
        .order_by(MatchParticipant.participant_id)
    )
    return list(await session.scalars(stmt, execution_options={"populate_existing": True}))
