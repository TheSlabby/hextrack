"""Pure per-match contributions to the ``champion_*`` rollup tables.

:class:`Increments` accumulates what a batch of matches adds to every table (keys exactly
as documented in :mod:`hextrack.stats.champions`); the worker
(:mod:`hextrack.stats.champions.worker`) upserts the totals additively. Nothing here does
I/O, so the rules are unit-testable with plain objects.

Per match (``timeline_only=False``, a ``champ_rollup = 0`` game):

* ``champion_patch_totals.matches`` + 1 (and ``timeline_matches`` + 1 with a timeline);
* ``champion_bans`` + 1 per distinct banned champion (Riot can list one twice);
* per player in a :data:`ROLES` position: ``champion_stats``, the lane matchup against the
  enemy in the same position (when each team has exactly one there), and every rollup kind;
  the timeline kinds and ``timeline_games`` / ``timeline_wins`` only when that player has a
  timeline row.

A ``champ_rollup = 3`` game (``timeline_only=True``) was counted without its timeline; it adds
only the timeline kinds, ``timeline_games`` / ``timeline_wins`` and ``timeline_matches``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

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
    START_WINDOW_S,
    join_key,
)
from hextrack.stats.champions.items import ItemCatalog

#: Inventory slots item0..item5 (item6 is the trinket).
INVENTORY_SLOTS = 6
#: Points a basic ability has when maxed.
SKILL_MAX_POINTS = 5
BASIC_SKILLS = (1, 2, 3)
MAX_LEVEL = 18
CORE_SIZE = 3


@dataclass(slots=True)
class PlayerLine:
    """What the rollups read from one ``match_participants`` row."""

    participant_id: int
    team_id: int
    champion_id: int
    champion_name: str
    position: str
    win: bool
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    damage: int = 0
    cs: int = 0
    gold: int = 0
    #: item0..item6 as stored (item6 = trinket).
    items: Sequence[int] = ()
    spells: tuple[int, int] = (0, 0)
    primary_style_id: int | None = None
    secondary_style_id: int | None = None
    rune_ids: Sequence[int] | None = None
    stat_shards: Sequence[int] | None = None
    #: The role quest slot (bot lane's boots live here); 0 / None = empty.
    role_bound_item: int | None = None
    puuid: str = ""


@dataclass(slots=True)
class TimelineLine:
    """One ``match_timeline_players`` row."""

    purchases: Sequence[int]
    purchase_s: Sequence[int]
    skill_order: Sequence[int]


@dataclass(slots=True)
class MatchLine:
    match_id: str
    patch: str
    queue_id: int
    duration_s: int
    ban_ids: Sequence[int] | None
    players: list[PlayerLine]


# --- per-player rules ---------------------------------------------------------------------


def starting_items(timeline: TimelineLine, catalog: ItemCatalog) -> list[int]:
    """Items bought up to :data:`START_WINDOW_S` (undos already removed at extraction),
    canonical, sorted, repeats kept. Trinkets (the free ward everyone takes) are left out."""
    return sorted(
        catalog.canonical(item)
        for item, second in zip(timeline.purchases, timeline.purchase_s, strict=False)
        if second <= START_WINDOW_S and not catalog.is_trinket(item)
    )


def completed_order(timeline: TimelineLine, catalog: ItemCatalog) -> list[tuple[int, int]]:
    """``(canonical item, second)`` of each completed non-boots item in purchase order; a
    re-bought item (sold, then bought again) counts once, at its first purchase."""
    seen: set[int] = set()
    order: list[tuple[int, int]] = []
    for item, second in zip(timeline.purchases, timeline.purchase_s, strict=False):
        canonical = catalog.canonical(item)
        if canonical in seen or not catalog.is_legendary(canonical):
            continue
        seen.add(canonical)
        order.append((canonical, second))
    return order


def skill_max_order(skill_order: Sequence[int]) -> list[int]:
    """Basic abilities (1 Q, 2 W, 3 E) in the order they reached :data:`SKILL_MAX_POINTS`;
    the rest by points at the end, then Q before W before E."""
    points: Counter[int] = Counter()
    maxed: list[int] = []
    for slot in skill_order:
        if slot not in BASIC_SKILLS:
            continue
        points[slot] += 1
        if points[slot] == SKILL_MAX_POINTS:
            maxed.append(slot)
    rest = sorted((s for s in BASIC_SKILLS if s not in maxed), key=lambda s: (-points[s], s))
    return maxed + rest


def final_items(items: Sequence[int], catalog: ItemCatalog) -> list[int]:
    """Distinct canonical completed non-boots items in item0..item5, in slot order."""
    out: list[int] = []
    for item in items[:INVENTORY_SLOTS]:
        if item and catalog.is_legendary(item):
            canonical = catalog.canonical(item)
            if canonical not in out:
                out.append(canonical)
    return out


def final_boots(
    items: Sequence[int], catalog: ItemCatalog, role_bound_item: int | None = None
) -> str:
    """Tier-2 boots in item0..item5 or the role quest slot (where bot lane keeps them; upgrades
    folded), or :data:`NO_BOOTS_KEY`."""
    for item in [*items[:INVENTORY_SLOTS], role_bound_item or 0]:
        if item and catalog.is_boots(item) and catalog.is_completed(item):
            return str(catalog.canonical(item))
    return NO_BOOTS_KEY


def lane_opponents(players: Iterable[PlayerLine]) -> dict[int, PlayerLine]:
    """participant id -> the enemy in the same position, for positions in :data:`ROLES`
    where each team has exactly one player."""
    by_slot: dict[tuple[str, int], list[PlayerLine]] = {}
    for p in players:
        if p.position in ROLES:
            by_slot.setdefault((p.position, p.team_id), []).append(p)
    out: dict[int, PlayerLine] = {}
    for (position, team), mine in by_slot.items():
        enemies = [
            p for (pos, t), group in by_slot.items() if pos == position and t != team for p in group
        ]
        if len(mine) == 1 and len(enemies) == 1:
            out[mine[0].participant_id] = enemies[0]
    return out


def rune_keys(p: PlayerLine) -> list[tuple[str, str]]:
    """``(kind, key)`` for the rune page, each rune, the shards and each shard."""
    out: list[tuple[str, str]] = []
    runes = list(p.rune_ids) if p.rune_ids is not None else None
    if (
        runes is not None
        and len(runes) == 6
        and p.primary_style_id is not None
        and p.secondary_style_id is not None
    ):
        out.append((KIND_RUNE_PAGE, join_key([p.primary_style_id, p.secondary_style_id, *runes])))
        out.extend((KIND_RUNE, str(r)) for r in dict.fromkeys(runes))
    shards = list(p.stat_shards) if p.stat_shards is not None else None
    if shards is not None and len(shards) == 3:
        out.append((KIND_SHARDS, join_key(shards)))
        out.extend((KIND_SHARD, f"{row}:{shard}") for row, shard in enumerate(shards))
    return out


def timeline_keys(timeline: TimelineLine, catalog: ItemCatalog) -> list[tuple[str, str, int]]:
    """``(kind, key, extra)`` of every timeline kind for one player."""
    out: list[tuple[str, str, int]] = []
    start = starting_items(timeline, catalog)
    if start:
        out.append((KIND_START, join_key(start), 0))
    order = completed_order(timeline, catalog)
    if len(order) >= CORE_SIZE:
        core = order[:CORE_SIZE]
        out.append((KIND_CORE, join_key([item for item, _ in core]), core[-1][1]))
    for index, kind in ((3, KIND_ITEM4), (4, KIND_ITEM5), (5, KIND_ITEM6)):
        if len(order) > index:
            out.append((kind, str(order[index][0]), 0))
    if timeline.skill_order:
        out.append((KIND_SKILL_MAX, join_key(skill_max_order(timeline.skill_order)), 0))
        out.extend(
            (KIND_SKILL_AT, f"{level}:{slot}", 0)
            for level, slot in enumerate(timeline.skill_order[:MAX_LEVEL], start=1)
        )
    return out


def static_keys(p: PlayerLine, catalog: ItemCatalog) -> list[tuple[str, str]]:
    """``(kind, key)`` of every kind that needs no timeline."""
    out: list[tuple[str, str]] = [(KIND_BOOTS, final_boots(p.items, catalog, p.role_bound_item))]
    out.extend((KIND_ITEM, str(item)) for item in final_items(p.items, catalog))
    out.extend(rune_keys(p))
    spells = sorted(p.spells)
    if all(spells):
        out.append((KIND_SPELLS, join_key(spells)))
    return out


# --- accumulator --------------------------------------------------------------------------

type StatKey = tuple[int, str, str, int]
type RollupKey = tuple[int, str, str, int, str, str]
type MatchupKey = tuple[int, str, str, int, int]


@dataclass(slots=True)
class StatRow:
    """Increments of one ``champion_stats`` row."""

    champion_key: str
    games: int = 0
    wins: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    damage: int = 0
    cs: int = 0
    gold: int = 0
    duration_s: int = 0
    timeline_games: int = 0
    timeline_wins: int = 0


#: champion_stats value columns after champion_key, in order (StatRow fields).
STAT_FIELDS = (
    "games",
    "wins",
    "kills",
    "deaths",
    "assists",
    "damage",
    "cs",
    "gold",
    "duration_s",
    "timeline_games",
    "timeline_wins",
)


@dataclass(slots=True)
class Increments:
    """Summed increments of a batch, keyed by each table's primary key."""

    #: (champion_id, position, patch, queue_id) -> champion_stats increments
    stats: dict[StatKey, StatRow] = field(default_factory=dict)
    #: (patch, queue_id, champion_id) -> bans
    bans: Counter[tuple[str, int, int]] = field(default_factory=Counter)
    #: (patch, queue_id) -> [matches, timeline_matches]
    totals: dict[tuple[str, int], list[int]] = field(default_factory=dict)
    #: (champion_id, position, patch, queue_id, kind, key) -> [games, wins, extra_sum]
    rollups: dict[RollupKey, list[int]] = field(default_factory=dict)
    #: (champion_id, position, patch, queue_id, opponent_id) -> [games, wins, gold_diff_sum]
    matchups: dict[MatchupKey, list[int]] = field(default_factory=dict)

    def add_match(
        self,
        match: MatchLine,
        timelines: Mapping[int, TimelineLine],
        catalog: ItemCatalog,
        *,
        timeline_only: bool = False,
    ) -> bool:
        """Add one match; ``timelines`` maps participant id -> timeline row (empty when the
        match has none). Returns True when a timeline was used."""
        patch, queue = match.patch, match.queue_id
        used_timeline = any(p.participant_id in timelines for p in match.players)
        if timeline_only and not used_timeline:
            return False
        total = self.totals.setdefault((patch, queue), [0, 0])
        total[1] += 1 if used_timeline else 0
        if not timeline_only:
            total[0] += 1
            for champion_id in set(match.ban_ids or ()):
                if champion_id > 0:
                    self.bans[(patch, queue, champion_id)] += 1

        opponents = {} if timeline_only else lane_opponents(match.players)
        for p in match.players:
            if p.position not in ROLES:
                continue
            timeline = timelines.get(p.participant_id)
            if timeline_only and timeline is None:
                continue
            base: StatKey = (p.champion_id, p.position, patch, queue)
            win = 1 if p.win else 0
            stat = self.stats.get(base)
            if stat is None:
                stat = self.stats[base] = StatRow(p.champion_name)
            stat.champion_key = p.champion_name
            if not timeline_only:
                stat.games += 1
                stat.wins += win
                stat.kills += p.kills
                stat.deaths += p.deaths
                stat.assists += p.assists
                stat.damage += p.damage
                stat.cs += p.cs
                stat.gold += p.gold
                stat.duration_s += match.duration_s
                for kind, key in static_keys(p, catalog):
                    self._rollup((*base, kind, key), win, 0)
                opponent = opponents.get(p.participant_id)
                if opponent is not None:
                    row = self.matchups.setdefault((*base, opponent.champion_id), [0, 0, 0])
                    row[0] += 1
                    row[1] += win
                    row[2] += p.gold - opponent.gold
            if timeline is not None:
                stat.timeline_games += 1
                stat.timeline_wins += win
                for kind, key, extra in timeline_keys(timeline, catalog):
                    self._rollup((*base, kind, key), win, extra)
        return used_timeline

    def _rollup(self, key: RollupKey, win: int, extra: int) -> None:
        row = self.rollups.get(key)
        if row is None:
            self.rollups[key] = [1, win, extra]
        else:
            row[0] += 1
            row[1] += win
            row[2] += extra

    def row_count(self) -> int:
        return (
            len(self.stats)
            + len(self.bans)
            + len(self.totals)
            + len(self.rollups)
            + len(self.matchups)
        )
