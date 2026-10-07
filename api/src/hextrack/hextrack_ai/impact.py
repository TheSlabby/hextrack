"""Training pieces of the impact model (the current Hex Score).

Why this model: the legacy one learned P(win | one player's stat line). A stat line carries a
lot of its team's result (winners take towers and live longer), so its scores sat near 0 or
100 and mostly restated the result. Here the network gives each player an *impact* from
their own line, role and champion only (no team or opponent totals: those would leak the
result straight back in), and it is trained on whole games: the five impacts of a team minus
the five of the other team are the log-odds that the team won. Credit for a won game is
shared by the lines that explain it, so a strong line in a loss still scores well and a
passenger in a win doesn't.

The Hex Score shown is that impact, minus its champion's average impact (a pick isn't a
performance), as a percentile among training games in the same role: 50 is a typical game,
80 is better than 80% of games in that role.
"""

from __future__ import annotations

import copy
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import torch
from sklearn.metrics import roc_auc_score
from torch import nn

from hextrack.hextrack_ai.features import ROLE_SLOTS, UNKNOWN_ROLE_SLOT
from hextrack.hextrack_ai.model import HexImpactNet

logger = logging.getLogger(__name__)

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

#: Champions with fewer training rows share the "unknown champion" embedding (slot 0).
MIN_CHAMPION_ROWS: Final = 30
#: A champion's offset is shrunk toward 0 as if it had this many extra average games.
CHAMPION_OFFSET_PRIOR: Final = 50.0
#: Quantile levels stored in the score map (0, 0.5%, ..., 100%).
SCORE_LEVELS: Final[int] = 201
#: Players per team; games that aren't a complete 5v5 are not used for training.
TEAM_SIZE: Final = 5


def champion_vocabulary(
    champion_ids: npt.ArrayLike, min_rows: int = MIN_CHAMPION_ROWS
) -> list[int]:
    """Champion ids with at least ``min_rows`` rows, sorted; slot ``i + 1`` is the i-th."""
    ids, counts = np.unique(np.asarray(champion_ids, dtype=np.int64), return_counts=True)
    return [int(c) for c, n in zip(ids, counts, strict=True) if n >= min_rows and c > 0]


def champion_slots(champion_ids: npt.ArrayLike, vocabulary: Sequence[int]) -> IntArray:
    lookup = {c: i + 1 for i, c in enumerate(vocabulary)}
    ids = np.asarray(champion_ids, dtype=np.int64).reshape(-1)
    return np.fromiter((lookup.get(int(c), 0) for c in ids), dtype=np.int64, count=ids.shape[0])


def game_rows(
    match_ids: npt.NDArray[np.int64],
    team_ids: npt.NDArray[Any],
    labels: FloatArray,
    mask: npt.NDArray[np.bool_],
) -> tuple[IntArray, FloatArray]:
    """Complete 5v5 games among the ``mask`` rows: ``(rows, y)`` where ``rows[g]`` holds the
    row indices of game ``g`` (team 100's five first) and ``y[g]`` is 1 when team 100 won.
    Games with another shape or inconsistent results are left out."""
    idx = np.flatnonzero(mask)
    if idx.shape[0] == 0:
        return np.zeros((0, 2 * TEAM_SIZE), np.int64), np.zeros(0, np.float64)
    order = idx[np.lexsort((team_ids[idx], match_ids[idx]))]
    codes = match_ids[order]
    starts = np.flatnonzero(np.r_[True, codes[1:] != codes[:-1]])
    sizes = np.diff(np.r_[starts, codes.shape[0]])
    full = starts[sizes == 2 * TEAM_SIZE]
    rows = order[full[:, None] + np.arange(2 * TEAM_SIZE)]
    teams = team_ids[rows]
    won = labels[rows]
    ok = (
        (teams[:, :TEAM_SIZE] == 100).all(axis=1)
        & (teams[:, TEAM_SIZE:] == 200).all(axis=1)
        & (won[:, :TEAM_SIZE] == won[:, :1]).all(axis=1)
        & (won[:, TEAM_SIZE:] == 1.0 - won[:, :1]).all(axis=1)
    )
    return rows[ok], won[ok, 0].astype(np.float64)


@dataclass(slots=True)
class ImpactEpoch:
    epoch: int
    train_loss: float
    val_loss: float
    val_accuracy: float
    val_auc: float | None


_SIGN: Final = torch.tensor([1.0] * TEAM_SIZE + [-1.0] * TEAM_SIZE)


def _team_logits(
    model: HexImpactNet, side: torch.Tensor, x: torch.Tensor, r: torch.Tensor, c: torch.Tensor
) -> torch.Tensor:
    return (model(x, r, c) * _SIGN).sum(dim=-1) + side


def _auc(labels: FloatArray, scores: FloatArray) -> float | None:
    if np.unique(labels).shape[0] < 2:
        return None
    return float(roc_auc_score(labels, scores))


def _log_loss(labels: FloatArray, probs: FloatArray) -> float:
    p = np.clip(probs, 1e-7, 1 - 1e-7)
    return float(-np.mean(labels * np.log(p) + (1 - labels) * np.log(1 - p)))


