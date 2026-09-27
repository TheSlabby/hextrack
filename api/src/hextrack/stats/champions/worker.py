"""The champion rollup worker: folds matches into the ``champion_*`` tables exactly once.

:func:`run_rollup_batch` takes up to ``limit`` matches from the queue (``champ_rollup`` 0 or
3, oldest ingested first, ``FOR UPDATE SKIP LOCKED``), marks ineligible ones -1, fills rune
pages and bans that older rows lack from ``matches.raw``, sums every match's contributions
(:mod:`hextrack.stats.champions.rollup`) in memory, upserts them additively and sets each
match's flag, all in the caller's transaction: either everything of a batch is counted and
flagged, or nothing is. Batches (and :func:`rebuild`) serialise on a transaction-level
advisory lock, so the worker and a CLI run never interleave.

:func:`run_rollups` runs batches for a bounded wall time (the worker calls it after each
poll), :func:`prune` drops tiny combinations on old patches, :func:`champions_status`
summarises the queue and the tables for ``hextrack champions status``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.config import Settings
from hextrack.db.engine import session_scope
from hextrack.ingest.mapping import ban_ids as raw_ban_ids
from hextrack.ingest.mapping import role_bound_item, rune_page
from hextrack.stats.champions import ROLLUP_QUEUES
from hextrack.stats.champions.rollup import (
    STAT_FIELDS,
    Increments,
    MatchLine,
    PlayerLine,
    TimelineLine,
)

if TYPE_CHECKING:
    from hextrack.stats.champions.items import ItemCatalog

logger = logging.getLogger(__name__)

#: ``pg_advisory_xact_lock`` key of the rollup ("HXTRCHMP").
ROLLUP_LOCK_KEY: Final = 0x4858_5452_4348_4D50
BATCH_SIZE: Final = 500
#: Rows per upsert statement (arrays through ``unnest``).
UPSERT_CHUNK: Final = 5000
#: Wall time the worker spends on rollups after each poll.
WORKER_BUDGET_SECONDS: Final = 15.0
#: :func:`prune` keeps every row of the newest this-many patches...
PRUNE_KEEP_PATCHES: Final = 3
#: ...and on older patches only rows with at least this many games.
PRUNE_MIN_GAMES: Final = 3
#: The worker prunes this often.
PRUNE_EVERY_SECONDS: Final = 24 * 60 * 60

STATE_TODO: Final = 0
STATE_COUNTED: Final = 1
STATE_WITH_TIMELINE: Final = 2
STATE_TIMELINE_LATE: Final = 3
STATE_INELIGIBLE: Final = -1

CHAMPION_TABLES: Final = (
    "champion_rollups",
    "champion_matchups",
    "champion_stats",
    "champion_bans",
    "champion_patch_totals",
)


class CatalogSource(Protocol):
    """What the worker needs from :class:`hextrack.riot.ddragon.DDragon`."""

    async def item_catalog(self, patch: str) -> ItemCatalog | None: ...


def _version_key(patch: str) -> tuple[int, ...]:
    return tuple(int(part) for part in patch.split(".") if part.isdigit())


# --- one batch ------------------------------------------------------------------------------


@dataclass(slots=True)
class _Queued:
    match_id: str
    patch: str
    queue_id: int
    duration_s: int
    game_start: datetime
    remake: bool
    state: int
    timeline_state: str | None
    ban_ids: list[int] | None


_SELECT_QUEUE = text(
    """
    SELECT match_id, patch, queue_id, game_duration, game_start, remake, champ_rollup,
           timeline_state, ban_ids
    FROM matches
    WHERE champ_rollup IN (0, 3)
    ORDER BY ingested_at
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
    """
)

_SELECT_PLAYERS = text(
    """
    SELECT match_id, puuid, participant_id, team_id, champion_id, champion_name, team_position,
           win, kills, deaths, assists, total_damage_dealt_to_champions,
           total_minions_killed + neutral_minions_killed AS cs, gold_earned, items,
           summoner1_id, summoner2_id, primary_style_id, secondary_style_id, rune_ids,
           stat_shards, role_bound_item
    FROM match_participants
    WHERE match_id = ANY(:ids)
    """
)

_SELECT_PERKS = text(
    """
    SELECT m.match_id, p->>'puuid' AS puuid, p->'perks' AS perks,
           p->'roleBoundItem' AS role_bound_item
    FROM matches m CROSS JOIN LATERAL jsonb_array_elements(m.raw->'info'->'participants') p
    WHERE m.match_id = ANY(:ids) AND jsonb_typeof(m.raw->'info'->'participants') = 'array'
    """
)

_SELECT_TEAMS = text(
    "SELECT match_id, raw->'info'->'teams' AS teams FROM matches WHERE match_id = ANY(:ids)"
)

_SELECT_TIMELINES = text(
    """
    SELECT match_id, participant_id, purchases, purchase_s, skill_order
    FROM match_timeline_players
    WHERE match_id = ANY(:ids)
    """
)

_FILL_RUNES = text(
    """
    UPDATE match_participants mp
    SET primary_style_id = COALESCE(mp.primary_style_id, x.primary_style_id),
        rune_ids = COALESCE(mp.rune_ids, CAST(x.rune_ids AS smallint[])),
        stat_shards = COALESCE(mp.stat_shards, CAST(x.stat_shards AS smallint[])),
        role_bound_item = COALESCE(mp.role_bound_item, x.role_bound_item)
    FROM unnest(CAST(:match_ids AS text[]), CAST(:puuids AS text[]),
                CAST(:styles AS smallint[]), CAST(:runes AS text[]), CAST(:shards AS text[]),
                CAST(:bound AS integer[]))
         AS x(match_id, puuid, primary_style_id, rune_ids, stat_shards, role_bound_item)
    WHERE mp.match_id = x.match_id AND mp.puuid = x.puuid
    """
)

_SET_FLAGS = text(
    """
    UPDATE matches m
    SET champ_rollup = x.state,
        ban_ids = COALESCE(m.ban_ids, CAST(x.bans AS smallint[]))
    FROM unnest(CAST(:match_ids AS text[]), CAST(:states AS smallint[]), CAST(:bans AS text[]))
         AS x(match_id, state, bans)
    WHERE m.match_id = x.match_id
    """
)


def _pg_array(values: Sequence[int] | None) -> str | None:
    """Postgres array literal for an int list (passed as text, cast in SQL)."""
    if values is None:
        return None
    return "{" + ",".join(str(int(v)) for v in values) + "}"


def _eligible(q: _Queued, season_start: datetime) -> bool:
    return q.queue_id in ROLLUP_QUEUES and not q.remake and q.game_start >= season_start


async def _fill_runes(session: AsyncSession, players: Mapping[str, list[PlayerLine]]) -> int:
    """Fill NULL rune pages / shards of these matches' players from ``matches.raw`` (in
    memory and in the table). Returns the rows updated."""
    missing = [
        match_id
        for match_id, lines in players.items()
        if any(
            p.rune_ids is None
            or p.stat_shards is None
            or p.primary_style_id is None
            or p.role_bound_item is None
            for p in lines
        )
    ]
    if not missing:
        return 0
    found: dict[tuple[str, str], tuple[int | None, list[int] | None, list[int] | None]] = {}
    bound_found: dict[tuple[str, str], int | None] = {}
    for row in (await session.execute(_SELECT_PERKS, {"ids": missing})).all():
        if row.puuid is None:
            continue
        bound_found[(row.match_id, row.puuid)] = role_bound_item(
            {"roleBoundItem": row.role_bound_item}
        )
        if row.perks is not None:
            found[(row.match_id, row.puuid)] = rune_page({"perks": row.perks})
    match_ids: list[str] = []
    puuid_list: list[str] = []
    styles: list[int | None] = []
    runes: list[str | None] = []
    shards: list[str | None] = []
    bound: list[int | None] = []
    for match_id in missing:
        for p in players[match_id]:
            page = found.get((match_id, p.puuid)) or (None, None, None)
            bound_item = bound_found.get((match_id, p.puuid))
            if page == (None, None, None) and bound_item is None:
                continue
            if p.role_bound_item is None:
                p.role_bound_item = bound_item
            style, rune_ids, stat_shards = page
            if p.primary_style_id is None:
                p.primary_style_id = style
            if p.rune_ids is None:
                p.rune_ids = rune_ids
            if p.stat_shards is None:
                p.stat_shards = stat_shards
            match_ids.append(match_id)
            puuid_list.append(p.puuid)
            styles.append(style)
            runes.append(_pg_array(rune_ids))
            shards.append(_pg_array(stat_shards))
            bound.append(bound_item)
    if match_ids:
        await session.execute(
            _FILL_RUNES,
            {
                "match_ids": match_ids,
                "puuids": puuid_list,
                "styles": styles,
                "runes": runes,
                "shards": shards,
                "bound": bound,
            },
        )
    return len(match_ids)


def _upsert_sql(
    table: str,
    keys: Sequence[tuple[str, str]],
    values: Sequence[tuple[str, str]],
    *,
    replace: Sequence[str] = (),
) -> Any:
    """``INSERT ... SELECT FROM unnest(arrays) ON CONFLICT (keys) DO UPDATE`` adding every
    value column (``replace`` columns are overwritten instead)."""
    columns = [*keys, *values]
    names = ", ".join(name for name, _ in columns)
    arrays = ", ".join(f"CAST(:{name} AS {sqltype}[])" for name, sqltype in columns)
    updates = ", ".join(
        f"{name} = excluded.{name}"
        if name in replace
        else f"{name} = {table}.{name} + excluded.{name}"
        for name, _ in values
    )
    return text(
        f"INSERT INTO {table} ({names}) SELECT * FROM unnest({arrays}) "
        f"ON CONFLICT ({', '.join(name for name, _ in keys)}) DO UPDATE SET {updates}"
    )


_CHAMP_KEY = (
    ("champion_id", "integer"),
    ("position", "text"),
    ("patch", "text"),
    ("queue_id", "integer"),
)
_COUNT_FIELDS = frozenset({"games", "wins", "timeline_games", "timeline_wins"})
_UPSERT_STATS = _upsert_sql(
    "champion_stats",
    _CHAMP_KEY,
    [("champion_key", "text")]
    + [(name, "integer" if name in _COUNT_FIELDS else "bigint") for name in STAT_FIELDS],
    replace=("champion_key",),
)
_UPSERT_ROLLUPS = _upsert_sql(
    "champion_rollups",
    (*_CHAMP_KEY, ("kind", "text"), ("key", "text")),
    (("games", "integer"), ("wins", "integer"), ("extra_sum", "bigint")),
)
_UPSERT_MATCHUPS = _upsert_sql(
    "champion_matchups",
    (*_CHAMP_KEY, ("opponent_id", "integer")),
    (("games", "integer"), ("wins", "integer"), ("gold_diff_sum", "bigint")),
)
_UPSERT_BANS = _upsert_sql(
    "champion_bans",
    (("patch", "text"), ("queue_id", "integer"), ("champion_id", "integer")),
    (("bans", "integer"),),
)
_UPSERT_TOTALS = _upsert_sql(
    "champion_patch_totals",
    (("patch", "text"), ("queue_id", "integer")),
    (("matches", "integer"), ("timeline_matches", "integer")),
)


async def _upsert(
    session: AsyncSession, stmt: Any, names: Sequence[str], rows: list[tuple[Any, ...]]
) -> None:
    """Run ``stmt`` over ``rows`` (tuples in ``names`` order), sorted by key, in chunks."""
    rows.sort()
    for start in range(0, len(rows), UPSERT_CHUNK):
        chunk = rows[start : start + UPSERT_CHUNK]
        columns = list(zip(*chunk, strict=True))
        params = {name: list(col) for name, col in zip(names, columns, strict=True)}
        await session.execute(stmt, params)


async def apply_increments(session: AsyncSession, inc: Increments) -> None:
    """Add a batch's increments to the ``champion_*`` tables."""
    key_names = [name for name, _ in _CHAMP_KEY]
    if inc.stats:
        await _upsert(
            session,
            _UPSERT_STATS,
            [*key_names, "champion_key", *STAT_FIELDS],
            [
                (*key, row.champion_key, *(getattr(row, name) for name in STAT_FIELDS))
                for key, row in inc.stats.items()
            ],
        )
    if inc.rollups:
        await _upsert(
            session,
            _UPSERT_ROLLUPS,
            [*key_names, "kind", "key", "games", "wins", "extra_sum"],
            [(*key, *value) for key, value in inc.rollups.items()],
        )
    if inc.matchups:
        await _upsert(
            session,
            _UPSERT_MATCHUPS,
            [*key_names, "opponent_id", "games", "wins", "gold_diff_sum"],
            [(*key, *value) for key, value in inc.matchups.items()],
        )
    if inc.bans:
        await _upsert(
            session,
            _UPSERT_BANS,
            ["patch", "queue_id", "champion_id", "bans"],
            [(*key, count) for key, count in inc.bans.items()],
        )
    if inc.totals:
        await _upsert(
            session,
            _UPSERT_TOTALS,
            ["patch", "queue_id", "matches", "timeline_matches"],
            [(*key, *value) for key, value in inc.totals.items()],
        )


