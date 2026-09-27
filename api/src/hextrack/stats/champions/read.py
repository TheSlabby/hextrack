"""Read side of the champion pages: sums the worker's rollups over a patch window.

Every query filters on the rollup tables' primary-key prefix (``champion_id``, ``position``,
``patch``, ``queue_id``) and aggregates in SQL (``SUM ... GROUP BY``); Python only applies
the display thresholds. The patch window, the champion list and champion details are kept
in :data:`hextrack.stats.champions.cache.CHAMPION_CACHE` for ~2 minutes; the squad view is a
live query over the roster's own rows.

Windows (``patch`` query value):

* ``"recent"``: the two newest patches with counted games;
* ``"season"``: every patch with counted games;
* one patch, e.g. ``"16.18"``: it must have counted games (:class:`UnknownPatch`).

Patches come from ``champion_patch_totals`` (all queues), ordered by their numeric version,
so "16.10" is newer than "16.9". The same patches are used whatever the ``queue`` filter;
``queue`` only narrows the rows summed (420 solo, 440 flex, or both).

Display rules (see the ``Champion*`` models in :mod:`hextrack.api.schemas`):

* option lists keep choices with at least max(8 games, 1% of the denominator), top 5 by
  games (popular items: top 10); rune picks keep every rune taken in at least 1% of games;
* a role is ``shown`` with at least 20 games and 10% of the champion's games, and the most
  played role always is;
* the highest win rate core build needs max(20, 3% of timeline games) and is compared on
  its win rate shrunk toward the role's win rate with 30 games of prior;
* lane matchups need 10 games; their adjusted win rate uses 20 games of prior;
* the skill path is the most common legal choice at each level (:func:`skill_path`).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import ColumnElement, bindparam, false, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.api.schemas import (
    BuildOption,
    ChampionBuilds,
    ChampionDetail,
    ChampionLaneMatchup,
    ChampionLaneMatchups,
    ChampionList,
    ChampionListRole,
    ChampionListRow,
    ChampionPatches,
    ChampionPatchInfo,
    ChampionRole,
    ChampionRoleDetail,
    ChampionRoleStats,
    ChampionRoleSummary,
    ChampionRunes,
    ChampionSquad,
    ChampionSquadRow,
    ItemSlotOptions,
    LeaderboardQueue,
    RunePageOption,
    RunePick,
    ShardPick,
    ShardSetOption,
    SkillMaxOption,
    SkillOrder,
    SpellOption,
)
from hextrack.config import Settings
from hextrack.db.models import (
    ChampionBan,
    ChampionMatchup,
    ChampionPatchTotal,
    ChampionRollup,
    ChampionStat,
    Match,
    MatchParticipant,
    Summoner,
)
from hextrack.stats import present, queries
from hextrack.stats.aggregate import LEADERBOARD_QUEUES, stat_rows
from hextrack.stats.champions import (
    KIND_BOOTS,
    KIND_CORE,
    KIND_ITEM,
    KIND_ITEM4,
    KIND_ITEM5,
    KIND_ITEM6,
    KIND_RUNE,
    KIND_RUNE_PAGE,
    KIND_SHARD,
    KIND_SHARDS,
    KIND_SKILL_AT,
    KIND_SKILL_MAX,
    KIND_SPELLS,
    KIND_START,
    NO_BOOTS_KEY,
    ROLES,
    split_key,
)
from hextrack.stats.champions.cache import CHAMPION_CACHE
from hextrack.stats.metrics import (
    clamp_rate,
    per_minute,
    rounded,
    safe_div,
    to_int,
    to_optional_float,
    total_kda,
    winrate,
)

WINDOW_RECENT: Final = "recent"
WINDOW_SEASON: Final = "season"
#: Patches ``patch=recent`` covers.
RECENT_PATCHES: Final = 2

#: Option lists: at least this many games and this share of the denominator, top N.
OPTION_MIN_GAMES: Final = 8
OPTION_MIN_SHARE: Final = 0.01
OPTION_LIMIT: Final = 5
POPULAR_ITEMS_LIMIT: Final = 10
#: Rune picks: every rune taken in at least this share of games.
RUNE_PICK_MIN_SHARE: Final = 0.01
#: Role tabs.
ROLE_SHOWN_MIN_GAMES: Final = 20
ROLE_SHOWN_MIN_SHARE: Final = 0.10
#: Highest win rate core build.
CORE_BEST_MIN_GAMES: Final = 20
CORE_BEST_MIN_SHARE: Final = 0.03
CORE_BEST_PRIOR_GAMES: Final = 30
#: Lane matchups.
MATCHUP_MIN_GAMES: Final = 10
MATCHUP_PRIOR_GAMES: Final = 20
MATCHUP_LIMIT: Final = 60
#: Stats flagged as shaky below this many games.
SMALL_SAMPLE_GAMES: Final = 100

#: Skill slots: 1 Q, 2 W, 3 E, 4 R.
SKILL_R: Final = 4
R_LEVELS: Final = (6, 11, 16)
MAX_R_POINTS: Final = 3
MAX_BASIC_POINTS: Final = 5
MAX_LEVEL: Final = 18

_ROLE_ORDER: Final = {role: i for i, role in enumerate(ROLES)}


class UnknownPatch(LookupError):
    """``patch`` is not "recent", "season" or a patch with counted games."""


class ChampionNotFound(LookupError):
    """No counted games of this champion on any patch."""


# --- SQL helpers ---------------------------------------------------------------------------


def _in(column: ColumnElement[Any], name: str, values: Collection[Any]) -> ColumnElement[bool]:
    """``column IN (...)`` rendered with literal values: with an ordinary bind list,
    asyncpg's cached prepared statement switches to a generic plan after five runs (see
    :func:`hextrack.stats.aggregate.stat_rows`)."""
    return column.in_(
        bindparam(name, sorted(values), expanding=True, literal_execute=True, unique=True)
    )


def patch_sort_key(patch: str) -> tuple[tuple[int, ...], str]:
    """Numeric version order: "16.9" < "16.10" (non-numeric parts sort first)."""
    return tuple(int(part) if part.isdigit() else -1 for part in patch.split(".")), patch


def _engine(session: AsyncSession) -> Any:
    return session.bind


def _rate(numerator: int, denominator: int) -> float:
    """A share in [0, 1], rounded; 0 for an empty denominator."""
    return winrate(numerator, denominator)


# --- patch window --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PatchTotals:
    """``champion_patch_totals`` rows: (patch, queue) -> (matches, timeline matches)."""

    rows: Mapping[tuple[str, int], tuple[int, int]]

    @property
    def patches(self) -> list[str]:
        """Patches with counted games, newest first."""
        per_patch: dict[str, int] = defaultdict(int)
        for (patch, _queue), (matches, _timeline) in self.rows.items():
            per_patch[patch] += matches
        return sorted(
            (patch for patch, matches in per_patch.items() if matches > 0),
            key=patch_sort_key,
            reverse=True,
        )

    def matches(self, patches: Iterable[str], queues: Iterable[int]) -> int:
        wanted = set(queues)
        return sum(
            self.rows.get((patch, queue), (0, 0))[0] for patch in patches for queue in wanted
        )


@dataclass(frozen=True, slots=True)
class Window:
    """The requested patches and queues, and how many matches they counted."""

    label: str
    patches: tuple[str, ...]
    queue: LeaderboardQueue
    queue_ids: tuple[int, ...]
    total_matches: int


async def _patch_totals(session: AsyncSession) -> _PatchTotals:
    async def load() -> _PatchTotals:
        t = ChampionPatchTotal
        result = await session.execute(select(t.patch, t.queue_id, t.matches, t.timeline_matches))
        return _PatchTotals(
            rows={
                (patch, int(queue_id)): (to_int(matches), to_int(timeline))
                for patch, queue_id, matches, timeline in result.all()
            }
        )

    return await CHAMPION_CACHE.get_or_load(_engine(session), ("patch_totals",), load)


async def resolve_window(session: AsyncSession, patch: str, queue: LeaderboardQueue) -> Window:
    totals = await _patch_totals(session)
    available = totals.patches
    if patch == WINDOW_RECENT:
        patches = available[:RECENT_PATCHES]
    elif patch == WINDOW_SEASON:
        patches = available
    elif patch in available:
        patches = [patch]
    else:
        raise UnknownPatch(patch)
    queue_ids = LEADERBOARD_QUEUES[queue]
    return Window(
        label=patch,
        patches=tuple(patches),
        queue=queue,
        queue_ids=queue_ids,
        total_matches=totals.matches(patches, queue_ids),
    )


async def champion_patches(session: AsyncSession) -> ChampionPatches:
    """Patches with counted games this season (newest first) and the worker's backlog."""

    async def load() -> ChampionPatches:
        totals = await _patch_totals(session)
        infos: list[ChampionPatchInfo] = []
        for patch in totals.patches:
            matches = timeline = 0
            for (row_patch, _queue), (m, tl) in totals.rows.items():
                if row_patch == patch:
                    matches += m
                    timeline += tl
            infos.append(ChampionPatchInfo(patch=patch, matches=matches, timeline_matches=timeline))
        # Literal predicate so the planner can use the partial index ix_matches_rollup_todo.
        pending = await session.scalar(
            select(func.count()).select_from(Match).where(text("champ_rollup IN (0, 3)"))
        )
        return ChampionPatches(
            patches=infos,
            recent=[info.patch for info in infos[:RECENT_PATCHES]],
            pending_matches=to_int(pending),
        )

    return await CHAMPION_CACHE.get_or_load(_engine(session), ("patches",), load)


