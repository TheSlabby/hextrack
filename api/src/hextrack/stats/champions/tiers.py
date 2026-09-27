"""Champion tiers: how strong a champion is in one role, relative to the other champions in
that role, for one patch window and queue. Pure (no I/O); the read side
(:mod:`hextrack.stats.champions.read`) feeds it the same per champion / role sums the champion
list loads and caches the result per (window, queue), so the list and every champion detail
of that window agree.

Rules, per role (TOP .. UTILITY):

* **Eligible:** role games >= max(:data:`MIN_GAMES`, :data:`MIN_ROLE_SHARE` of every game
  played in that role, all champions) AND (the role is at least :data:`MIN_CHAMPION_SHARE`
  of the champion's games, or it is the champion's most played role: most games, then most
  wins, then TOP .. UTILITY order, as the champion page picks its first role). Everyone
  else gets no tier (None).
* **Score:** ``z(adjusted win rate) + 0.5 * z(log pick rate) + 0.25 * z(ban rate)``, each
  z-score over the eligible champions of the role (population standard deviation; a
  feature with no spread contributes 0).

  - adjusted win rate = ``(wins + K * p) / (games + K)`` with K = :data:`PRIOR_GAMES` and
    p = the role's overall win rate (all champions in the role);
  - pick rate = role games / total matches in the window;
  - ban rate = the champion's bans / total matches (champion-wide, not per role).

* **Tiers** by rank within the role (score descending; ties: more games, then lower
  champion id, so the result is deterministic): the top 10% S, the next 20% A, the next 35%
  B, the next 20% C, the last 15% D (:data:`TIER_CUTS`). Cumulative cut-offs are
  ``round(n * share)`` (halves up), then nudged so that every tier gets at least one
  champion: 5 champions are S, A, B, C, D; 10 are 1/2/4/2/1; 20 are 2/4/7/4/3.
* A role with fewer than :data:`MIN_ELIGIBLE` eligible champions gives nobody a tier.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, Literal

from hextrack.stats.champions import ROLES

Tier = Literal["S", "A", "B", "C", "D"]

#: Eligibility: at least this many games in the role...
MIN_GAMES: Final = 30
#: ...and at least this share of all games played in the role.
MIN_ROLE_SHARE: Final = 0.005
#: The role must be this share of the champion's games (or its most played role).
MIN_CHAMPION_SHARE: Final = 0.10
#: Games of the role's win rate mixed into each champion's win rate.
PRIOR_GAMES: Final = 100
#: Score weights.
WEIGHT_WIN_RATE: Final = 1.0
WEIGHT_PICK_RATE: Final = 0.5
WEIGHT_BAN_RATE: Final = 0.25
#: (tier, share of the ranked champions), strongest first.
TIER_CUTS: Final[tuple[tuple[Tier, float], ...]] = (
    ("S", 0.10),
    ("A", 0.20),
    ("B", 0.35),
    ("C", 0.20),
    ("D", 0.15),
)
#: Roles with fewer eligible champions get no tiers.
MIN_ELIGIBLE: Final = len(TIER_CUTS)

#: Role order used to break "most played role" ties (as the champion pages do).
_ROLE_ORDER: Final = {role: i for i, role in enumerate(ROLES)}


@dataclass(frozen=True, slots=True)
class RoleLine:
    """One champion in one role over the window."""

    champion_id: int
    position: str
    games: int
    wins: int


@dataclass(frozen=True, slots=True)
class Scored:
    """An eligible champion's score and tier (for tests and debugging)."""

    champion_id: int
    position: str
    games: int
    adjusted_win_rate: float
    pick_rate: float
    ban_rate: float
    score: float
    tier: Tier | None


def tier_counts(n: int) -> list[int]:
    """How many of ``n`` ranked champions get each tier of :data:`TIER_CUTS` (all zero
    below :data:`MIN_ELIGIBLE`)."""
    k = len(TIER_CUTS)
    if n < MIN_ELIGIBLE:
        return [0] * k
    bounds: list[int] = []
    cumulative = 0.0
    previous = 0
    for index, (_tier, share) in enumerate(TIER_CUTS):
        cumulative += share
        bound = n if index == k - 1 else math.floor(n * cumulative + 0.5)
        remaining = k - 1 - index
        bound = max(bound, previous + 1)  # every tier gets someone...
        bound = min(bound, n - remaining)  # ...and leaves one for each weaker tier
        bounds.append(bound)
        previous = bound
    return [b - a for a, b in zip([0, *bounds[:-1]], bounds, strict=True)]


