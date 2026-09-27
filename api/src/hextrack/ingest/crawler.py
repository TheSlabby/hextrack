"""Data crawler: keep adding ranked games of players HexTrack doesn't track, for training.

Runs inside the standalone worker next to the roster poller (``poll_forever`` starts it while
it holds the poller lock) and only ever uses Riot budget the poller, live games and the
website leave over. Games are stored like any other (raw JSON, participants) with
``matches.source = "crawl"``, but unscored (they are training data only) and without bot
events.

Frontier (``crawl_players``):

* seeded from league-exp ladder pages, rotating through RANKED_SOLO_5x5 IRON..DIAMOND x IV..I
  plus MASTER / GRANDMASTER / CHALLENGER, one random page at a time (a page past the end
  lowers that slot's page range, a full page far down raises it). A page is fetched when the
  uncrawled backlog is small (:data:`LADDER_BACKLOG_MIN`) and every
  :data:`LADDER_EVERY_STEPS` steps so every rank keeps mixing in;
* grown with the participants of crawled games while it is below ``crawl_frontier_max``.
  Tracked summoners (the poller owns them) and demo puuids are never added.

One step (:meth:`Crawler.step`): first the timeline backlog (below), then maybe a ladder
page, then one player: uncrawled players first (oldest discovered; every
:data:`LADDER_PICK_EVERY` th pick prefers a ladder player so ranks stay mixed), else whoever
was crawled longest ago, at least :data:`RECRAWL_AFTER` back. Their newest
``crawl_matches_per_player`` ranked games since the season start are listed, stored ones
skipped, and the rest fetched and stored one transaction per match. A game with a tracked
player in it is left to the poller (it announces friends' games; the crawler never does).

Timeline backlog (champion build orders, :mod:`hextrack.ingest.timeline`): each step first
fetches up to :data:`TIMELINE_BATCH` timelines of games marked ``timeline_state = 'pending'``
(roster games first, then sampled crawled games, newest first) through the same budget gate
(regional routing, like match fetches), so timelines come before new crawl games but never
before the poll. A stored timeline writes its rows and ``timeline_state = 'ok'`` in one
transaction (moving ``champ_rollup`` 1 -> 3 for the rollup worker). A 404 marks the game
"missing", a timeline whose players differ from the stored match "failed"; other errors count
an attempt and give up ("failed") at :data:`~hextrack.ingest.timeline.TIMELINE_MAX_ATTEMPTS`.
Rate limits and key errors are not attempts: they pause the crawler like any other request.

Budget gate (:class:`CrawlBudget`): before every request the crawler waits until

* no poll tick / live refresh is running (``poll_active``), and
* a request on that routing value would go out without queuing in the limiter, and
* the free slots in the longest application window (2 min) exceed the *reserve*: the most
  requests one poll tick + live refresh used on that routing value over the last
  :data:`RESERVE_TICKS` ticks (the poller measures it) plus :data:`RESERVE_MARGIN`, or
  :data:`DEFAULT_RESERVE` before the first measurement.

So when the next tick starts it finds at least what it needed last time free, and never waits
on the limiter because of the crawler. A 429 backs off, a missing / rejected key pauses
:data:`AUTH_PAUSE_SECONDS`, and the crawl pauses while the disk has less than
``crawl_min_free_gb`` free.

Heartbeat (``app_state["crawler"]``, written every :data:`HEARTBEAT_SECONDS`)::

    {"running": bool, "paused_reason": None | "disk" | "budget_starved" | "riot_forbidden"
     | "error", "updated_at": ISO, "started_at": ISO, "matches_added": int (this run),
     "matches_added_today": int, "day": "YYYY-MM-DD" (UTC), "players_crawled": int (this run),
     "frontier_uncrawled": int, "frontier_total": int, "last_error": str | None,
     "reserve": {"na1": int, "americas": int}, "ladder_pages": {"GOLD II": [max_page, end_known]},
     "timelines_fetched": int (this run), "timelines_fetched_today": int,
     "timelines_pending": int | None}
"""

from __future__ import annotations

import asyncio
import logging
import random
import shutil
import time
from collections import deque
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert

from hextrack.db.engine import session_scope
from hextrack.db.models import CrawlPlayer, Summoner
from hextrack.db.repo import app_state as app_state_repo
from hextrack.db.repo import matches as matches_repo
from hextrack.demo.names import DEMO_PUUID_PREFIX
from hextrack.ingest.context import IngestContext
from hextrack.ingest.mapping import InvalidMatchPayload
from hextrack.ingest.service import MATCH_TYPE, ingest_match_json
from hextrack.ingest.timeline import (
    STATE_FAILED,
    STATE_MISSING,
    TIMELINE_MAX_ATTEMPTS,
    InvalidTimeline,
    TimelineMismatch,
    extract_timeline,
)
from hextrack.rank import APEX_TIERS, DIVISION_ORDER, TIER_ORDER, RANKED_SOLO_5x5
from hextrack.riot.client import METHOD_ROUTING, Routing
from hextrack.riot.errors import (
    RiotBadResponse,
    RiotError,
    RiotForbidden,
    RiotKeyMissing,
    RiotNotFound,
    RiotRateLimited,
)
from hextrack.riot.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