# --- champion names ------------------------------------------------------------------------


async def champion_names(session: AsyncSession) -> dict[int, str]:
    """champion id -> Data Dragon key for every champion with counted games (any patch)."""

    async def load() -> dict[int, str]:
        cs = ChampionStat
        stmt = select(cs.champion_id, func.max(cs.champion_key)).group_by(cs.champion_id)
        return {int(cid): key for cid, key in (await session.execute(stmt)).all() if key}

    return await CHAMPION_CACHE.get_or_load(_engine(session), ("champion_names",), load)


def resolve_champion(names: Mapping[int, str], champion: str) -> tuple[int, str]:
    """(id, key) for a Data Dragon key (any case) or a numeric champion id."""
    value = champion.strip()
    if value.isdigit():
        cid = int(value)
        if cid in names:
            return cid, names[cid]
        raise ChampionNotFound(champion)
    folded = value.casefold()
    for cid, key in names.items():
        if key.casefold() == folded:
            return cid, key
    raise ChampionNotFound(champion)


# --- list ----------------------------------------------------------------------------------


@dataclass(slots=True)
class _Totals:
    games: int = 0
    wins: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0

    def add(self, other: _Totals) -> None:
        self.games += other.games
        self.wins += other.wins
        self.kills += other.kills
        self.deaths += other.deaths
        self.assists += other.assists


