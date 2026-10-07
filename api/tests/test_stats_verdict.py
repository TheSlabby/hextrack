"""Tier boundaries for the stack verdict (must match web/src/components/match/verdicts.ts)."""

from __future__ import annotations

import pytest

from hextrack.stats.verdict import score100, team_verdict


def _members(*scores: float | None) -> list[tuple[str, float | None]]:
    return [(f"p{i}", s) for i, s in enumerate(scores)]


@pytest.mark.parametrize(
    ("scores", "tier", "target", "gap"),
    [
        ((0.80, 0.61), "winTogether", None, 19),
        ((0.80, 0.60), "edge", "p0", 20),
        ((0.80, 0.51), "edge", "p0", 29),
        ((0.80, 0.50), "carry", "p0", 30),
        ((0.80, 0.36), "carry", "p0", 44),
        ((0.80, 0.35), "hardCarry", "p0", 45),
        ((0.50, 0.95, 0.60, 0.55, 0.52), "carry", "p1", 35),
        # No clear carry, but a clear bottom in a 3+ stack: a passenger.
        ((0.90, 0.85, 0.80, 0.50), "passenger", "p3", 30),
        ((0.90, 0.85, 0.80, 0.51), "winTogether", None, 5),
        # A clear carry wins over a passenger.
        ((0.90, 0.70, 0.65, 0.20), "edge", "p0", 20),
        # Duos never get "passenger": the only gap is the top one.
        ((0.80, 0.61), "winTogether", None, 19),
    ],
)
def test_win_tiers(scores, tier, target, gap):
    v = team_verdict(_members(*scores), win=True)
    assert v is not None
    assert (v.tier, v.target_puuid, v.gap) == (tier, target, gap)


@pytest.mark.parametrize(
    ("scores", "tier", "target", "gap"),
    [
        ((0.30, 0.11), "loseTogether", None, 19),
        ((0.30, 0.10), "offDay", "p1", 20),
        ((0.40, 0.10), "ranDown", "p1", 30),
        ((0.55, 0.10), "soloLost", "p1", 45),
        # Close at the bottom but one clearly stood out: they "tried".
        ((0.60, 0.20, 0.15, 0.12), "tried", "p0", 40),
        # Standing out by only 29 isn't enough: back to the bottom gap.
        ((0.44, 0.15, 0.12), "loseTogether", None, 3),
        # A clear bottom beats "tried": ran it down wins over tried.
        ((0.70, 0.40, 0.05), "ranDown", "p2", 35),
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
    v = team_verdict(_members(0.625, 0.33), win=True)
    assert v is not None and (v.tier, v.gap) == ("carry", 30)
