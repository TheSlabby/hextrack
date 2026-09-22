"""Ranked tier arithmetic shared by ingestion, API, leaderboard and bot.

``rank_value`` turns (tier, division, LP) into one comparable integer:
Iron IV 0 LP = 0, each division adds 100, each tier below Master adds 400. Master,
Grandmaster and Challenger have no divisions and share one LP ladder, so all three map to
``MASTER_BASE + lp`` (Master 0 LP = 2800).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

#: A refresh re-records an unchanged standing (``is_heartbeat``) once this much time has
#: passed, so the newest snapshot of a ranked queue is never older than this while the
#: player is being refreshed. The read side uses that to tell "unranked in this queue"
#: (league-v4 returns no entry, so nothing is written) from "this is the current standing".
RANK_HEARTBEAT_INTERVAL: Final = timedelta(hours=24)

RANKED_SOLO_5x5: Final = "RANKED_SOLO_5x5"
RANKED_FLEX_SR: Final = "RANKED_FLEX_SR"
RANKED_QUEUE_TYPES: Final[tuple[str, str]] = (RANKED_SOLO_5x5, RANKED_FLEX_SR)
#: queue_type -> match-v5 queue id.
QUEUE_TYPE_TO_QUEUE_ID: Final[dict[str, int]] = {RANKED_SOLO_5x5: 420, RANKED_FLEX_SR: 440}

TIER_ORDER: Final[tuple[str, ...]] = (
    "IRON",
    "BRONZE",
    "SILVER",
    "GOLD",
    "PLATINUM",
    "EMERALD",
    "DIAMOND",
    "MASTER",
    "GRANDMASTER",
    "CHALLENGER",
)
#: Lowest to highest.
DIVISION_ORDER: Final[tuple[str, ...]] = ("IV", "III", "II", "I")
APEX_TIERS: Final[frozenset[str]] = frozenset({"MASTER", "GRANDMASTER", "CHALLENGER"})

DIVISION_SIZE: Final = 100
TIER_SIZE: Final = DIVISION_SIZE * len(DIVISION_ORDER)
#: rank_value of Master 0 LP (7 divisioned tiers * 400).
MASTER_BASE: Final = TIER_ORDER.index("MASTER") * TIER_SIZE


def normalize_tier(tier: str) -> str:
    value = tier.strip().upper()
    if value not in TIER_ORDER:
        raise ValueError(f"unknown tier {tier!r}")
    return value


def is_apex(tier: str) -> bool:
    return normalize_tier(tier) in APEX_TIERS


def tier_index(tier: str) -> int:
    """0 for IRON .. 9 for CHALLENGER. Raises ValueError for unknown tiers."""
    return TIER_ORDER.index(normalize_tier(tier))


def division_index(rank: str) -> int:
    """0 for IV .. 3 for I."""
    value = rank.strip().upper()
    if value not in DIVISION_ORDER:
        raise ValueError(f"unknown division {rank!r}")
    return DIVISION_ORDER.index(value)


def compare_tiers(a: str, b: str) -> int:
    """-1 if tier ``a`` is below ``b``, 0 if equal, 1 if above."""
    ia, ib = tier_index(a), tier_index(b)
    return (ia > ib) - (ia < ib)


def rank_value(tier: str, rank: str | None, lp: int) -> int:
    """Single comparable integer for a ranked standing (see module docstring)."""
    t = normalize_tier(tier)
    if t in APEX_TIERS:
        return MASTER_BASE + max(lp, 0)
    if rank is None:
        raise ValueError(f"division required for tier {t}")
    return tier_index(t) * TIER_SIZE + division_index(rank) * DIVISION_SIZE + max(lp, 0)


def display_rank(tier: str | None, rank: str | None = None, lp: int | None = None) -> str:
    """Human label, e.g. "Gold II 45 LP", "Master 120 LP", "Unranked"."""
    if not tier:
        return "Unranked"
    t = normalize_tier(tier)
    parts = [t.capitalize() if t != "GRANDMASTER" else "Grandmaster"]
    if t not in APEX_TIERS and rank:
        parts.append(rank.strip().upper())
    label = " ".join(parts)
    if lp is not None:
        label += f" {lp} LP"
    return label


def queue_type_label(queue_type: str) -> str:
    return {RANKED_SOLO_5x5: "Ranked Solo/Duo", RANKED_FLEX_SR: "Ranked Flex"}.get(
        queue_type, queue_type
    )
