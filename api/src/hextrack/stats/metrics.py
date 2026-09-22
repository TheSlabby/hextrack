"""Small numeric helpers shared by the aggregates and the response builders.

Every derived number the API returns is computed by one of these functions so the rules
("KDA with zero deaths", "kill participation with zero team kills", ...) live in one place.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Final

from hextrack.ingest import mapping

#: Derived ratios are rounded to this many decimals (stored AI scores are returned as is).
DECIMALS: Final = 4
#: A game shorter than this (seconds) is a remake even when no one early-surrendered. The
#: same rule is applied at ingestion (``matches.remake``), so stats, AI scoring and the bot
#: never disagree about which games count; kept here for rows stored before that.
REMAKE_MAX_SECONDS: Final = mapping.REMAKE_MAX_SECONDS


def to_float(value: float | int | Decimal | None) -> float:
    """SQL aggregate result (numeric -> Decimal, NULL -> None) as a plain float."""
    return float(value) if value is not None else 0.0


def to_optional_float(value: float | int | Decimal | None) -> float | None:
    return float(value) if value is not None else None


def to_int(value: int | Decimal | None) -> int:
    return int(value) if value is not None else 0


def rounded(value: float) -> float:
    return round(value, DECIMALS)


def safe_div(numerator: float, denominator: float) -> float:
    """``numerator / denominator``, or 0.0 when the denominator is 0."""
    return numerator / denominator if denominator else 0.0


def clamp_rate(value: float | None) -> float | None:
    """Clamp a probability-like value into [0, 1] (None stays None)."""
    if value is None:
        return None
    return min(1.0, max(0.0, float(value)))


def winrate(wins: int, games: int) -> float:
    """Wins / games in [0, 1]; 0.0 for no games."""
    return rounded(clamp_rate(safe_div(wins, games)) or 0.0)


def game_kda(kills: int, deaths: int, assists: int) -> float:
    """Single-game KDA: ``(k + a) / d``, and ``k + a`` for a deathless ("perfect") game."""
    return rounded((kills + assists) / deaths if deaths else float(kills + assists))


def total_kda(kills: int, deaths: int, assists: int) -> float:
    """KDA over totals: ``(k + a) / max(d, 1)``."""
    return rounded((kills + assists) / max(deaths, 1))


def per_minute(value: float, duration_seconds: int) -> float:
    """``value`` per minute of game time; 0.0 for a zero-length game."""
    return rounded(safe_div(value * 60.0, duration_seconds))


def kill_participation(kills: int, assists: int, team_kills: int) -> float:
    """``(k + a) / team kills`` in [0, 1]; 0.0 when the team got no kills."""
    return rounded(clamp_rate(safe_div(kills + assists, team_kills)) or 0.0)


def is_remake(remake_flag: bool, duration_seconds: int) -> bool:
    """A remake: someone early-surrendered, or the game ended before 5 minutes."""
    return bool(remake_flag) or duration_seconds < REMAKE_MAX_SECONDS


def average(values: Iterable[float]) -> float | None:
    """Arithmetic mean, or None for no values."""
    items = list(values)
    return sum(items) / len(items) if items else None
