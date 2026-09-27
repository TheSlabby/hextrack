"""Champion pages: per champion / role / patch / queue rollups.

The worker folds every eligible match into the ``champion_*`` tables exactly once
(:mod:`hextrack.stats.champions.rollup`), and the API sums the rollups over the requested
patches (:mod:`hextrack.stats.champions.read`). Eligible: ranked solo / flex
(:data:`ROLLUP_QUEUES`), not a remake, started at or after the season start. Positions
outside :data:`ROLES` are not counted per champion (the match still counts in the patch
totals).

``matches.champ_rollup`` (the worker's queue):

* ``0``: to count.
* ``1``: counted without a timeline.
* ``2``: counted with its timeline (everything done).
* ``3``: counted without a timeline, and the timeline has since arrived; the worker adds
  only the timeline kinds (:data:`TIMELINE_KINDS`), ``timeline_games`` / ``timeline_wins``
  and ``champion_patch_totals.timeline_matches``, then sets ``2``.
* ``-1``: not eligible.

Storing a timeline (the crawler's backlog step) sets ``timeline_state = 'ok'`` and moves
``champ_rollup`` 1 -> 3 in the same statement.

``champion_rollups`` kinds and keys (item ids use the patch's Data Dragon item data; a
"completed" item is a finished legendary / boots-tier-2 item, with transforms folded into
their base item, e.g. Muramana -> Manamune):

* ``start``: items bought in the first 90 s after undos, sorted, repeats kept: "1055-2003".
* ``core``: the first three completed non-boots items in purchase order: "3078-3071-6333";
  ``extra_sum`` = seconds at which the third was bought.
* ``item4`` / ``item5`` / ``item6``: the 4th / 5th / 6th completed non-boots item bought.
* ``boots``: tier-2 boots in the final inventory ("3047"), or "0" for none.
* ``item``: each distinct completed non-boots item in the final inventory.
* ``rune_page``: "primaryStyle-subStyle-r1-r2-r3-r4-r5-r6" (keystone first).
* ``rune``: each of the 6 runes.
* ``shards``: "offense-flex-defense".
* ``shard``: "row:shardId", row 0 offense, 1 flex, 2 defense.
* ``spells``: the two summoner spell ids, ascending: "4-14".
* ``skill_max``: basic abilities in the order they reached 5 points (a skill that never
  does ranks by points at the end, then Q before W before E): "1-3-2".
* ``skill_at``: the ability levelled at each champion level 1..18: "level:slot" ("1:1").

Timeline kinds are over ``timeline_games``; the rest over ``games``.
"""

from __future__ import annotations

from typing import Final

ROLLUP_QUEUES: Final = (420, 440)
ROLES: Final = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")

#: Items bought up to this many seconds into the game are starting items.
START_WINDOW_S: Final = 90

KIND_START: Final = "start"
KIND_CORE: Final = "core"
KIND_ITEM4: Final = "item4"
KIND_ITEM5: Final = "item5"
KIND_ITEM6: Final = "item6"
KIND_BOOTS: Final = "boots"
KIND_ITEM: Final = "item"
KIND_RUNE_PAGE: Final = "rune_page"
KIND_RUNE: Final = "rune"
KIND_SHARDS: Final = "shards"
KIND_SHARD: Final = "shard"
KIND_SPELLS: Final = "spells"
KIND_SKILL_MAX: Final = "skill_max"
KIND_SKILL_AT: Final = "skill_at"

#: Kinds that need the match timeline.
TIMELINE_KINDS: Final = frozenset(
    {KIND_START, KIND_CORE, KIND_ITEM4, KIND_ITEM5, KIND_ITEM6, KIND_SKILL_MAX, KIND_SKILL_AT}
)
ALL_KINDS: Final = TIMELINE_KINDS | {
    KIND_BOOTS,
    KIND_ITEM,
    KIND_RUNE_PAGE,
    KIND_RUNE,
    KIND_SHARDS,
    KIND_SHARD,
    KIND_SPELLS,
}

#: "no boots" key of KIND_BOOTS.
NO_BOOTS_KEY: Final = "0"


def join_key(ids: list[int] | tuple[int, ...]) -> str:
    return "-".join(str(i) for i in ids)


def split_key(key: str) -> list[int]:
    return [int(part) for part in key.split("-")] if key else []