def _role_sort_key(item: tuple[str, _Totals]) -> tuple[int, int, int]:
    position, totals = item
    return (-totals.games, -totals.wins, _ROLE_ORDER.get(position, len(ROLES)))


async def champion_list(
    session: AsyncSession, *, patch: str, queue: LeaderboardQueue
) -> ChampionList:
    """Every champion with games in the window, most games first."""
    window = await resolve_window(session, patch, queue)

    async def load() -> ChampionList:
        return await _build_list(session, window)

    key = ("list", window.label, window.patches, queue)
    return await CHAMPION_CACHE.get_or_load(_engine(session), key, load)


async def _build_list(session: AsyncSession, window: Window) -> ChampionList:
    per_role: dict[int, dict[str, _Totals]] = defaultdict(dict)
    names: dict[int, str] = {}
    bans: dict[int, int] = {}
    if window.patches:
        cs = ChampionStat
        stmt = (
            select(
                cs.champion_id,
                cs.position,
                func.max(cs.champion_key),
                func.sum(cs.games),
                func.sum(cs.wins),
                func.sum(cs.kills),
                func.sum(cs.deaths),
                func.sum(cs.assists),
            )
            .where(
                _in(cs.patch, "cl_patches", window.patches),
                _in(cs.queue_id, "cl_queues", window.queue_ids),
                _in(cs.position, "cl_roles", ROLES),
            )
            .group_by(cs.champion_id, cs.position)
        )
        for cid, position, key, games, wins, kills, deaths, assists in (
            await session.execute(stmt)
        ).all():
            if not to_int(games):
                continue
            names[int(cid)] = key
            per_role[int(cid)][position] = _Totals(
                to_int(games), to_int(wins), to_int(kills), to_int(deaths), to_int(assists)
            )
        cb = ChampionBan
        ban_stmt = (
            select(cb.champion_id, func.sum(cb.bans))
            .where(
                _in(cb.patch, "cl_ban_patches", window.patches),
                _in(cb.queue_id, "cl_ban_queues", window.queue_ids),
            )
            .group_by(cb.champion_id)
        )
        bans = {int(cid): to_int(n) for cid, n in (await session.execute(ban_stmt)).all()}

    total = window.total_matches
    rows: list[ChampionListRow] = []
    for cid, roles in per_role.items():
        overall = _Totals()
        for totals in roles.values():
            overall.add(totals)
        ordered = sorted(roles.items(), key=_role_sort_key)
        rows.append(
            ChampionListRow(
                champion_id=cid,
                champion_name=names[cid],
                games=overall.games,
                wins=overall.wins,
                win_rate=winrate(overall.wins, overall.games),
                pick_rate=_rate(overall.games, total),
                ban_rate=_rate(bans.get(cid, 0), total),
                kda=total_kda(overall.kills, overall.deaths, overall.assists),
                roles=[
                    ChampionListRole(
                        position=position,  # type: ignore[arg-type]
                        games=t.games,
                        wins=t.wins,
                        win_rate=winrate(t.wins, t.games),
                        share=_rate(t.games, overall.games),
                    )
                    for position, t in ordered
                ],
            )
        )
    rows.sort(key=lambda r: (-r.games, -r.wins, r.champion_name.casefold()))
    return ChampionList(
        patch=window.label,
        patches=list(window.patches),
        queue=window.queue,
        total_matches=total,
        rows=rows,
    )


