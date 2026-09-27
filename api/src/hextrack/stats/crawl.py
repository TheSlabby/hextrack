"""Read side of the data crawler: its ``app_state`` heartbeat, frontier and stored games.

Used by ``GET /health`` (cheap: heartbeat plus a cached count) and ``hextrack crawl status``
(exact counts, database size, free disk). The heartbeat is written by
``hextrack.ingest.crawler``; every field in it is optional here.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.config import Settings
from hextrack.db.models import AppState, CrawlPlayer, Match
from hextrack.db.repo import matches as matches_repo
from hextrack.ingest.crawler import STATE_KEY
from hextrack.rank import DIVISION_ORDER, TIER_ORDER

logger = logging.getLogger(__name__)

#: The crawler rewrites its heartbeat every few seconds; older than this means it is gone.
CRAWLER_HEARTBEAT_STALE: Final = timedelta(minutes=5)
#: ``matches.source`` of crawled games.
CRAWL_SOURCE: Final = "crawl"


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


@dataclass(frozen=True, slots=True)
class CrawlerHeartbeat:
    """The crawler heartbeat, interpreted (staleness, today's counter)."""

    running: bool
    paused_reason: str | None
    heartbeat_at: datetime | None
    matches_added_today: int | None
    frontier_uncrawled: int | None
    frontier_total: int | None
    last_error: str | None


def interpret_heartbeat(
    state: dict[str, Any] | None, *, now: datetime | None = None
) -> CrawlerHeartbeat:
    """``running`` is true when the heartbeat does not say ``running: false`` and was written
    within :data:`CRAWLER_HEARTBEAT_STALE`. ``matches_added_today`` is 0 when the heartbeat's
    ``day`` is not today (UTC): the crawler resets it on its first write of a new day."""
    if not state:
        return CrawlerHeartbeat(False, None, None, None, None, None, None)
    now = now or datetime.now(UTC)
    heartbeat_at = _parse_dt(state.get("updated_at")) or _parse_dt(state.get("heartbeat_at"))
    fresh = heartbeat_at is not None and now - heartbeat_at <= CRAWLER_HEARTBEAT_STALE
    running = bool(state.get("running", True)) and fresh
    today = _int(state.get("matches_added_today"))
    day = state.get("day")
    if today is not None and isinstance(day, str) and day and day != now.date().isoformat():
        today = 0
    paused = state.get("paused_reason")
    last_error = state.get("last_error")
    return CrawlerHeartbeat(
        running=running,
        paused_reason=str(paused) if paused and running else None,
        heartbeat_at=heartbeat_at,
        matches_added_today=today,
        frontier_uncrawled=_int(state.get("frontier_uncrawled")),
        frontier_total=_int(state.get("frontier_total")),
        last_error=str(last_error) if last_error else None,
    )


async def count_crawled_matches(session: AsyncSession, *, since: datetime | None = None) -> int:
    """Exact number of stored games the crawler added (optionally ingested after ``since``)."""
    stmt = select(func.count()).select_from(Match).where(Match.source == CRAWL_SOURCE)
    if since is not None:
        stmt = stmt.where(Match.ingested_at >= since)
    return int(await session.scalar(stmt) or 0)


class CrawledMatchCount:
    """Process-wide cache of :func:`count_crawled_matches` for ``GET /health``.

    Health is polled by every open tab, and counting a large ``matches`` table is a
    sequential scan, so the count is refreshed at most every ``ttl`` in a background task
    and health serves the last value (stale-while-revalidate). Only the very first call
    waits, briefly, for a value.
    """

    def __init__(self, ttl: timedelta = timedelta(minutes=5), timeout_s: float = 20.0) -> None:
        self.ttl_s = ttl.total_seconds()
        self.timeout_s = timeout_s
        self.value: int | None = None
        self._at: float | None = None
        self._task: asyncio.Task[None] | None = None

    async def get(
        self, factory: async_sessionmaker[AsyncSession], *, wait_s: float = 1.0
    ) -> int | None:
        fresh = self._at is not None and time.monotonic() - self._at < self.ttl_s
        if fresh:
            return self.value
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._refresh(factory))
        if self.value is None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), wait_s)
            except TimeoutError:
                pass
        return self.value

    async def _refresh(self, factory: async_sessionmaker[AsyncSession]) -> None:
        try:
            async with factory() as session:
                ms = int(self.timeout_s * 1000)
                await session.execute(text(f"SET LOCAL statement_timeout = {ms}"))
                self.value = await count_crawled_matches(session)
        except Exception as exc:  # health must never raise; keep the last value
            logger.warning("health: counting crawled matches failed: %s", exc)
        finally:
            self._at = time.monotonic()


