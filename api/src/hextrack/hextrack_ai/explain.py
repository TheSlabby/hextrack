"""Per-stat attributions behind a player's AI Score (owner: B3).

What the "What drives the score" chart shows, per stat: how much it moved the player's
Hex Score, on average over their recent games, relative to an average stat line for the
game's role (:meth:`Scorer.baseline_scaled`; for legacy models the all-mean input ``x = 0``),
whose score is :func:`base_score_for`. Role and champion are context, never credited.

Three properties matter for that chart, and the legacy gradient x input port had none of
them:

* **Complete, in score units.** Attributions are integrated gradients of the win
  *probability* along the straight path from the average line to the game's stat line.
  Each game's attributions add up to ``p_game - base`` exactly (the small Riemann-sum
  residual is spread over the features in proportion to their size), so the bars of a
  player add up to ``mean(p) - base``. Gradient x input on the logit is local: real games
  sit at logits of +-3..5, where the probability barely moves, so converting it with the
  slope at the base score inflated every bar several times over.
* **Collinear inputs reported together.** The network sees the same quantity several ways
  (kills, kills per minute, kills per gold; deaths, deaths per minute, deaths per gold and
  longest time alive; ...) and spreads large, offsetting weights over them. A single member
  can therefore get a big attribution with the "wrong" sign (e.g. "deaths lift your score"
  for a player who dies more than average) while the group's sum is stable. Such groups are
  reported as one entry: :data:`COLLINEAR_GROUPS`.
* **Stable units for the API.** ``mean_attribution`` keeps the documented unit of the
  ``FeatureAttribution`` contract, logits at the base score: the probability effect divided
  by the sigmoid slope ``b(1 - b)`` there. ``mean_attribution * b * (1 - b) * 100`` (what
  the web app computes) is exactly the stat's effect in AI Score points.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import torch

from hextrack.hextrack_ai.features import (
    FEATURE_GROUPS,
    FEATURE_LABELS,
    FEATURE_SPECS,
    UNKNOWN_ROLE_SLOT,
)
from hextrack.hextrack_ai.inference import Scorer

#: Riemann steps (midpoint rule) for integrated gradients. 128 keeps the per-game residual
#: under about 1.5 score points before it is redistributed; a 30-game explanation costs a
#: few milliseconds.
IG_STEPS: Final = 128


@dataclass(frozen=True, slots=True)
class CollinearGroup:
    """Model inputs that measure one quantity, explained as a single stat.

    ``headline`` gives the entry its feature name, label, chart group and the player /
    population values shown next to the bar; ``members`` (headline included) are summed.
    """

    headline: str
    members: tuple[str, ...]


#: Near-duplicate inputs (|r| >= 0.76 on real ranked games, and longest time alive, which the
#: network uses as the counterweight of the death inputs). Members missing from a model's
#: feature set are ignored, so the participation variant needs no separate table.
COLLINEAR_GROUPS: Final[tuple[CollinearGroup, ...]] = (
    CollinearGroup("kills", ("kills", "killsPerMinute", "killsPerGold")),
    CollinearGroup(
        "deaths",
        (
            "deaths",
            "deathsPerMinute",
            "deathsPerGold",
            "longestTimeSpentLiving",
            "deathParticipation",
        ),
    ),
    CollinearGroup("assists", ("assists", "assistsPerMinute", "assistsPerGold")),
    CollinearGroup("damagePerMinute", ("damagePerMinute", "damagePerGold")),
    CollinearGroup(
        "neutralMinionsPerMinute",
        ("neutralMinionsPerMinute", "totalAllyJungleMinionsKilledPerMinute"),
    ),
)


def display_groups(feature_names: Sequence[str]) -> list[tuple[str, tuple[str, ...]]]:
    """``(headline, members)`` for every reported stat, in model feature order.

    Every feature belongs to exactly one entry: the members of a :data:`COLLINEAR_GROUPS`
    group present in ``feature_names`` form one entry, every other feature is its own.
    """
    names = list(feature_names)
    present = set(names)
    owner: dict[str, str] = {}
    members: dict[str, tuple[str, ...]] = {}
    for group in COLLINEAR_GROUPS:
        found = tuple(m for m in group.members if m in present and m not in owner)
        if not found:
            continue
        headline = group.headline if group.headline in found else found[0]
        members[headline] = found
        for member in found:
            owner[member] = headline
    out: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for name in names:
        headline = owner.get(name, name)
        if headline in seen:
            continue
        seen.add(headline)
        out.append((headline, members.get(headline, (name,))))
    return out


def integrated_gradients(
    scorer: Scorer,
    scaled: np.ndarray,
    roles: np.ndarray | None = None,
    champions: np.ndarray | None = None,
    *,
    steps: int = IG_STEPS,
) -> np.ndarray:
    """Per-row integrated gradients of the score from the row's baseline line.

    The baseline is :meth:`Scorer.baseline_scaled` for the row's role (the training mean for
    legacy models, the role's average line for impact models); role and champion are held
    fixed along the path, so only stats get credit. Returns a matrix shaped like ``scaled``
    in score units (0..1) whose row ``i`` sums to ``score(x_i) - score(baseline_i)``
    (completeness). Gradients are taken with respect to the input only, so the shared
    model's parameters are never touched (safe under concurrent requests).
    """
    if steps < 1:
        raise ValueError("steps must be positive")
    scaled = np.asarray(scaled, dtype=np.float64)
    n, width = scaled.shape
    if n == 0:
        return np.zeros_like(scaled)
    if roles is None:
        roles = np.full(n, UNKNOWN_ROLE_SLOT, dtype=np.int64)
    if champions is None:
        champions = np.zeros(n, dtype=np.int64)
    base = scorer.baseline_scaled(roles)
    delta = scaled - base
    alphas = (torch.arange(steps, dtype=torch.float32) + 0.5) / steps
    b = torch.as_tensor(base, dtype=torch.float32)
    d = torch.as_tensor(delta, dtype=torch.float32)
    r = torch.as_tensor(roles, dtype=torch.long).repeat(steps)
    c = torch.as_tensor(champions, dtype=torch.long).repeat(steps)
    with torch.enable_grad():
        path = (b.unsqueeze(0) + alphas.view(-1, 1, 1) * d.unsqueeze(0)).reshape(-1, width)
        path.requires_grad_(True)
        scores = scorer.score_tensor(path, r, c)
        (grads,) = torch.autograd.grad(scores.sum(), path)
    mean_grads = grads.detach().reshape(steps, n, width).to(torch.float64).mean(dim=0).numpy()
    attr = np.nan_to_num(mean_grads * delta, nan=0.0, posinf=0.0, neginf=0.0)

    # Make each row add up exactly: spread the Riemann-sum residual over the features in
    # proportion to their attribution size (a zero attribution stays zero).
    target = np.nan_to_num(
        scorer.scores_from_scaled(scaled, roles, champions)
        - scorer.scores_from_scaled(base, roles, champions)
    )
    residual = target - attr.sum(axis=1)
    weights = np.abs(attr)
    totals = weights.sum(axis=1, keepdims=True)
    share = np.divide(weights, totals, out=np.zeros_like(weights), where=totals > 0)
    attr += residual[:, None] * share
    return np.nan_to_num(attr, nan=0.0, posinf=0.0, neginf=0.0)


def _finite(value: float) -> float:
    return float(value) if math.isfinite(value) else 0.0


def _slope(base: float | None) -> float:
    """``b(1 - b)`` at the base score (the unit conversion of ``mean_attribution``).

    Falls back to 0.5, exactly like the web app does when ``base_score`` is null.
    """
    b = base
    if b is None or not 0.0 < b < 1.0:
        b = 0.5
    return max(b * (1.0 - b), 1e-12)


def explain_player(
    scorer: Scorer,
    durations: Sequence[int | float],
    rows: Sequence[Mapping[str, Any]],
    population_means: Mapping[str, float] | None,
) -> list[dict[str, Any]]:
    """Average effect of each stat on the AI Score across ``rows`` (one player's matches).

    Each dict has exactly the ``FeatureAttribution`` API fields: feature, label, group
    (of the entry's headline feature, see :func:`display_groups`), mean_attribution
    (signed, logits at the base score, see the module docstring), mean_abs_attribution
    (mean per-game magnitude, same unit), player_value (mean raw value of the headline
    feature) and population_value (from ``population_means`` or None). The
    mean_attributions add up to ``(mean(p) - base) / (base * (1 - base))``, where ``base`` is
    :func:`base_score_for` the same rows. Sorted by mean_abs_attribution descending. Returns
    ``[]`` when ``rows`` is empty.
    """
    if not rows:
        return []
    raw = scorer.features(durations, rows)
    scaled = scorer.scale(raw)
    roles, champions = scorer.context(rows)
    base = _base_for_context(scorer, roles, champions)
    effects = integrated_gradients(scorer, scaled, roles, champions) / _slope(base)
    player_means = raw.mean(axis=0)
    index = {name: j for j, name in enumerate(scorer.feature_names)}

    result: list[dict[str, Any]] = []
    for headline, members in display_groups(scorer.feature_names):
        per_game = effects[:, [index[m] for m in members]].sum(axis=1)
        spec = FEATURE_SPECS.get(headline)
        population: float | None = None
        if population_means is not None:
            value = population_means.get(headline)
            if value is not None and math.isfinite(float(value)):
                population = float(value)
        result.append(
            {
                "feature": headline,
                "label": FEATURE_LABELS.get(headline, spec.label if spec else headline),
                "group": FEATURE_GROUPS.get(headline, spec.group if spec else "combat"),
                "mean_attribution": _finite(float(per_game.mean())),
                "mean_abs_attribution": _finite(float(np.abs(per_game).mean())),
                "player_value": _finite(float(player_means[index[headline]])),
                "population_value": population,
            }
        )
    result.sort(key=lambda item: (-item["mean_abs_attribution"], item["feature"]))
    return result


def base_score(scorer: Scorer) -> float | None:
    """Score of the average stat line (see :meth:`Scorer.base_probability`), or None."""
    try:
        return scorer.base_probability()
    except (ValueError, RuntimeError):
        return None


def _base_for_context(scorer: Scorer, roles: np.ndarray, champions: np.ndarray) -> float | None:
    try:
        value = float(np.mean(scorer.base_scores(roles, champions)))
    except (ValueError, RuntimeError):
        return None
    return value if math.isfinite(value) else None


def base_score_for(scorer: Scorer, rows: Sequence[Mapping[str, Any]]) -> float | None:
    """Where :func:`explain_player` starts for ``rows``: the mean score of an average line in
    each row's role and champion (for legacy models the same as :func:`base_score`)."""
    if not rows:
        return base_score(scorer)
    roles, champions = scorer.context(rows)
    return _base_for_context(scorer, roles, champions)