# --- detail --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Agg:
    """One summed rollup choice."""

    key: str
    games: int
    wins: int
    extra: int = 0


def pick_options(
    aggs: Iterable[Agg],
    denominator: int,
    *,
    limit: int = OPTION_LIMIT,
    min_games: int = OPTION_MIN_GAMES,
    min_share: float = OPTION_MIN_SHARE,
) -> list[Agg]:
    """Choices with at least max(``min_games``, ``min_share`` of ``denominator``) games,
    most games first (then more wins, then key), at most ``limit``."""
    threshold = max(min_games, min_share * denominator)
    kept = [a for a in aggs if a.games >= threshold]
    kept.sort(key=lambda a: (-a.games, -a.wins, a.key))
    return kept[:limit]


def _shrunk(wins: int, games: int, prior_rate: float, prior_games: int) -> float:
    return (wins + prior_games * prior_rate) / (games + prior_games)


def best_core(core: Sequence[Agg], timeline_games: int, role_win_rate: float) -> Agg | None:
    """The core build with the best shrunk win rate among those with at least
    max(20, 3% of timeline games) games (ties: more games, then key)."""
    threshold = max(CORE_BEST_MIN_GAMES, CORE_BEST_MIN_SHARE * timeline_games)
    candidates = [a for a in core if a.games >= threshold]
    if not candidates:
        return None
    candidates.sort(
        key=lambda a: (
            -_shrunk(a.wins, a.games, role_win_rate, CORE_BEST_PRIOR_GAMES),
            -a.games,
            a.key,
        )
    )
    return candidates[0]


def _ints(key: str, length: int | None = None) -> list[int] | None:
    try:
        values = split_key(key)
    except ValueError:
        return None
    if length is not None and len(values) != length:
        return None
    return values


def _build_option(agg: Agg, denominator: int, *, with_time: bool = False) -> BuildOption | None:
    items = _ints(agg.key)
    if not items:
        return None
    return BuildOption(
        items=items,
        games=agg.games,
        wins=agg.wins,
        win_rate=winrate(agg.wins, agg.games),
        pick_rate=_rate(agg.games, denominator),
        avg_time_s=rounded(safe_div(agg.extra, agg.games)) if with_time else None,
    )


def _build_options(
    aggs: Iterable[Agg], denominator: int, *, limit: int = OPTION_LIMIT, with_time: bool = False
) -> list[BuildOption]:
    valid = [a for a in aggs if _ints(a.key)]
    options = (
        _build_option(a, denominator, with_time=with_time)
        for a in pick_options(valid, denominator, limit=limit)
    )
    return [o for o in options if o is not None]


# -- skills ---------------------------------------------------------------------------------


def _legal(level: int, points: tuple[int, int, int, int], slot: int) -> bool:
    if slot == SKILL_R:
        return level in R_LEVELS and points[3] < MAX_R_POINTS
    have = points[slot - 1]
    return have < MAX_BASIC_POINTS and have + 1 <= math.ceil(level / 2)


def skill_path(
    counts: Mapping[int, Mapping[int, int]], max_order: Sequence[int] = (1, 2, 3)
) -> list[int]:
    """The usual ability for levels 1..N (N = the highest level with data, at most 18).

    At each level the most common *legal* choice is taken: R only at 6, 11 and 16 (three
    points at most), a basic ability at most 5 points and at most ceil(level / 2) points by
    that level. Levels without a legal choice in the data fall back to R when it is
    available, else the basic abilities in ``max_order``. A choice that would leave no legal
    path to level N is skipped (a depth-first search; it only backtracks when the data would
    otherwise paint itself into a corner, e.g. no R at 6)."""
    levels = [
        lvl for lvl, slots in counts.items() if 1 <= lvl and any(n > 0 for n in slots.values())
    ]
    if not levels:
        return []
    length = min(MAX_LEVEL, max(levels))
    priority = {slot: i for i, slot in enumerate(max_order)}

    def preference(level: int) -> list[int]:
        at = counts.get(level, {})
        return sorted(
            (1, 2, 3, SKILL_R),
            key=lambda s: (-at.get(s, 0), 0 if s == SKILL_R else 1, priority.get(s, 3), s),
        )

    dead: set[tuple[int, tuple[int, int, int, int]]] = set()
    path: list[int] = []

    def search(level: int, points: tuple[int, int, int, int]) -> bool:
        if level > length:
            return True
        if (level, points) in dead:
            return False
        for slot in preference(level):
            if not _legal(level, points, slot):
                continue
            nxt = list(points)
            nxt[slot - 1] += 1
            path.append(slot)
            if search(level + 1, (nxt[0], nxt[1], nxt[2], nxt[3])):
                return True
            path.pop()
        dead.add((level, points))
        return False

    search(1, (0, 0, 0, 0))
    return path