def _zscores(values: Sequence[float]) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    mean = math.fsum(values) / n
    std = math.sqrt(math.fsum((v - mean) ** 2 for v in values) / n)
    if std < 1e-12:
        return [0.0] * n
    return [(v - mean) / std for v in values]


def _main_roles(lines: Iterable[RoleLine]) -> dict[int, str]:
    best: dict[int, RoleLine] = {}
    for line in lines:
        current = best.get(line.champion_id)
        if current is None or _role_key(line) < _role_key(current):
            best[line.champion_id] = line
    return {cid: line.position for cid, line in best.items()}


def _role_key(line: RoleLine) -> tuple[int, int, int, str]:
    return (
        -line.games,
        -line.wins,
        _ROLE_ORDER.get(line.position, len(_ROLE_ORDER)),
        line.position,
    )


def score_roles(
    lines: Iterable[RoleLine], bans: Mapping[int, int], total_matches: int
) -> dict[str, list[Scored]]:
    """Every role's eligible champions, strongest first, with their score and tier.
    ``lines`` are the window's (champion, role) sums (roles outside TOP .. UTILITY should be
    left out by the caller); ``bans`` champion id -> bans in the window."""
    rows = sorted(
        (line for line in lines if line.games > 0),
        key=lambda line: (line.position, line.champion_id),
    )
    champion_games: dict[int, int] = defaultdict(int)
    for line in rows:
        champion_games[line.champion_id] += line.games
    main_role = _main_roles(rows)
    by_role: dict[str, list[RoleLine]] = defaultdict(list)
    for line in rows:
        by_role[line.position].append(line)

    total = max(total_matches, 1)
    out: dict[str, list[Scored]] = {}
    for position, role_lines in by_role.items():
        role_games = sum(line.games for line in role_lines)
        role_wins = sum(line.wins for line in role_lines)
        p = role_wins / role_games if role_games else 0.5
        min_games = max(MIN_GAMES, MIN_ROLE_SHARE * role_games)
        eligible = [
            line
            for line in role_lines
            if line.games >= min_games
            and (
                line.games / champion_games[line.champion_id] >= MIN_CHAMPION_SHARE
                or main_role.get(line.champion_id) == position
            )
        ]
        adjusted = [(line.wins + PRIOR_GAMES * p) / (line.games + PRIOR_GAMES) for line in eligible]
        pick = [line.games / total for line in eligible]
        ban = [bans.get(line.champion_id, 0) / total for line in eligible]
        z_win, z_pick, z_ban = (
            _zscores(adjusted),
            _zscores([math.log(v) for v in pick]),
            _zscores(ban),
        )
        scored = [
            Scored(
                champion_id=line.champion_id,
                position=position,
                games=line.games,
                adjusted_win_rate=adjusted[i],
                pick_rate=pick[i],
                ban_rate=ban[i],
                score=WEIGHT_WIN_RATE * z_win[i]
                + WEIGHT_PICK_RATE * z_pick[i]
                + WEIGHT_BAN_RATE * z_ban[i],
                tier=None,
            )
            for i, line in enumerate(eligible)
        ]
        scored.sort(key=lambda s: (-s.score, -s.games, s.champion_id))
        counts = tier_counts(len(scored))
        tiers = [
            tier
            for (tier, _share), count in zip(TIER_CUTS, counts, strict=True)
            for _ in range(count)
        ]
        out[position] = [replace(s, tier=tiers[i]) if tiers else s for i, s in enumerate(scored)]
    return out


def role_tiers(
    lines: Iterable[RoleLine], bans: Mapping[int, int], total_matches: int
) -> dict[tuple[int, str], Tier]:
    """(champion id, position) -> tier, for the champions that get one (see the module
    docstring); everyone else is absent (no tier)."""
    return {
        (s.champion_id, s.position): s.tier
        for scored in score_roles(lines, bans, total_matches).values()
        for s in scored
        if s.tier is not None
    }