async def run_rollup_batch(
    session: AsyncSession,
    ddragon: CatalogSource,
    settings: Settings,
    limit: int = BATCH_SIZE,
) -> int:
    """Count up to ``limit`` queued matches into the rollups in ``session``'s transaction
    (the caller commits). Returns how many matches left the queue (counted or marked
    ineligible); 0 when the queue is empty, another batch holds the rollup lock, or no item
    data is available for the queued patches."""
    locked = await session.scalar(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": ROLLUP_LOCK_KEY}
    )
    if not locked:
        return 0
    queued = [
        _Queued(
            match_id=r.match_id,
            patch=r.patch,
            queue_id=r.queue_id,
            duration_s=r.game_duration,
            game_start=r.game_start,
            remake=r.remake,
            state=r.champ_rollup,
            timeline_state=r.timeline_state,
            ban_ids=list(r.ban_ids) if r.ban_ids is not None else None,
        )
        for r in (await session.execute(_SELECT_QUEUE, {"limit": limit})).all()
    ]
    if not queued:
        return 0

    flags: dict[str, tuple[int, str | None]] = {}
    work: list[_Queued] = []
    for q in queued:
        if q.state == STATE_TODO and not _eligible(q, settings.season_start):
            flags[q.match_id] = (STATE_INELIGIBLE, None)
        else:
            work.append(q)

    catalogs: dict[str, ItemCatalog | None] = {}
    for patch in sorted({q.patch for q in work}):
        catalogs[patch] = await ddragon.item_catalog(patch)
    skipped = [q for q in work if catalogs.get(q.patch) is None]
    if skipped:
        logger.warning(
            "champion rollup: no item data for patch(es) %s; %d matches wait",
            ", ".join(sorted({q.patch for q in skipped})),
            len(skipped),
        )
    work = [q for q in work if catalogs.get(q.patch) is not None]

    if work:
        ids = [q.match_id for q in work]
        players: dict[str, list[PlayerLine]] = {q.match_id: [] for q in work}
        for r in (await session.execute(_SELECT_PLAYERS, {"ids": ids})).all():
            line = PlayerLine(
                participant_id=r.participant_id,
                team_id=r.team_id,
                champion_id=r.champion_id,
                champion_name=r.champion_name,
                position=r.team_position,
                win=r.win,
                kills=r.kills,
                deaths=r.deaths,
                assists=r.assists,
                damage=r.total_damage_dealt_to_champions,
                cs=r.cs,
                gold=r.gold_earned,
                items=list(r.items or ()),
                spells=(r.summoner1_id, r.summoner2_id),
                primary_style_id=r.primary_style_id,
                secondary_style_id=r.secondary_style_id,
                rune_ids=list(r.rune_ids) if r.rune_ids is not None else None,
                stat_shards=list(r.stat_shards) if r.stat_shards is not None else None,
                role_bound_item=r.role_bound_item,
                puuid=r.puuid,
            )
            players[r.match_id].append(line)

        todo = {q.match_id for q in work if q.state == STATE_TODO}
        await _fill_runes(session, {m: players[m] for m in todo})
        bans_from_raw: dict[str, list[int] | None] = {}
        need_bans = [q.match_id for q in work if q.state == STATE_TODO and q.ban_ids is None]
        if need_bans:
            for r in (await session.execute(_SELECT_TEAMS, {"ids": need_bans})).all():
                bans_from_raw[r.match_id] = raw_ban_ids({"teams": r.teams})

        timelines: dict[str, dict[int, TimelineLine]] = {}
        with_timeline = [q.match_id for q in work if q.timeline_state == "ok"]
        if with_timeline:
            for r in (await session.execute(_SELECT_TIMELINES, {"ids": with_timeline})).all():
                timelines.setdefault(r.match_id, {})[r.participant_id] = TimelineLine(
                    purchases=list(r.purchases),
                    purchase_s=list(r.purchase_s),
                    skill_order=list(r.skill_order),
                )

        inc = Increments()
        for q in work:
            bans = q.ban_ids if q.ban_ids is not None else bans_from_raw.get(q.match_id)
            match = MatchLine(
                match_id=q.match_id,
                patch=q.patch,
                queue_id=q.queue_id,
                duration_s=q.duration_s,
                ban_ids=bans,
                players=players[q.match_id],
            )
            catalog = catalogs[q.patch]
            assert catalog is not None
            used = inc.add_match(
                match,
                timelines.get(q.match_id, {}),
                catalog,
                timeline_only=q.state == STATE_TIMELINE_LATE,
            )
            new_bans = _pg_array(bans) if q.ban_ids is None and bans is not None else None
            flags[q.match_id] = (STATE_WITH_TIMELINE if used else STATE_COUNTED, new_bans)
        await apply_increments(session, inc)

    if flags:
        ordered = sorted(flags.items())
        await session.execute(
            _SET_FLAGS,
            {
                "match_ids": [m for m, _ in ordered],
                "states": [state for _, (state, _) in ordered],
                "bans": [bans for _, (_, bans) in ordered],
            },
        )
    return len(flags)