def _skill_at_counts(aggs: Iterable[Agg]) -> dict[int, dict[int, int]]:
    counts: dict[int, dict[int, int]] = defaultdict(dict)
    for agg in aggs:
        level_s, _, slot_s = agg.key.partition(":")
        if not (level_s.isdigit() and slot_s.isdigit()):
            continue
        level, slot = int(level_s), int(slot_s)
        if 1 <= level <= MAX_LEVEL and 1 <= slot <= SKILL_R:
            counts[level][slot] = counts[level].get(slot, 0) + agg.games
    return counts


# -- one role -------------------------------------------------------------------------------


@dataclass(slots=True)
class _RoleRow:
    position: str
    games: int
    wins: int
    kills: int
    deaths: int
    assists: int
    damage: int
    cs: int
    gold: int
    duration_s: int
    timeline_games: int


def _role_stats(row: _RoleRow, total_matches: int) -> ChampionRoleStats:
    g = row.games
    return ChampionRoleStats(
        games=g,
        wins=row.wins,
        win_rate=winrate(row.wins, g),
        pick_rate=_rate(g, total_matches),
        avg_kills=rounded(safe_div(row.kills, g)),
        avg_deaths=rounded(safe_div(row.deaths, g)),
        avg_assists=rounded(safe_div(row.assists, g)),
        kda=total_kda(row.kills, row.deaths, row.assists),
        avg_damage=rounded(safe_div(row.damage, g)),
        avg_cs=rounded(safe_div(row.cs, g)),
        cs_per_min=per_minute(row.cs, row.duration_s),
        avg_gold=rounded(safe_div(row.gold, g)),
        avg_duration_s=rounded(safe_div(row.duration_s, g)),
        timeline_games=row.timeline_games,
        small_sample=g < SMALL_SAMPLE_GAMES,
    )