def _game_eval(
    model: HexImpactNet,
    side: torch.Tensor,
    x: torch.Tensor,
    r: torch.Tensor,
    c: torch.Tensor,
    y: FloatArray,
) -> dict[str, Any]:
    model.eval()
    with torch.inference_mode():
        logits = _team_logits(model, side, x, r, c).to(torch.float64).numpy()
    probs = 0.5 * (1.0 + np.tanh(0.5 * logits))
    return {
        "loss": _log_loss(y, probs),
        "accuracy": float(np.mean((logits > 0) == (y > 0.5))),
        "auc": _auc(y, probs),
    }


def fit_impact(
    x_train: torch.Tensor,
    r_train: torch.Tensor,
    c_train: torch.Tensor,
    y_train: FloatArray,
    x_val: torch.Tensor,
    r_val: torch.Tensor,
    c_val: torch.Tensor,
    y_val: FloatArray,
    *,
    n_champions: int,
    epochs: int,
    batch_games: int,
    lr: float,
    seed: int,
    patience: int,
) -> tuple[HexImpactNet, float, list[ImpactEpoch], int]:
    """Train on games (``x`` shaped ``(games, 10, features)``); returns the best-validation
    model, the side bias (team 100's edge, logits), the history and the best epoch."""
    n_games = x_train.shape[0]
    yt = torch.as_tensor(y_train, dtype=torch.float32)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = HexImpactNet(x_train.shape[-1], n_champions=n_champions)
        side = nn.Parameter(torch.zeros(()))
        generator = torch.Generator().manual_seed(seed)
        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.Adam([*model.parameters(), side], lr=lr)
        history: list[ImpactEpoch] = []
        best_loss = math.inf
        best_epoch = 0
        best_state = copy.deepcopy(model.state_dict())
        best_side = 0.0
        log_every = max(1, epochs // 10)
        for epoch in range(1, epochs + 1):
            if best_epoch > 0 and epoch - best_epoch > patience:
                logger.info("no validation improvement for %d epochs; stopping", patience)
                break
            model.train()
            order = torch.randperm(n_games, generator=generator)
            running = 0.0
            for start in range(0, n_games, batch_games):
                idx = order[start : start + batch_games]
                optimizer.zero_grad(set_to_none=True)
                logits = _team_logits(model, side, x_train[idx], r_train[idx], c_train[idx])
                loss = criterion(logits, yt[idx])
                loss.backward()
                optimizer.step()
                running += float(loss.item()) * idx.shape[0]
            val = _game_eval(model, side.detach(), x_val, r_val, c_val, y_val)
            history.append(
                ImpactEpoch(epoch, running / n_games, val["loss"], val["accuracy"], val["auc"])
            )
            if val["loss"] < best_loss:
                best_loss, best_epoch = val["loss"], epoch
                best_state = copy.deepcopy(model.state_dict())
                best_side = float(side.detach())
            if epoch % log_every == 0 or epoch == epochs:
                auc = val["auc"]
                logger.info(
                    "epoch %d/%d  train loss %.4f  val loss %.4f  val acc %.2f%%  val AUC %s",
                    epoch,
                    epochs,
                    running / n_games,
                    val["loss"],
                    100 * val["accuracy"],
                    f"{auc:.4f}" if auc is not None else "n/a",
                )
    model.load_state_dict(best_state)
    model.eval()
    for param in model.parameters():
        param.requires_grad_(False)
    return model, best_side, history, best_epoch


def predict_impact(
    model: HexImpactNet,
    scaled: npt.NDArray[Any],
    roles: IntArray,
    champions: IntArray,
    *,
    rows: IntArray | None = None,
    batch: int = 65_536,
) -> FloatArray:
    """Impacts of ``rows`` (default: every row), read batch by batch so no full copy of the
    selected rows is made."""
    index = np.arange(scaled.shape[0]) if rows is None else np.asarray(rows)
    out = np.empty(index.shape[0], dtype=np.float64)
    with torch.inference_mode():
        for start in range(0, index.shape[0], batch):
            sel = index[start : start + batch]
            out[start : start + sel.shape[0]] = (
                model(
                    torch.as_tensor(scaled[sel], dtype=torch.float32),
                    torch.as_tensor(roles[sel], dtype=torch.long),
                    torch.as_tensor(champions[sel], dtype=torch.long),
                )
                .to(torch.float64)
                .numpy()
            )
    return out


def scale_float32(
    scaler: Any, features: npt.NDArray[Any], *, chunk: int = 200_000
) -> npt.NDArray[np.float32]:
    """``scaler.transform`` in chunks, straight into float32 (a float64 copy of millions of
    rows doesn't fit the training sandbox's memory cap)."""
    out = np.empty(features.shape, dtype=np.float32)
    mean = np.asarray(scaler.mean_, dtype=np.float64)
    scale = np.asarray(scaler.scale_, dtype=np.float64)
    for start in range(0, features.shape[0], chunk):
        part = np.asarray(features[start : start + chunk], dtype=np.float64)
        out[start : start + part.shape[0]] = (part - mean) / scale
    return out


def _strictly_increasing(knots: FloatArray) -> FloatArray:
    knots = np.maximum.accumulate(np.asarray(knots, dtype=np.float64))
    return knots + np.arange(knots.shape[0]) * 1e-9


def build_score_map(
    impacts: FloatArray, roles: IntArray, champions: IntArray, n_champion_slots: int
) -> dict[str, Any]:
    """``meta["score_map"]``: per-champion offsets (shrunk mean impact above the role's
    average) and, per role slot, the impact quantiles after removing them. The unknown role
    slot uses every role's games."""
    impacts = np.asarray(impacts, dtype=np.float64)
    role_mean = np.zeros(ROLE_SLOTS)
    for slot in range(ROLE_SLOTS):
        mask = roles == slot
        role_mean[slot] = impacts[mask].mean() if mask.any() else impacts.mean()
    residual = impacts - role_mean[roles]
    sums = np.bincount(champions, weights=residual, minlength=n_champion_slots)
    counts = np.bincount(champions, minlength=n_champion_slots).astype(np.float64)
    offsets = sums / (counts + CHAMPION_OFFSET_PRIOR)
    value = impacts - offsets[champions]
    levels = np.linspace(0.0, 1.0, SCORE_LEVELS)
    knots = np.empty((ROLE_SLOTS, SCORE_LEVELS))
    for slot in range(ROLE_SLOTS):
        mask = roles == slot
        if slot == UNKNOWN_ROLE_SLOT or mask.sum() < SCORE_LEVELS:
            mask = roles != UNKNOWN_ROLE_SLOT
            if not mask.any():
                mask = np.ones_like(roles, dtype=bool)
        knots[slot] = _strictly_increasing(np.quantile(value[mask], levels))
    return {
        "type": "role_quantiles",
        "levels": [round(float(v), 6) for v in levels],
        "knots": [[float(v) for v in row] for row in knots],
        "champion_offsets": [float(v) for v in offsets],
    }


def apply_score_map(
    score_map: dict[str, Any], impacts: FloatArray, roles: IntArray, champions: IntArray
) -> FloatArray:
    levels = np.asarray(score_map["levels"], dtype=np.float64)
    knots = np.asarray(score_map["knots"], dtype=np.float64)
    offsets = np.asarray(score_map["champion_offsets"], dtype=np.float64)
    value = np.asarray(impacts, dtype=np.float64) - offsets[champions]
    out = np.empty_like(value)
    for slot in np.unique(roles):
        mask = roles == slot
        out[mask] = np.interp(value[mask], knots[slot], levels)
    return out


def role_baselines(
    scaled: npt.NDArray[Any], roles: IntArray, *, rows: IntArray | None = None
) -> FloatArray:
    """``meta["baselines"]``: the mean scaled stat line per role slot over ``rows`` (default
    all), the explanation's starting point. The unknown slot is the overall mean: zeros."""
    index = np.arange(scaled.shape[0]) if rows is None else np.asarray(rows)
    width = scaled.shape[1]
    sums = np.zeros((ROLE_SLOTS, width))
    counts = np.zeros(ROLE_SLOTS)
    for start in range(0, index.shape[0], 200_000):
        sel = index[start : start + 200_000]
        r = roles[sel]
        np.add.at(sums, r, np.asarray(scaled[sel], dtype=np.float64))
        counts += np.bincount(r, minlength=ROLE_SLOTS)
    out = np.zeros((ROLE_SLOTS, width))
    for slot in range(ROLE_SLOTS):
        if slot != UNKNOWN_ROLE_SLOT and counts[slot] > 0:
            out[slot] = sums[slot] / counts[slot]
    return out


def score_metrics(
    scores: FloatArray, labels: FloatArray, match_ids: npt.NDArray[Any]
) -> dict[str, float | None]:
    """How the Hex Scores of held-out games behave (0..1 scale in, 0..100 points out):
    ``player_auc`` (score vs own result: lower = less tied to the result), mean score in
    wins / losses, and how often the best player of the losing team outscored the worst
    player of the winning team."""
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.float64)
    out: dict[str, float | None] = {"player_auc": _auc(labels, scores)}
    won = labels > 0.5
    out["mean_score_win"] = float(100 * scores[won].mean()) if won.any() else None
    out["mean_score_loss"] = float(100 * scores[~won].mean()) if (~won).any() else None
    order = np.argsort(match_ids, kind="stable")
    ids, s, w = match_ids[order], scores[order], won[order]
    starts = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]])
    best_loser = np.maximum.reduceat(np.where(w, -np.inf, s), starts)
    worst_winner = np.minimum.reduceat(np.where(w, s, np.inf), starts)
    both = np.isfinite(best_loser) & np.isfinite(worst_winner)
    out["best_loser_beats_worst_winner"] = (
        float(np.mean(best_loser[both] > worst_winner[both])) if both.any() else None
    )
    return out