#: app_state key for the crawler's heartbeat (counters, last error, paused reason).
STATE_KEY = "crawler"

# --- budget ---
#: Reserve before the poller measured a tick (of the worker's 80 per 2 min by default).
DEFAULT_RESERVE: Final = 60
#: Added to the measured tick usage.
RESERVE_MARGIN: Final = 10
#: Ticks whose usage the reserve covers (the largest of them counts).
RESERVE_TICKS: Final = 5
#: The reserve never exceeds this share of the long window, so a mismeasured tick (e.g. one
#: that included a restarted process's calls, which Riot reports back) can't starve the
#: crawler for good.
RESERVE_MAX_SHARE: Final = 0.75
#: How often the gate re-checks the budget while it waits.
GATE_POLL_SECONDS: Final = 1.0
#: Waiting this long for budget outside poll ticks reports ``paused_reason="budget_starved"``.
STARVED_AFTER_SECONDS: Final = 300.0
#: Longest pause after a 429.
MAX_RATE_LIMIT_PAUSE_SECONDS: Final = 60.0

# --- pauses ---
#: Pause after a missing / rejected Riot key.
AUTH_PAUSE_SECONDS: Final = 600.0
#: Disk re-check interval while paused for space.
DISK_CHECK_SECONDS: Final = 600.0
#: Pause after an unexpected error.
ERROR_PAUSE_SECONDS: Final = 60.0
#: Pause when there is nobody to crawl.
IDLE_PAUSE_SECONDS: Final = 60.0
#: Path whose file system the disk guard checks.
DISK_PATH: Final = "/"
_GIB: Final = 1024**3

# --- frontier ---
#: Fetch a ladder page when fewer players than this are waiting for their first crawl.
LADDER_BACKLOG_MIN: Final = 200
#: ... and also every this many steps, so every rank keeps mixing in.
LADDER_EVERY_STEPS: Final = 100
#: Every this many picks prefer an uncrawled ladder player over the oldest one.
LADDER_PICK_EVERY: Final = 3
#: A player's games are listed again once their last crawl is this old.
RECRAWL_AFTER: Final = timedelta(days=7)
#: First guess for how many pages a ladder slot has, and the most it may grow to.
LADDER_DEFAULT_MAX_PAGE: Final = 50
LADDER_MAX_PAGE_CEILING: Final = 2000
LADDER_QUEUE: Final = RANKED_SOLO_5x5
#: (tier, division) ladder slots, lowest first; apex tiers are one "I" division.
LADDER_SLOTS: Final[tuple[tuple[str, str], ...]] = tuple(
    (tier, division)
    for tier in TIER_ORDER
    for division in (("I",) if tier in APEX_TIERS else DIVISION_ORDER)
)

# --- timelines ---
#: Most pending timelines fetched per step (before the step's player crawl). A player crawl
#: fetches up to ``crawl_matches_per_player`` (20) games, so a backlog gets about half the
#: spare budget; in steady state (1 in 3 crawled games sampled) it stays near empty.
TIMELINE_BATCH: Final = 20
#: Demo games have no Riot timeline.
_DEMO_MATCH_PREFIX: Final = "DEMO_"

# --- reporting ---
HEARTBEAT_SECONDS: Final = 60.0
LOG_EVERY_SECONDS: Final = 300.0
#: Error text kept in the heartbeat / crawl_players.last_error.
MAX_ERROR_CHARS: Final = 300

PausedReason = str  # "disk" | "budget_starved" | "riot_forbidden" | "error"
Sleep = Callable[[float], Awaitable[bool]]
Clock = Callable[[], float]