def build_role_detail(
    row: _RoleRow,
    rollups: Mapping[str, Sequence[Agg]],
    matchups: Sequence[tuple[int, str, int, int, int]],
    *,
    total_matches: int,
) -> ChampionRoleDetail:
    """Assemble one role's detail from its summed rollups (pure; no database access).
    ``matchups`` are (opponent id, name, games, wins, gold diff sum)."""
    games, tl = row.games, row.timeline_games
    role_wr = safe_div(row.wins, games)

    def kind(name: str) -> Sequence[Agg]:
        return rollups.get(name, ())

    # Builds.
    core_valid = [a for a in kind(KIND_CORE) if _ints(a.key)]
    core = _build_options(core_valid, tl, with_time=True)
    best = best_core(core_valid, tl, role_wr)
    core_best = None
    if best is not None and (not core or core[0].items != split_key(best.key)):
        core_best = _build_option(best, tl, with_time=True)
    boots_aggs = [a for a in kind(KIND_BOOTS) if a.key != NO_BOOTS_KEY]
    no_boots = sum(a.games for a in kind(KIND_BOOTS) if a.key == NO_BOOTS_KEY)
    slots = [
        ItemSlotOptions(slot=n, options=_build_options(kind(k), tl))
        for n, k in ((4, KIND_ITEM4), (5, KIND_ITEM5), (6, KIND_ITEM6))
    ]
    builds = ChampionBuilds(
        starting=_build_options(kind(KIND_START), tl),
        core=core,
        core_best=core_best,
        boots=_build_options(boots_aggs, games),
        no_boots_rate=_rate(no_boots, games),
        slots=slots,
        popular_items=_build_options(kind(KIND_ITEM), games, limit=POPULAR_ITEMS_LIMIT),
    )

    # Runes.
    pages: list[RunePageOption] = []
    page_aggs = [a for a in kind(KIND_RUNE_PAGE) if _ints(a.key, 8)]
    for agg in pick_options(page_aggs, games):
        ids = split_key(agg.key)
        pages.append(
            RunePageOption(
                primary_style_id=ids[0],
                secondary_style_id=ids[1],
                rune_ids=ids[2:],
                games=agg.games,
                wins=agg.wins,
                win_rate=winrate(agg.wins, agg.games),
                pick_rate=_rate(agg.games, games),
            )
        )
    picks = [
        RunePick(
            rune_id=int(a.key),
            games=a.games,
            wins=a.wins,
            win_rate=winrate(a.wins, a.games),
            pick_rate=_rate(a.games, games),
        )
        for a in sorted(kind(KIND_RUNE), key=lambda a: (-a.games, -a.wins, a.key))
        if a.key.isdigit() and games and a.games / games >= RUNE_PICK_MIN_SHARE
    ]
    shard_sets = [
        ShardSetOption(
            shard_ids=split_key(a.key),
            games=a.games,
            wins=a.wins,
            win_rate=winrate(a.wins, a.games),
            pick_rate=_rate(a.games, games),
        )
        for a in pick_options([a for a in kind(KIND_SHARDS) if _ints(a.key, 3)], games)
    ]
    shard_picks: list[ShardPick] = []
    for a in kind(KIND_SHARD):
        row_s, _, shard_s = a.key.partition(":")
        if not (row_s.isdigit() and shard_s.isdigit()) or int(row_s) > 2:
            continue
        shard_picks.append(
            ShardPick(
                row=int(row_s),
                shard_id=int(shard_s),
                games=a.games,
                win_rate=winrate(a.wins, a.games),
                pick_rate=_rate(a.games, games),
            )
        )
    shard_picks.sort(key=lambda p: (p.row, -p.games, p.shard_id))
    runes = ChampionRunes(pages=pages, picks=picks, shards=shard_sets, shard_picks=shard_picks)

    # Spells.
    spells = [
        SpellOption(
            spell_ids=sorted(split_key(a.key)),
            games=a.games,
            wins=a.wins,
            win_rate=winrate(a.wins, a.games),
            pick_rate=_rate(a.games, games),
        )
        for a in pick_options([a for a in kind(KIND_SPELLS) if _ints(a.key, 2)], games)
    ]

    # Skills.
    max_aggs = [
        a
        for a in kind(KIND_SKILL_MAX)
        if (ids := _ints(a.key, 3)) is not None and sorted(ids) == [1, 2, 3]
    ]
    max_orders = [
        SkillMaxOption(
            order=split_key(a.key),
            games=a.games,
            wins=a.wins,
            win_rate=winrate(a.wins, a.games),
            pick_rate=_rate(a.games, tl),
        )
        for a in pick_options(max_aggs, tl)
    ]
    top_order = max(max_aggs, key=lambda a: (a.games, a.wins), default=None)
    path = (
        skill_path(
            _skill_at_counts(kind(KIND_SKILL_AT)),
            split_key(top_order.key) if top_order else (1, 2, 3),
        )
        if tl > 0
        else []
    )
    skills = SkillOrder(max_orders=max_orders, path=path)

    # Lane matchups.
    lanes = ChampionLaneMatchups(
        min_games=MATCHUP_MIN_GAMES,
        rows=[
            ChampionLaneMatchup(
                champion_id=opp_id,
                champion_name=opp_name,
                games=m_games,
                wins=m_wins,
                win_rate=winrate(m_wins, m_games),
                adjusted_win_rate=rounded(
                    clamp_rate(_shrunk(m_wins, m_games, role_wr, MATCHUP_PRIOR_GAMES)) or 0.0
                ),
                avg_gold_diff=round(safe_div(gold_diff, m_games), 1),
            )
            for opp_id, opp_name, m_games, m_wins, gold_diff in matchups
            if m_games >= MATCHUP_MIN_GAMES
        ][:MATCHUP_LIMIT],
    )

    return ChampionRoleDetail(
        stats=_role_stats(row, total_matches),
        builds=builds,
        runes=runes,
        spells=spells,
        skills=skills,
        matchups=lanes,
    )


async def _role_rows(session: AsyncSession, champion_id: int, window: Window) -> list[_RoleRow]:
    cs = ChampionStat
    stmt = (
        select(
            cs.position,
            func.sum(cs.games),
            func.sum(cs.wins),
            func.sum(cs.kills),
            func.sum(cs.deaths),
            func.sum(cs.assists),
            func.sum(cs.damage),
            func.sum(cs.cs),
            func.sum(cs.gold),
            func.sum(cs.duration_s),
            func.sum(cs.timeline_games),
        )
        .where(
            cs.champion_id == champion_id,
            _in(cs.position, "cd_roles", ROLES),
            _in(cs.patch, "cd_patches", window.patches),
            _in(cs.queue_id, "cd_queues", window.queue_ids),
        )
        .group_by(cs.position)
    )
    rows = [
        _RoleRow(position, *(to_int(v) for v in values))
        for position, *values in (await session.execute(stmt)).all()
    ]
    rows = [r for r in rows if r.games > 0]
    rows.sort(key=lambda r: (-r.games, -r.wins, _ROLE_ORDER.get(r.position, len(ROLES))))
    return rows


