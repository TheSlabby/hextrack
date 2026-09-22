"""Per-stat attributions behind a player's AI Score (owner: B3).

What the "What drives the score" chart shows, per stat: how much it moved the player's
win probability, on average over their recent games, relative to an all-average stat line
(scaled input ``x = 0``, the training-population mean, whose score is :func:`base_score`).

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

from hextrack.hextrack_ai.features import FEATURE_GROUPS, FEATURE_LABELS, FEATURE_SPECS
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


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(logits, dtype=np.float64)))


def integrated_gradients(
    scorer: Scorer, scaled: np.ndarray, *, steps: int = IG_STEPS
) -> np.ndarray:
    """Per-row integrated gradients of the win probability from the scaled-zero baseline.

    Returns a matrix shaped like ``scaled`` in probability units whose row ``i`` sums to
    ``sigmoid(logit(x_i)) - sigmoid(logit(0))`` (completeness). Gradients are taken with
    respect to the input only, so the shared model's parameters are never touched (safe
    under concurrent requests).
    """
    if steps < 1:
        raise ValueError("steps must be positive")
    scaled = np.asarray(scaled, dtype=np.float64)
    n, width = scaled.shape
    if n == 0:
        return np.zeros_like(scaled)
    alphas = (torch.arange(steps, dtype=torch.float32) + 0.5) / steps
    x = torch.as_tensor(scaled, dtype=torch.float32)
    with torch.enable_grad():
        path = (alphas.view(-1, 1, 1) * x.unsqueeze(0)).reshape(-1, width).requires_grad_(True)
        probs = torch.sigmoid(scorer.model(path))
        (grads,) = torch.autograd.grad(probs.sum(), path)
    mean_grads = grads.detach().reshape(steps, n, width).to(torch.float64).mean(dim=0).numpy()
    attr = np.nan_to_num(mean_grads * scaled, nan=0.0, posinf=0.0, neginf=0.0)

    # Make each row add up exactly: spread the Riemann-sum residual over the features in
    # proportion to their attribution size (a zero attribution stays zero).
    logits = scorer.logits_from_scaled(np.vstack([np.zeros((1, width)), scaled]))
    probs_np = _sigmoid(logits)
    target = np.nan_to_num(probs_np[1:] - probs_np[0])
    residual = target - attr.sum(axis=1)
    weights = np.abs(attr)
    totals = weights.sum(axis=1, keepdims=True)
    share = np.divide(weights, totals, out=np.zeros_like(weights), where=totals > 0)
    attr += residual[:, None] * share
    return np.nan_to_num(attr, nan=0.0, posinf=0.0, neginf=0.0)


def _finite(value: float) -> float:
    return float(value) if math.isfinite(value) else 0.0


def _baseline_slope(scorer: Scorer) -> float:
    """``b(1 - b)`` at the base score (the unit conversion of ``mean_attribution``).

    Falls back to 0.5, exactly like the web app does when ``base_score`` is null.
    """
    b = base_score(scorer)
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
    mean_attributions add up to ``(mean(p) - base) / (base * (1 - base))``. Sorted by
    mean_abs_attribution descending. Returns ``[]`` when ``rows`` is empty.
    """
    if not rows:
        return []
    raw = scorer.features(durations, rows)
    scaled = scorer.scale(raw)
    effects = integrated_gradients(scorer, scaled) / _baseline_slope(scorer)
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
    """Model probability for an all-mean (scaled zero) input, or None if unavailable."""
    try:
        return scorer.base_probability()
    except (ValueError, RuntimeError):
        return None