# --- driving it -----------------------------------------------------------------------------


@dataclass(slots=True)
class RollupRun:
    matches: int = 0
    batches: int = 0
    seconds: float = 0.0


async def run_rollups(
    session_factory: async_sessionmaker[AsyncSession],
    ddragon: CatalogSource,
    settings: Settings,
    *,
    budget_seconds: float | None = WORKER_BUDGET_SECONDS,
    stop: asyncio.Event | None = None,
    batch_size: int = BATCH_SIZE,
    clock: Callable[[], float] = time.monotonic,
    on_batch: Callable[[RollupRun], None] | None = None,
) -> RollupRun:
    """Run batches (one transaction each) until the queue is drained, ``budget_seconds``
    of wall time have passed (None: no limit) or ``stop`` is set."""
    started = clock()
    run = RollupRun()
    while stop is None or not stop.is_set():
        if budget_seconds is not None and clock() - started >= budget_seconds:
            break
        async with session_scope(session_factory) as session:
            done = await run_rollup_batch(session, ddragon, settings, limit=batch_size)
        if done == 0:
            break
        run.matches += done
        run.batches += 1
        run.seconds = clock() - started
        if on_batch is not None:
            on_batch(run)
        if done < batch_size:
            break
    run.seconds = clock() - started
    return run