async def _rollups(
    session: AsyncSession, champion_id: int, position: str, window: Window
) -> dict[str, list[Agg]]:
    r = ChampionRollup
    stmt = (
        select(r.kind, r.key, func.sum(r.games), func.sum(r.wins), func.sum(r.extra_sum))
        .where(
            r.champion_id == champion_id,
            r.position == position,
            _in(r.patch, "cr_patches", window.patches),
            _in(r.queue_id, "cr_queues", window.queue_ids),
        )
        .group_by(r.kind, r.key)
    )
    result: dict[str, list[Agg]] = defaultdict(list)
    for kind, key, games, wins, extra in (await session.execute(stmt)).all():
        if to_int(games) > 0:
            result[kind].append(Agg(key, to_int(games), to_int(wins), to_int(extra)))
    return dict(result)


async def _matchups(
    session: AsyncSession,
    champion_id: int,
    position: str,
    window: Window,
    names: Mapping[int, str],
    ddragon: Any | None,
) -> list[tuple[int, str, int, int, int]]:
    m = ChampionMatchup
    games = func.sum(m.games)
    stmt = (
        select(m.opponent_id, games, func.sum(m.wins), func.sum(m.gold_diff_sum))
        .where(
            m.champion_id == champion_id,
            m.position == position,
            _in(m.patch, "cm_patches", window.patches),
            _in(m.queue_id, "cm_queues", window.queue_ids),
        )
        .group_by(m.opponent_id)
        .having(games >= MATCHUP_MIN_GAMES)
        .order_by(games.desc(), func.sum(m.wins).desc(), m.opponent_id)
        .limit(MATCHUP_LIMIT)
    )
    rows = [
        (int(opp), to_int(g), to_int(w), to_int(diff))
        for opp, g, w, diff in (await session.execute(stmt)).all()
    ]
    lookup: Mapping[int, str] = names
    if ddragon is not None and any(opp not in names for opp, *_ in rows):
        try:
            lookup = {**(await ddragon.champion_map()), **names}
        except Exception:  # names are cosmetic; never fail the page over Data Dragon
            lookup = names
    return [(opp, lookup.get(opp, str(opp)), g, w, diff) for opp, g, w, diff in rows]


async def _champion_bans(session: AsyncSession, champion_id: int, window: Window) -> int:
    cb = ChampionBan
    stmt = select(func.coalesce(func.sum(cb.bans), 0)).where(
        cb.champion_id == champion_id,
        _in(cb.patch, "cb_patches", window.patches),
        _in(cb.queue_id, "cb_queues", window.queue_ids),
    )
    return to_int(await session.scalar(stmt))


async def champion_detail(
    session: AsyncSession,
    *,
    champion: str,
    patch: str,
    queue: LeaderboardQueue,
    role: ChampionRole | None,
    ddragon: Any | None = None,
) -> ChampionDetail:
    """One champion in the window: roles, and the detail of the requested role (the most
    played one when it is not given or has no games in the window)."""
    names = await champion_names(session)
    champion_id, champion_name = resolve_champion(names, champion)
    window = await resolve_window(session, patch, queue)

    async def load() -> ChampionDetail:
        return await _build_detail(
            session, champion_id, champion_name, window, role, names, ddragon
        )

    key = ("detail", champion_id, window.label, window.patches, queue, role)
    return await CHAMPION_CACHE.get_or_load(_engine(session), key, load)


async def _build_detail(
    session: AsyncSession,
    champion_id: int,
    champion_name: str,
    window: Window,
    role: ChampionRole | None,
    names: Mapping[int, str],
    ddragon: Any | None,
) -> ChampionDetail:
    total = window.total_matches
    role_rows: list[_RoleRow] = []
    bans = 0
    if window.patches:
        role_rows = await _role_rows(session, champion_id, window)
        bans = await _champion_bans(session, champion_id, window)
    games = sum(r.games for r in role_rows)
    wins = sum(r.wins for r in role_rows)
    summaries = [
        ChampionRoleSummary(
            position=r.position,  # type: ignore[arg-type]
            games=r.games,
            wins=r.wins,
            win_rate=winrate(r.wins, r.games),
            share=_rate(r.games, games),
            shown=i == 0
            or (
                r.games >= ROLE_SHOWN_MIN_GAMES and safe_div(r.games, games) >= ROLE_SHOWN_MIN_SHARE
            ),
        )
        for i, r in enumerate(role_rows)
    ]
    by_position = {r.position: r for r in role_rows}
    chosen = by_position.get(role) if role else None
    if chosen is None and role_rows:
        chosen = role_rows[0]
    detail = None
    if chosen is not None:
        rollups = await _rollups(session, champion_id, chosen.position, window)
        matchups = await _matchups(session, champion_id, chosen.position, window, names, ddragon)
        detail = build_role_detail(chosen, rollups, matchups, total_matches=total)
    return ChampionDetail(
        champion_id=champion_id,
        champion_name=champion_name,
        patch=window.label,
        patches=list(window.patches),
        queue=window.queue,
        total_matches=total,
        games=games,
        win_rate=winrate(wins, games) if games else None,
        pick_rate=_rate(games, total),
        ban_rate=_rate(bans, total),
        roles=summaries,
        role=chosen.position if chosen else None,  # type: ignore[arg-type]
        detail=detail,
    )


