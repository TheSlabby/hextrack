"""Score within role: an AI Score's percentile among scored games in the same position.

Population = every ranked (420 / 440), non-remake participant row scored by the active model
with a known position (TOP / JUNGLE / MIDDLE / BOTTOM / UTILITY), across the whole database
(not just the roster). One query loads the sorted scores of each position; lookups are a
``bisect`` into those arrays, so filling a page of match history costs nothing extra.

A percentile answers "better than X% of the population": the share of population scores
strictly below this one, times 100 (0..100, two decimals). UNKNOWN / empty positions, missing
scores and rows scored by another model version get None.

Usage (the module-level :data:`ROLE_PERCENTILES` is the process-wide cache)::

    version = await queries.resolve_model_version(session, scorer, puuid=puuid)
    table = await ROLE_PERCENTILES.ensure_loaded(session, settings, model_version=version)
    table.percentile("UTILITY", 0.83)                      # -> 71.2 (or None)
    table.for_row(row.team_position, row.ai_score, row.model_version)  # None if other version
    ROLE_PERCENTILES.percentile("UTILITY", 0.83)           # same, on the latest loaded table

Refresh rules: a table is reused until it is 15 minutes old, the requested model version
changes, or the request runs on a different database engine than the one that loaded it
(each app instance, e.g. each API test, owns its engine, so tests never see another test's
scores). A table read while stored games still carry another model's score (a model was
just activated and the rescore is running, or was skipped) is *provisional*: it is only
reused for :data:`PROVISIONAL_SECONDS`, so a half-rescored population is not kept for 15
minutes. Loads are serialized by an asyncio lock, so a burst of concurrent requests after a
refresh runs the population query once. Tables are immutable snapshots, safe to share.
"""

from __future__ import annotations

import asyncio
import time
import weakref
from bisect import bisect_left
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.config import Settings
from hextrack.db.models import Match, MatchParticipant
from hextrack.queues import RANKED_QUEUES
from hextrack.stats import queries

#: Positions with a population; anything else (UNKNOWN, "", "Invalid") has no percentile.
KNOWN_POSITIONS: Final[tuple[str, ...]] = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
#: A loaded table is reused for this long (seconds) before the population is re-read.
REFRESH_SECONDS: Final = 15 * 60
#: A provisional table (rows scored by another model version still exist) is reused only
#: this long (seconds).
PROVISIONAL_SECONDS: Final = 60
#: Percentiles are rounded to this many decimals.
PERCENTILE_DECIMALS: Final = 2
#: Model versions kept at once (normally one; two while a new model is being activated).
MAX_TABLES: Final = 4

_RESOLVE: Final[Any] = object()


def percentile_of(sorted_scores: list[float], score: float) -> float | None:
    """Share (0..100) of ``sorted_scores`` strictly below ``score``; None for an empty
    population."""
    if not sorted_scores:
        return None
    below = bisect_left(sorted_scores, float(score))
    return round(100.0 * below / len(sorted_scores), PERCENTILE_DECIMALS)


@dataclass(frozen=True, slots=True)
class RolePercentileTable:
    """Sorted AI Scores (0..1) per position for one model version (an immutable snapshot)."""

    version: str | None
    scores: Mapping[str, list[float]] = field(default_factory=dict)
    loaded_at: float = 0.0
    #: Population rows scored by another model version when the table was read (a rescore
    #: is pending or running); non-zero makes the table provisional.
    pending: int = 0

    @property
    def provisional(self) -> bool:
        return self.pending > 0

    @property
    def size(self) -> int:
        """Population size over every position."""
        return sum(len(values) for values in self.scores.values())

    def percentile(self, position: str | None, score: float | None) -> float | None:
        """Percentile of ``score`` (0..1) among games in ``position``; None when the
        position is not a real one, the score is missing or the position has no games."""
        if score is None or position not in KNOWN_POSITIONS:
            return None
        return percentile_of(self.scores.get(position, []), score)

    def for_row(
        self, position: str | None, score: float | None, model_version: str | None
    ) -> float | None:
        """:meth:`percentile` for a stored row, None unless it was scored by this table's
        model version."""
        if self.version is None or model_version != self.version:
            return None
        return self.percentile(position, score)


#: The table used when nothing has been loaded (every lookup is None).
EMPTY_TABLE: Final = RolePercentileTable(version=None)


def population_query(model_version: str) -> Select:
    """(team_position, scores, pending) for every known position: one row per position.
    ``scores`` are the scores of ``model_version`` (sorted in Python by :func:`load_table`),
    ``pending`` counts the position's rows still scored by another version."""
    mp = MatchParticipant
    active = mp.model_version == model_version
    return (
        select(
            mp.team_position,
            func.array_agg(mp.ai_score).filter(active).label("scores"),
            func.count().filter(mp.model_version.is_distinct_from(model_version)).label("pending"),
        )
        .join(Match, Match.match_id == mp.match_id)
        .where(
            mp.queue_id.in_(sorted(RANKED_QUEUES)),
            queries.not_remake(),
            mp.ai_score.is_not(None),
            mp.team_position.in_(KNOWN_POSITIONS),
        )
        .group_by(mp.team_position)
    )


async def load_table(
    session: AsyncSession, model_version: str | None, *, now: float
) -> RolePercentileTable:
    """Read the population of ``model_version`` (an empty table for None)."""
    if model_version is None:
        return RolePercentileTable(version=None, loaded_at=now)
    rows = (await session.execute(population_query(model_version))).all()
    scores = {
        position: sorted(float(value) for value in (values or ()) if value is not None)
        for position, values, _pending in rows
    }
    pending = sum(int(row_pending or 0) for _position, _values, row_pending in rows)
    return RolePercentileTable(
        version=model_version,
        scores={position: values for position, values in scores.items() if values},
        loaded_at=now,
        pending=pending,
    )