async def rebuild(session: AsyncSession) -> int:
    """Empty the ``champion_*`` tables and queue every match again (in the caller's
    transaction). Returns the matches re-queued. Uses DELETE: the app role may not
    TRUNCATE."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ROLLUP_LOCK_KEY})
    for table in CHAMPION_TABLES:
        await session.execute(text(f"DELETE FROM {table}"))
    result = await session.execute(
        text("UPDATE matches SET champ_rollup = 0 WHERE champ_rollup <> 0")
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def prune(
    session: AsyncSession,
    *,
    keep_patches: int = PRUNE_KEEP_PATCHES,
    min_games: int = PRUNE_MIN_GAMES,
) -> int:
    """Delete ``champion_rollups`` rows with fewer than ``min_games`` games on every patch
    older than the newest ``keep_patches``. Returns the rows deleted."""
    patches = sorted(
        (await session.scalars(text("SELECT DISTINCT patch FROM champion_patch_totals"))).all(),
        key=_version_key,
        reverse=True,
    )
    old = patches[keep_patches:]
    if not old:
        return 0
    result = await session.execute(
        text("DELETE FROM champion_rollups WHERE patch = ANY(:patches) AND games < :min"),
        {"patches": old, "min": min_games},
    )
    return int(getattr(result, "rowcount", 0) or 0)


class RollupRunner:
    """The worker's rollup step: after each poll, count queued matches for up to
    :data:`WORKER_BUDGET_SECONDS` and, once a day, prune. Owns a DDragon for item data.
    Never raises (errors are logged)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        ddragon: CatalogSource | None = None,
        *,
        budget_seconds: float = WORKER_BUDGET_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self._ddragon = ddragon
        self._owns_ddragon = ddragon is None
        self.budget_seconds = budget_seconds
        self._clock = clock
        self._last_prune: float | None = None

    def _source(self) -> CatalogSource:
        if self._ddragon is None:
            from hextrack.riot.ddragon import DDragon

            self._ddragon = DDragon()
        return self._ddragon

    async def run(self, stop: asyncio.Event | None = None) -> RollupRun | None:
        try:
            run = await run_rollups(
                self.session_factory,
                self._source(),
                self.settings,
                budget_seconds=self.budget_seconds,
                stop=stop,
                clock=self._clock,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("champion rollup failed")
            return None
        if run.matches:
            logger.info(
                "champion rollup: %d matches in %d batches (%.1fs)",
                run.matches,
                run.batches,
                run.seconds,
            )
        await self._maybe_prune()
        return run

    async def _maybe_prune(self) -> None:
        now = self._clock()
        if self._last_prune is not None and now - self._last_prune < PRUNE_EVERY_SECONDS:
            return
        self._last_prune = now
        try:
            async with session_scope(self.session_factory) as session:
                deleted = await prune(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("champion rollup prune failed")
            return
        if deleted:
            logger.info("champion rollup: pruned %d small rows on old patches", deleted)

    async def aclose(self) -> None:
        if self._owns_ddragon and self._ddragon is not None:
            close = getattr(self._ddragon, "aclose", None)
            if close is not None:
                await close()
            self._ddragon = None


# --- status ---------------------------------------------------------------------------------


@dataclass(slots=True)
class PatchCount:
    patch: str
    queue_id: int
    matches: int
    timeline_matches: int


@dataclass(slots=True)
class ChampionsStatus:
    #: champ_rollup value -> matches
    by_state: dict[int, int] = field(default_factory=dict)
    #: counted, their timeline stored ("ok"), per champ_rollup (0 / 3 are still queued)
    timelines_ok: dict[int, int] = field(default_factory=dict)
    patches: list[PatchCount] = field(default_factory=list)
    #: table -> row count
    tables: dict[str, int] = field(default_factory=dict)


async def champions_status(session: AsyncSession) -> ChampionsStatus:
    status = ChampionsStatus()
    rows = await session.execute(
        text(
            """
            SELECT champ_rollup, count(*) AS n,
                   count(*) FILTER (WHERE timeline_state = 'ok') AS ok
            FROM matches GROUP BY champ_rollup ORDER BY champ_rollup
            """
        )
    )
    for r in rows.all():
        status.by_state[int(r.champ_rollup)] = int(r.n)
        status.timelines_ok[int(r.champ_rollup)] = int(r.ok)
    patch_rows = await session.execute(
        text("SELECT patch, queue_id, matches, timeline_matches FROM champion_patch_totals")
    )
    status.patches = sorted(
        (PatchCount(r.patch, r.queue_id, r.matches, r.timeline_matches) for r in patch_rows.all()),
        key=lambda p: (_version_key(p.patch), p.queue_id),
        reverse=True,
    )
    for table in (*CHAMPION_TABLES, "match_timeline_players"):
        status.tables[table] = int(await session.scalar(text(f"SELECT count(*) FROM {table}")) or 0)
    return status
