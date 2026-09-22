"""Dependencies shared by ingestion code paths (API process, worker, CLI)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.config import Settings
from hextrack.riot.client import RiotClient

if TYPE_CHECKING:
    from hextrack.hextrack_ai.inference import Scorer
    from hextrack.ingest.ondemand import MissCache, OnDemandGuard


def _guard() -> OnDemandGuard:
    from hextrack.ingest.ondemand import OnDemandGuard

    return OnDemandGuard()


def _miss_cache() -> MissCache:
    from hextrack.ingest.ondemand import MissCache

    return MissCache()


@dataclass(slots=True)
class IngestContext:
    """Everything ingestion needs. ``scorer`` is None when no AI model is loaded.

    ``ondemand_guard`` and ``lookup_misses`` are per-process throttles for the public
    lookup endpoints (see :mod:`hextrack.ingest.ondemand`); the worker and the CLI simply
    never use them.
    """

    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    riot: RiotClient
    scorer: Scorer | None = None
    ondemand_guard: OnDemandGuard = field(default_factory=_guard)
    lookup_misses: MissCache = field(default_factory=_miss_cache)
