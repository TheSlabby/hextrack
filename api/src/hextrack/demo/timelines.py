"""Synthetic match timelines for demo games (what the crawler stores for real ones).

Demo games have no Riot timeline, so :func:`demo_timeline_rows` derives plausible
``match_timeline_players`` rows from each player's final inventory: role starter items in the
first seconds, then the inventory (slot order, pets / support item / wards left out) spread
over the game, and a skill order that maxes the abilities in an order picked from the
champion id. Deterministic, so reseeding gives the same rows. This lets the champion pages'
build paths and skill orders be developed against demo data.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from hextrack.demo.matchgen import CONTROL_WARD, JUNGLE_PETS, SUPPORT_ITEMS

HEALTH_POTION: Final = 2003
WORLD_ATLAS: Final = 3865
STARTERS: Final[dict[str, tuple[int, ...]]] = {
    "TOP": (1054, HEALTH_POTION),
    "MIDDLE": (1056, HEALTH_POTION, HEALTH_POTION),
    "BOTTOM": (1055, HEALTH_POTION),
    "UTILITY": (WORLD_ATLAS, HEALTH_POTION, HEALTH_POTION),
}
#: Max orders (Q=1, W=2, E=3), chosen by champion id.
MAX_ORDERS: Final = ((1, 3, 2), (1, 2, 3), (3, 1, 2), (2, 1, 3), (3, 2, 1))
ULT_LEVELS: Final = (6, 11, 16)
_SKIP: Final = frozenset({CONTROL_WARD, *JUNGLE_PETS, *SUPPORT_ITEMS})


def skill_order(champion_id: int, level: int) -> list[int]:
    """Skill slot per level up to ``level``: one point in each basic ability first, R at
    6/11/16, then the max order."""
    first, second, third = MAX_ORDERS[champion_id % len(MAX_ORDERS)]
    points = {1: 0, 2: 0, 3: 0}
    order: list[int] = []
    for lvl in range(1, min(level, 18) + 1):
        if lvl in ULT_LEVELS:
            order.append(4)
            continue
        if lvl <= 3:
            slot = (first, second, third)[lvl - 1]
        else:
            slot = next(s for s in (first, second, third) if points[s] < 5)
        points[slot] += 1
        order.append(slot)
    return order


def demo_timeline_rows(match_id: str, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """``match_timeline_players`` rows for every participant of a demo match payload."""
    info = raw["info"]
    duration = int(info["gameDuration"])
    rows: list[dict[str, Any]] = []
    for p in info["participants"]:
        position = p.get("teamPosition") or ""
        inventory = [int(p.get(f"item{i}", 0)) for i in range(6)]
        if position == "JUNGLE":
            pet = next((i for i in inventory if i in JUNGLE_PETS), JUNGLE_PETS[0])
            start: tuple[int, ...] = (pet, HEALTH_POTION)
        else:
            start = STARTERS.get(position, (1055, HEALTH_POTION))
        later = [i for i in inventory if i and i not in _SKIP]
        purchases = [*start, *later]
        seconds = [5 + i for i in range(len(start))]
        step = max(60, (duration - 360) // max(len(later), 1))
        seconds += [min(360 + step * i, duration) for i in range(len(later))]
        rows.append(
            {
                "match_id": match_id,
                "participant_id": int(p["participantId"]),
                "purchases": purchases,
                "purchase_s": seconds,
                "skill_order": skill_order(int(p["championId"]), int(p.get("champLevel", 1))),
            }
        )
    return rows