_FATAL_RIOT_ERRORS: Final = (RiotForbidden, RiotKeyMissing)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _short(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    return text[:MAX_ERROR_CHARS]


class _Stopped(Exception):
    """Internal: ``stop`` was set while the crawler waited."""


# --- budget ----------------------------------------------------------------------------------


def _limiter(riot: Any, routing: Routing) -> RateLimiter | None:
    """The real client's limiter for ``routing`` (None for test doubles)."""
    getter = getattr(riot, "rate_limiter", None)
    if getter is None:
        return None
    limiter = getter(routing)
    return limiter if isinstance(limiter, RateLimiter) else None


class _AppWindow:
    """The *longest* application window of one routing value's limiter (the per-2-min one):
    ``RateLimiter.app_headroom`` reports the tightest window, the one-second one on a Riot
    key, which can't be compared with a per-2-min reserve."""

    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    def now(self) -> float:
        return self._limiter.now()

    def free(self) -> int:
        """Free slots in the longest window right now, minus requests already queued."""
        return self._limiter.long_window_headroom()

    def limit(self) -> int | None:
        """The longest window's request limit (None without application limits)."""
        limits = self._limiter.app_limits
        return max(limits, key=lambda lim: lim.window_seconds).max_requests if limits else None

    def sent_since(self, since: float) -> int:
        """Requests recorded after ``since`` that are still inside the longest window."""
        return self._limiter.long_window_sent_since(since)


class CrawlBudget:
    """What the crawler may spend: shared by the poller (which reports each tick's usage
    through :meth:`tick_started` / :meth:`tick_finished`) and the crawler's gate.

    ``reserve(routing)`` = the largest per-tick usage of the last :data:`RESERVE_TICKS` ticks
    (measured as requests sent into the longest window since the tick started, peak while it
    ran) + :data:`RESERVE_MARGIN`; :data:`DEFAULT_RESERVE` before the first measurement.
    Clients without a real limiter (test doubles) fall back to ``riot.app_headroom`` and
    measure nothing; tests feed samples with :meth:`record`.
    """

    def __init__(
        self,
        riot: Any,
        *,
        default_reserve: int = DEFAULT_RESERVE,
        margin: int = RESERVE_MARGIN,
        ticks: int = RESERVE_TICKS,
    ) -> None:
        self._riot = riot
        self.default_reserve = default_reserve
        self.margin = margin
        self._samples: dict[Routing, deque[int]] = {
            "platform": deque(maxlen=ticks),
            "regional": deque(maxlen=ticks),
        }
        self._windows: dict[Routing, _AppWindow] = {}
        for routing in ("platform", "regional"):
            limiter = _limiter(riot, routing)
            if limiter is not None:
                self._windows[routing] = _AppWindow(limiter)
        self._tick_start: dict[Routing, float] = {}
        self._tick_peak: dict[Routing, int] = {}
        #: The first tick after start-up also counts the previous process's recent calls
        #: (Riot's usage headers resync them), so it isn't recorded.
        self._skip_next_tick = True

    # --- measuring (poller side) -------------------------------------------------------------
    def tick_started(self) -> None:
        """A poll tick (and the live refresh after it) begins."""
        self._tick_start = {routing: window.now() for routing, window in self._windows.items()}
        self._tick_peak = dict.fromkeys(self._windows, 0)

    def observe(self) -> None:
        """Sample the running tick's usage (the crawler calls this while it waits)."""
        for routing, since in self._tick_start.items():
            used = self._windows[routing].sent_since(since)
            if used > self._tick_peak.get(routing, 0):
                self._tick_peak[routing] = used

    def tick_finished(self) -> None:
        """The tick is over: record what it used on each routing value."""
        if not self._tick_start:
            return
        self.observe()
        if self._skip_next_tick:
            self._skip_next_tick = False
        else:
            for routing, peak in self._tick_peak.items():
                self._samples[routing].append(peak)
        self._tick_start = {}
        self._tick_peak = {}

    def record(self, routing: Routing, used: int) -> None:
        """Record one tick's usage directly (tests, or a caller that counts itself)."""
        self._samples[routing].append(max(int(used), 0))

    # --- gate (crawler side) -----------------------------------------------------------------
    def reserve(self, routing: Routing) -> int:
        samples = self._samples[routing]
        wanted = max(samples) + self.margin if samples else self.default_reserve
        window = self._windows.get(routing)
        limit = window.limit() if window is not None else None
        if limit is None:
            return wanted
        return min(wanted, int(limit * RESERVE_MAX_SHARE))

    def headroom(self, method: str) -> int:
        """Free app-limit slots on ``method``'s routing value over the longest window."""
        window = self._windows.get(METHOD_ROUTING[method])
        if window is not None:
            return window.free()
        return int(self._riot.app_headroom(method))

    def available(self, method: str) -> bool:
        """True when a request for ``method`` goes out right now without queuing and still
        leaves more than the reserve free for the poller."""
        if self._riot.limiter_wait_estimate(method) > 0.0:
            return False
        return self.headroom(method) > self.reserve(METHOD_ROUTING[method])


# --- reports ---------------------------------------------------------------------------------


@dataclass(slots=True)
class CrawlReport:
    """What one :meth:`Crawler.step` did."""

    #: The player crawled (None: nobody to crawl).
    puuid: str | None = None
    #: Ranked ids Riot listed for them.
    listed: int = 0
    #: Games stored.
    added: int = 0
    #: Listed games not stored: already there, a tracked player's, 404 / invalid, or failed.
    skipped: int = 0
    #: Players added to the frontier (ladder page + participants).
    frontier_added: int = 0
    #: "GOLD II p17" when a ladder page was fetched.
    ladder: str | None = None
    #: Pending timelines tried this step, and how many of them were stored.
    timelines_tried: int = 0
    timelines_stored: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Counts:
    total: int = 0
    uncrawled: int = 0


# --- crawler ---------------------------------------------------------------------------------


async def _sleep_until_stopped(stop: asyncio.Event, seconds: float) -> bool:
    """Sleep ``seconds`` or until ``stop`` is set; True when stopped."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(seconds, 0.0))
    except TimeoutError:
        return False
    return True


def _free_gib(path: str) -> float:
    return shutil.disk_usage(path).free / _GIB


def _participant_puuids(raw: Mapping[str, Any]) -> list[str]:
    metadata = raw.get("metadata")
    values = metadata.get("participants") if isinstance(metadata, Mapping) else None
    if not isinstance(values, list):
        return []
    return [p for p in values if isinstance(p, str) and p]


def _payload_match_id(raw: object) -> str | None:
    if not isinstance(raw, Mapping):
        return None
    metadata = raw.get("metadata")
    value = metadata.get("matchId") if isinstance(metadata, Mapping) else None
    return value if isinstance(value, str) else None


def _slot_key(tier: str, division: str) -> str:
    return tier if tier in APEX_TIERS else f"{tier} {division}"


class Crawler:
    """The crawl loop and its state. :func:`run_crawler` is the entry point; tests drive
    :meth:`step` directly. ``sleep(seconds) -> stopped`` and ``clock`` are injectable."""

    def __init__(
        self,
        ctx: IngestContext,
        stop: asyncio.Event,
        poll_active: asyncio.Event,
        *,
        budget: CrawlBudget | None = None,
        sleep: Sleep | None = None,
        clock: Clock = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.ctx = ctx
        self.stop = stop
        self.poll_active = poll_active
        self.budget = budget if budget is not None else CrawlBudget(ctx.riot)
        self._sleep: Sleep = sleep or (lambda seconds: _sleep_until_stopped(stop, seconds))
        self._clock = clock
        self._rng = rng or random.Random()

        self.started_at = _utcnow()
        self.paused_reason: PausedReason | None = None
        self.last_error: str | None = None
        self.matches_added = 0
        self.matches_added_today = 0
        self.day = self.started_at.date().isoformat()
        self.players_crawled = 0
        self.timelines_fetched = 0
        self.timelines_fetched_today = 0
        #: Timelines still pending after the last backlog query (None: not counted yet).
        self.timelines_pending: int | None = None
        self.counts = _Counts()
        self._steps = 0
        self._picks = 0
        self._slot = self._rng.randrange(len(LADDER_SLOTS))
        #: slot key -> [max page, end known]
        self.ladder_pages: dict[str, list[Any]] = {}
        self._last_heartbeat = -float("inf")
        self._last_log = clock()
        self._logged_added = 0

    # --- entry ----------------------------------------------------------------------------
    async def run(self) -> None:
        """Crawl until ``stop`` is set. Never raises (except cancellation)."""
        await self._restore()
        logger.info("crawler started")
        try:
            while not self.stop.is_set():
                if await self._disk_low():
                    continue
                try:
                    report = await self.step()
                except _Stopped:
                    break
                except _FATAL_RIOT_ERRORS as exc:
                    logger.warning(
                        "crawl: Riot key missing or rejected; pausing %.0fs", AUTH_PAUSE_SECONDS
                    )
                    await self._pause_for("riot_forbidden", exc, AUTH_PAUSE_SECONDS)
                    continue
                except RiotRateLimited as exc:
                    seconds = min(max(exc.retry_after, 1.0), MAX_RATE_LIMIT_PAUSE_SECONDS)
                    logger.info("crawl: Riot rate limit; pausing %.0fs", seconds)
                    self.last_error = _short(exc)
                    await self._pause(seconds)
                    continue
                except Exception as exc:
                    logger.exception("crawl step failed")
                    await self._pause_for("error", exc, ERROR_PAUSE_SECONDS)
                    continue
                if self.paused_reason in ("riot_forbidden", "error"):
                    self.paused_reason = None
                await self._housekeeping()
                if report.puuid is None and not report.timelines_tried:
                    await self._pause(IDLE_PAUSE_SECONDS)
        finally:
            await self.write_heartbeat(running=False)
            logger.info("crawler stopped")

    async def step(self) -> CrawlReport:
        """Fetch pending timelines, maybe a ladder page, then crawl one player."""
        report = CrawlReport()
        if self.ctx.settings.timelines:
            await self._timelines(report)
        self.counts = await self._frontier_counts()
        tracked = await self._tracked()
        if self.counts.uncrawled < LADDER_BACKLOG_MIN or self._steps % LADDER_EVERY_STEPS == 0:
            await self._ladder_page(report, tracked)
        self._steps += 1
        puuid = await self._pick()
        if puuid is None:
            return report
        report.puuid = puuid
        await self._crawl_player(puuid, tracked, report)
        self.players_crawled += 1
        return report

    # --- budget gate ----------------------------------------------------------------------
    async def _gate(self, method: str) -> None:
        """Wait until a ``method`` request fits in the budget the poller leaves over."""
        waiting_since: float | None = None
        while True:
            if self.stop.is_set():
                raise _Stopped
            if self.poll_active.is_set():
                # A poll tick is running: it gets everything; measure what it uses.
                waiting_since = None
                self.budget.observe()
            elif self.budget.available(method):
                if self.paused_reason == "budget_starved":
                    self.paused_reason = None
                return
            else:
                now = self._clock()
                waiting_since = now if waiting_since is None else waiting_since
                if now - waiting_since >= STARVED_AFTER_SECONDS:
                    self.paused_reason = "budget_starved"
            await self._housekeeping()
            if await self._sleep(GATE_POLL_SECONDS):
                raise _Stopped

    # --- disk -----------------------------------------------------------------------------
    async def _disk_low(self) -> bool:
        """When free space is below ``crawl_min_free_gb``, pause (re-checking every
        :data:`DISK_CHECK_SECONDS`) and return True."""
        minimum = self.ctx.settings.crawl_min_free_gb
        try:
            free = _free_gib(DISK_PATH)
        except OSError as exc:
            logger.warning("crawl: disk usage unavailable (%s)", exc)
            return False
        if free >= minimum:
            if self.paused_reason == "disk":
                logger.info("crawl: %.1f GB free again; resuming", free)
                self.paused_reason = None
            return False
        if self.paused_reason != "disk":
            logger.warning("crawl: only %.1f GB free (minimum %.0f GB); pausing", free, minimum)
        self.paused_reason = "disk"
        self.last_error = f"low disk space: {free:.1f} GB free"
        await self.write_heartbeat()
        await self._pause(DISK_CHECK_SECONDS)
        return True

    # --- frontier -------------------------------------------------------------------------
    async def _frontier_counts(self) -> _Counts:
        stmt = select(
            func.count(),
            func.count().filter(CrawlPlayer.crawled_at.is_(None)),
        ).select_from(CrawlPlayer)
        async with self.ctx.session_factory() as session:
            row = (await session.execute(stmt)).one()
        return _Counts(total=int(row[0]), uncrawled=int(row[1]))

    async def _tracked(self) -> set[str]:
        async with self.ctx.session_factory() as session:
            return set(await session.scalars(select(Summoner.puuid).where(Summoner.is_tracked)))

    async def _add_players(
        self,
        rows: list[dict[str, Any]],
        tracked: Collection[str],
        *,
        limit: int | None = None,
    ) -> int:
        """Insert new frontier rows (ON CONFLICT DO NOTHING); tracked and demo puuids are
        dropped. Returns how many were added."""
        seen: set[str] = set()
        clean: list[dict[str, Any]] = []
        for row in rows:
            puuid = row["puuid"]
            if puuid in seen or puuid in tracked or puuid.startswith(DEMO_PUUID_PREFIX):
                continue
            seen.add(puuid)
            clean.append(row)
        if limit is not None:
            clean = clean[: max(limit, 0)]
        if not clean:
            return 0
        stmt = (
            insert(CrawlPlayer)
            .values(clean)
            .on_conflict_do_nothing(index_elements=[CrawlPlayer.puuid])
            .returning(CrawlPlayer.puuid)
        )
        async with session_scope(self.ctx.session_factory) as session:
            added = len(list(await session.scalars(stmt)))
        self.counts.total += added
        self.counts.uncrawled += added
        return added

    async def _ladder_page(self, report: CrawlReport, tracked: Collection[str]) -> None:
        """Fetch one random page of the next ladder slot and add its players."""
        tier, division = LADDER_SLOTS[self._slot % len(LADDER_SLOTS)]
        self._slot += 1
        key = _slot_key(tier, division)
        max_page, end_known = self.ladder_pages.get(key, [LADDER_DEFAULT_MAX_PAGE, False])
        page = self._rng.randint(1, max(int(max_page), 1))
        report.ladder = f"{key} p{page}"
        await self._gate("league_exp_entries")
        try:
            entries = await self.ctx.riot.league_exp_entries(
                LADDER_QUEUE, tier, division, page=page
            )
        except (*_FATAL_RIOT_ERRORS, RiotRateLimited):
            raise
        except RiotError as exc:
            logger.warning("crawl: ladder %s page %d failed: %s", key, page, exc)
            report.errors.append(f"ladder {key} p{page}: {_short(exc)}")
            return
        if not entries:
            # Past the end: stay below this page from now on.
            self.ladder_pages[key] = [max(page - 1, 1), True]
            return
        if not end_known and page * 2 > max_page:
            self.ladder_pages[key] = [min(int(max_page) * 2, LADDER_MAX_PAGE_CEILING), False]
        stored_division = None if tier in APEX_TIERS else division
        rows = [
            {
                "puuid": entry.puuid,
                "found_via": "ladder",
                "tier": tier,
                "division": stored_division,
            }
            for entry in entries
            if entry.puuid
        ]
        report.frontier_added += await self._add_players(rows, tracked)

    async def _pick(self) -> str | None:
        """The next player: uncrawled first (oldest discovered, every
        :data:`LADDER_PICK_EVERY` th pick a ladder player), else the stalest re-crawl."""
        self._picks += 1
        not_tracked = ~exists(
            select(Summoner.puuid).where(Summoner.is_tracked, Summoner.puuid == CrawlPlayer.puuid)
        )
        uncrawled = (
            select(CrawlPlayer.puuid)
            .where(CrawlPlayer.crawled_at.is_(None), not_tracked)
            .order_by(CrawlPlayer.discovered_at, CrawlPlayer.puuid)
            .limit(1)
        )
        queries = [uncrawled]
        if self._picks % LADDER_PICK_EVERY == 0:
            queries.insert(0, uncrawled.where(CrawlPlayer.found_via == "ladder"))
        queries.append(
            select(CrawlPlayer.puuid)
            .where(CrawlPlayer.crawled_at < _utcnow() - RECRAWL_AFTER, not_tracked)
            .order_by(CrawlPlayer.crawled_at, CrawlPlayer.puuid)
            .limit(1)
        )
        async with self.ctx.session_factory() as session:
            for query in queries:
                puuid = await session.scalar(query)
                if puuid is not None:
                    return str(puuid)
        return None

    # --- one player -----------------------------------------------------------------------
    async def _crawl_player(self, puuid: str, tracked: set[str], report: CrawlReport) -> None:
        """List ``puuid``'s newest ranked games and store the new ones. A Riot error on the
        listing records ``last_error`` and moves on; a missing key or rate limit leaves the
        player uncrawled (picked again later) and propagates."""
        settings = self.ctx.settings
        riot = self.ctx.riot
        finished = False
        error: str | None = None
        participants: list[str] = []
        try:
            await self._gate("match_ids_by_puuid")
            try:
                ids = await riot.match_ids_by_puuid(
                    puuid,
                    start=0,
                    count=settings.crawl_matches_per_player,
                    type_=MATCH_TYPE,
                    start_time=settings.season_start,
                )
            except (*_FATAL_RIOT_ERRORS, RiotRateLimited):
                raise
            except RiotError as exc:
                error = _short(exc)
                report.errors.append(f"{puuid}: {error}")
                logger.info("crawl: listing %s failed: %s", puuid, exc)
                finished = True
                return
            ids = list(dict.fromkeys(ids))
            report.listed = len(ids)
            async with self.ctx.session_factory() as session:
                existing = await matches_repo.existing_match_ids(session, ids)
            report.skipped += len(existing)
            for match_id in ids:
                if match_id in existing:
                    continue
                players = await self._crawl_match(match_id, tracked, report)
                participants.extend(p for p in players if p != puuid)
            finished = True
        finally:
            await self._finish_player(puuid, report.added, error, crawled=finished)
            if participants:
                room = self.ctx.settings.crawl_frontier_max - self.counts.total
                if room > 0:
                    rows = [
                        {"puuid": p, "found_via": "match", "tier": None, "division": None}
                        for p in participants
                    ]
                    report.frontier_added += await self._add_players(rows, tracked, limit=room)

    async def _crawl_match(
        self, match_id: str, tracked: Collection[str], report: CrawlReport
    ) -> list[str]:
        """Fetch and store one game; returns its participants when it was stored."""
        await self._gate("match")
        try:
            raw = await self.ctx.riot.match(match_id)
        except (*_FATAL_RIOT_ERRORS, RiotRateLimited):
            raise
        except (RiotNotFound, RiotBadResponse) as exc:
            logger.info("crawl: match %s skipped: %s", match_id, exc)
            report.skipped += 1
            return []
        except RiotError as exc:
            logger.warning("crawl: match %s failed: %s", match_id, exc)
            report.errors.append(f"{match_id}: {_short(exc)}")
            report.skipped += 1
            return []
        if _payload_match_id(raw) != match_id:
            logger.warning("crawl: match %s: payload is for another match; skipped", match_id)
            report.skipped += 1
            return []
        players = _participant_puuids(raw)
        if any(p in tracked for p in players):
            # The poller stores (and announces) the roster's games.
            report.skipped += 1
            return []
        try:
            async with session_scope(self.ctx.session_factory) as session:
                # Training data only: stored unscored, so model activation never has to
                # rescore the crawl.
                result = await ingest_match_json(
                    replace(self.ctx, scorer=None),
                    session,
                    raw,
                    enqueue_events=False,
                    source="crawl",
                )
        except InvalidMatchPayload as exc:
            logger.info("crawl: match %s: invalid payload (%s); skipped", match_id, exc)
            report.skipped += 1
            return []
        except Exception as exc:
            logger.exception("crawl: unexpected error storing %s", match_id)
            report.errors.append(f"{match_id}: {type(exc).__name__}: {_short(exc)}")
            report.skipped += 1
            return []
        if not result.created:
            report.skipped += 1
            return []
        report.added += 1
        self._count_added(1)
        return players

    async def _finish_player(
        self, puuid: str, added: int, error: str | None, *, crawled: bool
    ) -> None:
        values: dict[str, Any] = {"matches_added": CrawlPlayer.matches_added + added}
        if crawled:
            values["crawled_at"] = _utcnow()
            values["last_error"] = error
        try:
            async with session_scope(self.ctx.session_factory) as session:
                await session.execute(
                    update(CrawlPlayer).where(CrawlPlayer.puuid == puuid).values(**values)
                )
        except Exception:
            logger.exception("crawl: could not update frontier row %s", puuid)
        if crawled:
            self.counts.uncrawled = max(self.counts.uncrawled - 1, 0)

    def _roll_day(self) -> None:
        """Reset today's counters on the first use of a new UTC day."""
        today = _utcnow().date().isoformat()
        if today != self.day:
            self.day, self.matches_added_today, self.timelines_fetched_today = today, 0, 0

    def _count_added(self, n: int) -> None:
        self._roll_day()
        self.matches_added += n
        self.matches_added_today += n

    # --- timeline backlog -----------------------------------------------------------------
    async def _timelines(self, report: CrawlReport) -> None:
        """Fetch up to :data:`TIMELINE_BATCH` pending timelines (roster games first)."""
        async with self.ctx.session_factory() as session:
            batch = await matches_repo.pending_timelines(session, TIMELINE_BATCH)
            self.timelines_pending = (
                len(batch)
                if len(batch) < TIMELINE_BATCH
                else await matches_repo.count_pending_timelines(session)
            )
        for match_id in batch:
            report.timelines_tried += 1
            if await self._timeline(match_id, report):
                report.timelines_stored += 1
                self._roll_day()
                self.timelines_fetched += 1
                self.timelines_fetched_today += 1
            if self.timelines_pending:
                self.timelines_pending -= 1

    async def _timeline(self, match_id: str, report: CrawlReport) -> bool:
        """Fetch and store one game's timeline; True when stored. Rate limits and key errors
        propagate without counting an attempt (the game stays pending)."""
        if match_id.startswith(_DEMO_MATCH_PREFIX):
            await self._timeline_state(match_id, STATE_MISSING)
            return False
        await self._gate("match_timeline")
        try:
            raw = await self.ctx.riot.match_timeline(match_id)
        except (*_FATAL_RIOT_ERRORS, RiotRateLimited):
            raise
        except RiotNotFound:
            logger.info("crawl: no timeline for %s at Riot", match_id)
            await self._timeline_state(match_id, STATE_MISSING)
            return False
        except RiotError as exc:
            logger.info("crawl: timeline %s failed: %s", match_id, exc)
            report.errors.append(f"timeline {match_id}: {_short(exc)}")
            await self._timeline_attempt(match_id)
            return False
        try:
            async with session_scope(self.ctx.session_factory) as session:
                players = await matches_repo.participant_ids(session, match_id)
                rows = extract_timeline(raw, players, match_id=match_id)
                return await matches_repo.store_timeline(session, match_id, rows)
        except TimelineMismatch as exc:
            logger.warning("crawl: timeline %s: %s; giving up", match_id, exc)
            report.errors.append(f"timeline {match_id}: {_short(exc)}")
            await self._timeline_state(match_id, STATE_FAILED)
        except InvalidTimeline as exc:
            logger.warning("crawl: timeline %s: invalid payload (%s)", match_id, exc)
            report.errors.append(f"timeline {match_id}: {_short(exc)}")
            await self._timeline_attempt(match_id)
        except Exception as exc:
            logger.exception("crawl: unexpected error storing the timeline of %s", match_id)
            report.errors.append(f"timeline {match_id}: {type(exc).__name__}: {_short(exc)}")
            await self._timeline_attempt(match_id)
        return False

    async def _timeline_state(self, match_id: str, state: str) -> None:
        try:
            async with session_scope(self.ctx.session_factory) as session:
                await matches_repo.set_timeline_state(session, match_id, state)
        except Exception:
            logger.exception("crawl: could not mark the timeline of %s %s", match_id, state)

    async def _timeline_attempt(self, match_id: str) -> None:
        try:
            async with session_scope(self.ctx.session_factory) as session:
                state = await matches_repo.timeline_attempt_failed(
                    session, match_id, max_attempts=TIMELINE_MAX_ATTEMPTS
                )
        except Exception:
            logger.exception("crawl: could not count a timeline attempt for %s", match_id)
            return
        if state == STATE_FAILED:
            logger.warning(
                "crawl: timeline %s failed %d times; giving up", match_id, TIMELINE_MAX_ATTEMPTS
            )

    # --- pauses, heartbeat, log -----------------------------------------------------------
    async def _pause(self, seconds: float) -> None:
        """Sleep ``seconds`` (in heartbeat-sized chunks); returns early on stop."""
        remaining = seconds
        while remaining > 0 and not self.stop.is_set():
            chunk = min(remaining, HEARTBEAT_SECONDS)
            if await self._sleep(chunk):
                return
            remaining -= chunk
            await self._housekeeping()

    async def _pause_for(self, reason: PausedReason, exc: BaseException, seconds: float) -> None:
        self.paused_reason = reason
        self.last_error = _short(exc)
        await self.write_heartbeat()
        await self._pause(seconds)

    async def _housekeeping(self) -> None:
        now = self._clock()
        if now - self._last_heartbeat >= HEARTBEAT_SECONDS:
            await self.write_heartbeat()
        if now - self._last_log >= LOG_EVERY_SECONDS:
            self._last_log = now
            reserve = self.reserve_by_value()
            logger.info(
                "crawl: +%d games (%d today), %d timelines today (%s pending), "
                "frontier %d/%d, reserve %s",
                self.matches_added - self._logged_added,
                self.matches_added_today,
                self.timelines_fetched_today,
                "?" if self.timelines_pending is None else self.timelines_pending,
                self.counts.uncrawled,
                self.counts.total,
                " ".join(f"{name}={value}" for name, value in reserve.items()),
            )
            self._logged_added = self.matches_added

    def reserve_by_value(self) -> dict[str, int]:
        """The reserve keyed by routing value ("na1", "americas")."""
        settings = self.ctx.settings
        return {
            settings.riot_platform: self.budget.reserve("platform"),
            settings.riot_region: self.budget.reserve("regional"),
        }

    def heartbeat(self, *, running: bool = True) -> dict[str, Any]:
        self._roll_day()
        return {
            "running": running,
            "paused_reason": self.paused_reason,
            "updated_at": _utcnow().isoformat(),
            "started_at": self.started_at.isoformat(),
            "matches_added": self.matches_added,
            "matches_added_today": self.matches_added_today,
            "day": self.day,
            "players_crawled": self.players_crawled,
            "frontier_uncrawled": self.counts.uncrawled,
            "frontier_total": self.counts.total,
            "last_error": self.last_error,
            "reserve": self.reserve_by_value(),
            "ladder_pages": self.ladder_pages,
            "timelines_fetched": self.timelines_fetched,
            "timelines_fetched_today": self.timelines_fetched_today,
            "timelines_pending": self.timelines_pending,
        }

    async def write_heartbeat(self, *, running: bool = True) -> None:
        """Merge the heartbeat into ``app_state``; failures are logged, never raised."""
        self._last_heartbeat = self._clock()
        try:
            async with session_scope(self.ctx.session_factory) as session:
                await app_state_repo.merge_state(
                    session, STATE_KEY, self.heartbeat(running=running)
                )
        except Exception:
            logger.exception("could not write the crawler heartbeat")

    async def _restore(self) -> None:
        """Carry today's counter and the learned ladder page ranges over a restart."""
        try:
            async with self.ctx.session_factory() as session:
                state = await app_state_repo.get_state(session, STATE_KEY)
        except Exception:
            logger.exception("could not read the crawler state")
            return
        if not state:
            return
        if state.get("day") == self.day:
            self.matches_added_today = int(state.get("matches_added_today") or 0)
            self.timelines_fetched_today = int(state.get("timelines_fetched_today") or 0)
        pages = state.get("ladder_pages")
        if isinstance(pages, dict):
            for key, value in pages.items():
                if (
                    isinstance(value, list)
                    and len(value) == 2
                    and isinstance(value[0], int)
                    and value[0] >= 1
                ):
                    self.ladder_pages[str(key)] = [value[0], bool(value[1])]


async def run_crawler(
    ctx: IngestContext,
    stop: asyncio.Event,
    poll_active: asyncio.Event,
    *,
    budget: CrawlBudget | None = None,
) -> None:
    """Crawl until ``stop`` is set. Pauses while ``poll_active`` is set (a roster poll tick is
    running) and whenever the Riot budget left over is below what the next poll needs.
    ``budget`` is the object the poller reports its tick usage to (see :class:`CrawlBudget`)."""
    await Crawler(ctx, stop, poll_active, budget=budget).run()
