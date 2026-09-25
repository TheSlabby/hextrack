"""Carry / "ran it down" verdicts for a stack of roster teammates.

Teammates share the result, so comparing their AI Scores is fair (the one place the site
talks about carrying; see web/DESIGN.md). The tier depends on the gap in AI Score points:
on a win the clear top scorer carried, on a loss the clear bottom scorer ran it down, and on
a loss that's close at the bottom a teammate who clearly stood out "tried". On a win with no
clear carry, a 3+ stack can still have a clear bottom: they were a "passenger" (got carried).
With two players the top and bottom gaps are the same number, so duos never get "passenger".

KEEP IN SYNC with web/src/components/match/verdicts.ts (``verdictTier``): the gaps, the
"tried" rule, the rounding (JS ``Math.round``) and "every member scored". The TS side types
its text table against ``VerdictTier`` in api/schemas.py, so a renamed tier fails the build.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from hextrack.api.schemas import VerdictTier

#: AI Score point gaps for the loud, normal and mild tiers.
HARD_GAP, CARRY_GAP, EDGE_GAP = 40, 20, 10
#: On a loss, a bottom gap under this is "close"; then a top gap of CARRY_GAP+ means "tried".
TRIED_CLOSE = 10

WIN_TIERS: tuple[tuple[int, VerdictTier], ...] = (
    (HARD_GAP, "hardCarry"),
    (CARRY_GAP, "carry"),
    (EDGE_GAP, "edge"),
)
LOSS_TIERS: tuple[tuple[int, VerdictTier], ...] = (
    (HARD_GAP, "soloLost"),
    (CARRY_GAP, "ranDown"),
    (EDGE_GAP, "offDay"),
)
CARRY_TIERS: frozenset[VerdictTier] = frozenset({"hardCarry", "carry", "edge"})
RAN_DOWN_TIERS: frozenset[VerdictTier] = frozenset({"soloLost", "ranDown"})


@dataclass(frozen=True, slots=True)
class Verdict:
    tier: VerdictTier
    target_puuid: str | None
    gap: int


def score100(rate: float) -> int:
    """0..1 -> 0..100 like the frontend's ``toScore100`` (``Math.round``: halves round up,
    unlike Python's ``round``)."""
    return math.floor(max(0.0, min(1.0, rate)) * 100 + 0.5)


def team_verdict(
    members: Sequence[tuple[str, float | None]], *, win: bool, remake: bool = False
) -> Verdict | None:
    """``members`` are ``(puuid, ai_score 0..1 or None)``. None unless every member (2+) is
    scored and the game isn't a remake."""
    if remake or len(members) < 2 or any(score is None for _, score in members):
        return None
    ranked = sorted(((score100(s), p) for p, s in members if s is not None), reverse=True)
    (first, first_p), (second, _) = ranked[0], ranked[1]
    (second_last, _), (last, last_p) = ranked[-2], ranked[-1]

    if win:
        gap = first - second
        tier = next((t for g, t in WIN_TIERS if gap >= g), None)
        if tier is not None:
            return Verdict(tier, first_p, gap)
        if second_last - last >= CARRY_GAP:
            return Verdict("passenger", last_p, second_last - last)
        return Verdict("winTogether", None, gap)

    if second_last - last < TRIED_CLOSE and first - second >= CARRY_GAP:
        return Verdict("tried", first_p, first - second)
    gap = second_last - last
    tier = next((t for g, t in LOSS_TIERS if gap >= g), "loseTogether")
    return Verdict(tier, last_p if tier != "loseTogether" else None, gap)