# --- squad ---------------------------------------------------------------------------------


def _ai_filter(model_version: str | None, column: ColumnElement[Any]) -> ColumnElement[bool]:
    return column == model_version if model_version is not None else false()


async def champion_squad(
    session: AsyncSession,
    settings: Settings,
    *,
    champion: str,
    queue: LeaderboardQueue,
    model_version: str | None,
) -> ChampionSquad:
    """Roster players' ranked games on the champion this season (roster games only, remakes
    excluded), most games first. Not cached."""
    names = await champion_names(session)
    champion_id, champion_name = resolve_champion(names, champion)
    roster: list[Summoner] = await queries.tracked_summoners(session)
    rows: list[ChampionSquadRow] = []
    if roster:
        lines = (
            stat_rows(
                queues=LEADERBOARD_QUEUES[queue],
                since=settings.season_start,
                puuids=[s.puuid for s in roster],
            )
            .where(MatchParticipant.champion_id == champion_id, Match.source == "roster")
            .cte("champ_lines")
        )
        totals_stmt = select(
            lines.c.puuid,
            func.count().label("games"),
            func.count().filter(lines.c.win.is_(True)).label("wins"),
            func.sum(lines.c.kills).label("kills"),
            func.sum(lines.c.deaths).label("deaths"),
            func.sum(lines.c.assists).label("assists"),
            func.avg(lines.c.ai_score)
            .filter(_ai_filter(model_version, lines.c.model_version))
            .label("ai_score"),
        ).group_by(lines.c.puuid)
        totals = {r["puuid"]: r for r in (await session.execute(totals_stmt)).mappings()}

        last_stmt = (
            select(lines.c.puuid, lines.c.match_id, lines.c.game_start)
            .order_by(lines.c.puuid, lines.c.game_start.desc(), lines.c.match_id.desc())
            .distinct(lines.c.puuid)
        )
        last: dict[str, tuple[str, datetime]] = {
            puuid: (match_id, start)
            for puuid, match_id, start in (await session.execute(last_stmt)).all()
        }

        pos_stmt = select(lines.c.puuid, lines.c.team_position, func.count()).group_by(
            lines.c.puuid, lines.c.team_position
        )
        positions: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for puuid, position, n in (await session.execute(pos_stmt)).all():
            positions[puuid].append((to_int(n), position or ""))

        for summoner in roster:
            t = totals.get(summoner.puuid)
            if t is None or summoner.puuid not in last:
                continue
            games, wins = to_int(t["games"]), to_int(t["wins"])
            main = min(
                positions.get(summoner.puuid, [(0, "")]),
                key=lambda item: (-item[0], _ROLE_ORDER.get(item[1], len(ROLES)), item[1]),
            )[1]
            match_id, started = last[summoner.puuid]
            rows.append(
                ChampionSquadRow(
                    puuid=summoner.puuid,
                    game_name=summoner.game_name,
                    tag_line=summoner.tag_line,
                    profile_icon_id=summoner.profile_icon_id,
                    games=games,
                    wins=wins,
                    win_rate=winrate(wins, games),
                    kda=total_kda(to_int(t["kills"]), to_int(t["deaths"]), to_int(t["assists"])),
                    avg_ai_score=clamp_rate(to_optional_float(t["ai_score"])),
                    main_position=present.normalize_position(main),
                    last_played=started,
                    last_match_id=match_id,
                )
            )
        rows.sort(
            key=lambda r: (
                -r.games,
                -r.wins,
                (r.game_name or "").casefold(),
                (r.tag_line or "").casefold(),
                r.puuid,
            )
        )
    return ChampionSquad(
        champion_id=champion_id,
        champion_name=champion_name,
        queue=queue,
        model_version=model_version,
        rows=rows,
    )
