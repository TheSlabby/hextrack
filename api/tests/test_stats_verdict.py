"""Tier boundaries for the stack verdict (must match web/src/components/match/verdicts.ts)."""

from __future__ import annotations

import pytest

from hextrack.stats.verdict import score100, team_verdict


def _members(*scores: float | None) -> list[tuple[str, float | None]]:
    return [(f"p{i}", s) for i, s in enumerate(scores)]


@pytest.mark.parametrize(
    ("scores", "tier", "target", "gap"),
    [
        ((0.80, 0.71), "winTogether", None, 9),
        ((0.80, 0.70), "edge", "p0", 10),
        ((0.80, 0.61), "edge", "p0", 19),
        ((0.80, 0.60), "carry", "p0", 20),
        ((0.80, 0.41), "carry", "p0", 39),
        ((0.80, 0.40), "hardCarry", "p0", 40),
        ((0.50, 0.95, 0.60, 0.55, 0.52), "carry", "p1", 35),
        # No clear carry, but a clear bottom in a 3+ stack: a passenger.
        ((0.90, 0.85, 0.80, 0.60), "passenger", "p3", 20),
        ((0.90, 0.85, 0.80, 0.61), "winTogether", None, 5),
        # A clear carry wins over a passenger.
        ((0.90, 0.75, 0.70, 0.20), "edge", "p0", 15),
        # Duos never get "passenger": the only gap is the top one.
        ((0.80, 0.71), "winTogether", None, 9),
    ],
)
def test_win_tiers(scores, tier, target, gap):
    v = team_verdict(_members(*scores), win=True)
    assert v is not None
    assert (v.tier, v.target_puuid, v.gap) == (tier, target, gap)


@pytest.mark.parametrize(
    ("scores", "tier", "target", "gap"),
    [
        ((0.30, 0.21), "loseTogether", None, 9),
        ((0.30, 0.20), "offDay", "p1", 10),
        ((0.30, 0.10), "ranDown", "p1", 20),
        ((0.50, 0.10), "soloLost", "p1", 40),
        # Close at the bottom but one clearly stood out: they "tried".
        ((0.60, 0.20, 0.15, 0.12), "tried", "p0", 40),
        # Standing out by only 19 isn't enough: back to the bottom gap.
        ((0.34, 0.15, 0.12), "loseTogether", None, 3),
        # A clear bottom beats "tried": ran it down wins over tried.
        ((0.60, 0.30, 0.05), "ranDown", "p2", 25),
    ],
)
def test_loss_tiers(scores, tier, target, gap):
    v = team_verdict(_members(*scores), win=False)
    assert v is not None
    assert (v.tier, v.target_puuid, v.gap) == (tier, target, gap)


def test_needs_every_member_scored_and_no_remake():
    assert team_verdict(_members(0.9, None, 0.2), win=True) is None
    assert team_verdict(_members(0.9, 0.2), win=True, remake=True) is None
    assert team_verdict(_members(0.9), win=True) is None


def test_rounding_matches_javascript():
    # Math.round(62.5) == 63 in JS; Python's round(62.5) == 62.
    assert score100(0.625) == 63
    assert score100(1.2) == 100 and score100(-0.1) == 0
    v = team_verdict(_members(0.625, 0.43), win=True)
    assert v is not None and (v.tier, v.gap) == ("carry", 20)