# --- `hextrack crawl status` -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrontierRow:
    """Frontier players in one group: all of them, not crawled yet, last crawl failed."""

    label: str
    total: int
    uncrawled: int
    errored: int


@dataclass(slots=True)
class CrawlStatus:
    enabled: bool
    heartbeat: dict[str, Any] | None
    heartbeat_row_updated_at: datetime | None
    interpreted: CrawlerHeartbeat
    by_found_via: list[FrontierRow] = field(default_factory=list)
    by_tier: list[FrontierRow] = field(default_factory=list)
    crawled_total: int = 0
    crawled_24h: int = 0
    matches_total: int = 0
    db_size_bytes: int | None = None
    disk_path: str | None = None
    disk_free_bytes: int | None = None
    disk_total_bytes: int | None = None
    min_free_gb: float = 0.0
    timelines_enabled: bool = True
    #: Sampled games by ``matches.timeline_state`` (pending / ok / missing / failed).
    timelines: dict[str, int] = field(default_factory=dict)


def _tier_sort_key(label: str) -> tuple[int, int, str]:
    """Iron IV first, Challenger last, players found in games after the ladder tiers."""
    tier, _, division = label.partition(" ")
    if tier in TIER_ORDER:
        div = DIVISION_ORDER.index(division) if division in DIVISION_ORDER else 0
        return (TIER_ORDER.index(tier), div, "")
    return (len(TIER_ORDER), 0, label)


async def _frontier(session: AsyncSession, *group_by: Any) -> list[tuple[Any, ...]]:
    stmt = select(
        *group_by,
        func.count(),
        func.count().filter(CrawlPlayer.crawled_at.is_(None)),
        func.count().filter(CrawlPlayer.last_error.is_not(None)),
    ).group_by(*group_by)
    return [tuple(row) for row in (await session.execute(stmt)).all()]


async def _data_directory(session: AsyncSession) -> str | None:
    """Postgres' data directory; only readable by superusers / pg_read_all_settings."""
    try:
        async with session.begin_nested():
            value = await session.scalar(text("SELECT current_setting('data_directory')"))
    except Exception:
        return None
    return str(value) if value else None


def _disk_usage(candidates: list[str | None]) -> tuple[str, int, int] | None:
    for path in candidates:
        if not path:
            continue
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        return path, usage.free, usage.total
    return None


async def crawl_status(
    session: AsyncSession, settings: Settings, *, now: datetime | None = None
) -> CrawlStatus:
    """Everything ``hextrack crawl status`` prints (exact counts; meant for the CLI)."""
    now = now or datetime.now(UTC)
    row = (
        await session.execute(
            select(AppState.value, AppState.updated_at).where(AppState.key == STATE_KEY)
        )
    ).first()
    heartbeat = dict(row[0]) if row is not None and isinstance(row[0], dict) else None
    status = CrawlStatus(
        enabled=settings.crawl,
        heartbeat=heartbeat,
        heartbeat_row_updated_at=row[1] if row is not None else None,
        interpreted=interpret_heartbeat(heartbeat, now=now),
        min_free_gb=settings.crawl_min_free_gb,
        timelines_enabled=settings.timelines,
    )

    for found_via, total, uncrawled, errored in await _frontier(session, CrawlPlayer.found_via):
        status.by_found_via.append(FrontierRow(str(found_via), total, uncrawled, errored))
    status.by_found_via.sort(key=lambda r: r.label)

    tier_label = case(
        (CrawlPlayer.tier.is_(None), "(found in games)"),
        (CrawlPlayer.division.is_(None), CrawlPlayer.tier),
        else_=CrawlPlayer.tier + " " + CrawlPlayer.division,
    )
    for label, total, uncrawled, errored in await _frontier(session, tier_label):
        status.by_tier.append(FrontierRow(str(label), total, uncrawled, errored))
    status.by_tier.sort(key=lambda r: _tier_sort_key(r.label))

    status.crawled_total = await count_crawled_matches(session)
    status.crawled_24h = await count_crawled_matches(session, since=now - timedelta(hours=24))
    status.matches_total = int(await session.scalar(select(func.count()).select_from(Match)) or 0)
    status.timelines = await matches_repo.timeline_state_counts(session)
    status.db_size_bytes = await session.scalar(text("SELECT pg_database_size(current_database())"))

    data_dir = await _data_directory(session)
    usage = _disk_usage([data_dir, "/var/lib/postgresql", "/"])
    if usage is not None:
        status.disk_path, status.disk_free_bytes, status.disk_total_bytes = usage
    return status