class RolePercentileCache:
    """Process-wide cache of :class:`RolePercentileTable` per model version."""

    def __init__(
        self,
        *,
        refresh_seconds: float = REFRESH_SECONDS,
        provisional_seconds: float = PROVISIONAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.refresh_seconds = refresh_seconds
        self.provisional_seconds = provisional_seconds
        self._clock = clock
        self._tables: dict[str | None, RolePercentileTable] = {}
        self._latest: RolePercentileTable = EMPTY_TABLE
        self._engine: weakref.ref[Any] | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        #: Number of population queries run (for tests and logs).
        self.loads = 0

    # -- public API ---------------------------------------------------------------------------

    @property
    def table(self) -> RolePercentileTable:
        """The most recently used table (EMPTY_TABLE before the first load)."""
        return self._latest

    @property
    def version(self) -> str | None:
        return self._latest.version

    def percentile(self, position: str | None, score: float | None) -> float | None:
        """Lookup on the most recently loaded table; call :meth:`ensure_loaded` first."""
        return self._latest.percentile(position, score)

    def invalidate(self) -> None:
        """Forget every table; the next :meth:`ensure_loaded` re-reads the population."""
        self._tables.clear()
        self._latest = EMPTY_TABLE
        self._engine = None

    async def ensure_loaded(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        model_version: str | None = _RESOLVE,
    ) -> RolePercentileTable:
        """The table for ``model_version``, (re)loading it when missing, older than
        :attr:`refresh_seconds` (:attr:`provisional_seconds` for a provisional table), or
        loaded through another engine.

        ``model_version`` defaults to the ``ai_models`` row marked active; routes that
        resolve the version with the loaded scorer as a fallback
        (:func:`hextrack.stats.queries.resolve_model_version`) should pass it. ``None``
        means "no model": an empty table, no query. ``settings`` is accepted for interface
        symmetry with the other stats builders and is not needed today.
        """
        del settings
        if model_version is _RESOLVE:
            model_version = await queries.active_model_version(session)
        if model_version is None:
            self._latest = EMPTY_TABLE
            return EMPTY_TABLE
        engine = session.bind
        fresh = self._fresh(model_version, engine)
        if fresh is not None:
            self._latest = fresh
            return fresh
        async with self._get_lock():
            fresh = self._fresh(model_version, engine)
            if fresh is None:
                if not self._same_engine(engine):
                    self._tables.clear()
                    self._engine = _weak(engine)
                fresh = await load_table(session, model_version, now=self._clock())
                self.loads += 1
                self._store(fresh)
            self._latest = fresh
            return fresh

    # -- internals ----------------------------------------------------------------------------

    def _same_engine(self, engine: Any) -> bool:
        if self._engine is None:
            return False
        return self._engine() is engine

    def _fresh(self, model_version: str, engine: Any) -> RolePercentileTable | None:
        if not self._same_engine(engine):
            return None
        table = self._tables.get(model_version)
        if table is None:
            return None
        ttl = self.provisional_seconds if table.provisional else self.refresh_seconds
        if self._clock() - table.loaded_at >= ttl:
            return None
        return table

    def _store(self, table: RolePercentileTable) -> None:
        self._tables.pop(table.version, None)
        self._tables[table.version] = table
        while len(self._tables) > MAX_TABLES:
            self._tables.pop(next(iter(self._tables)))

    def _get_lock(self) -> asyncio.Lock:
        """One lock per event loop (pytest runs each test on its own loop)."""
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock


def _weak(engine: Any) -> weakref.ref[Any] | None:
    try:
        return weakref.ref(engine)
    except TypeError:
        return None


#: The process-wide cache every route uses.
ROLE_PERCENTILES: Final = RolePercentileCache()


async def average_role_percentiles(
    session: AsyncSession, rows: Select, *, table: RolePercentileTable
) -> dict[str, float]:
    """puuid -> mean per-game role percentile over ``rows`` (a
    :func:`hextrack.stats.aggregate.stat_rows` select), using only games scored by the
    table's model version with a known position. Players without such games are left out."""
    if table.version is None:
        return {}
    sq = rows.subquery("role_rows")
    stmt = select(sq.c.puuid, sq.c.team_position, sq.c.ai_score).where(
        sq.c.model_version == table.version,
        sq.c.ai_score.is_not(None),
        sq.c.team_position.in_(KNOWN_POSITIONS),
    )
    result = await session.execute(stmt)
    return mean_percentiles(result.all(), table)


def mean_percentiles(
    rows: Iterable[tuple[str, str | None, float | None]], table: RolePercentileTable
) -> dict[str, float]:
    """puuid -> mean percentile of (puuid, position, score) rows (rows without one skipped)."""
    totals: dict[str, list[float]] = {}
    for puuid, position, score in rows:
        value = table.percentile(position, score)
        if value is not None:
            totals.setdefault(puuid, []).append(value)
    return {
        puuid: round(sum(values) / len(values), PERCENTILE_DECIMALS)
        for puuid, values in totals.items()
    }


__all__ = [
    "EMPTY_TABLE",
    "KNOWN_POSITIONS",
    "PROVISIONAL_SECONDS",
    "REFRESH_SECONDS",
    "ROLE_PERCENTILES",
    "RolePercentileCache",
    "RolePercentileTable",
    "average_role_percentiles",
    "load_table",
    "mean_percentiles",
    "percentile_of",
    "population_query",
]
