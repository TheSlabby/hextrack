"""Training from Postgres (owner: B3). Splits by match_id; scaler fit on train only.

Port of the legacy ``hextrack-ai/train.py`` with these changes:

* data comes from ``match_participants`` of scorable matches (CLASSIC, completed, no
  remakes) instead of LPBot's SQLite file;
* the train/validation split is by ``match_id`` (all 10 participants of a match land on
  the same side; the legacy row-level split leaked each game's teammates and opponents
  into validation) with an 80/20 ratio;
* the kept checkpoint is the epoch with the best validation log loss (legacy: accuracy),
  and accuracy / ROC AUC / log loss are reported;
* artifacts go to a versioned directory and ``train_curve.png`` is written with the Agg
  backend instead of ``plt.show()``.
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import math
import os
import shutil
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import joblib
import numpy as np
import numpy.typing as npt
import sklearn
import torch
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from torch import nn

from hextrack.config import Settings
from hextrack.db.engine import make_sync_engine, make_sync_session_factory
from hextrack.db.models import AiModel, Match, MatchParticipant
from hextrack.hextrack_ai import registry
from hextrack.hextrack_ai.features import FEATURE_NAMES, FEATURE_SET
from hextrack.hextrack_ai.inference import (
    CURVE_FILE,
    META_FILE,
    MODEL_FILE,
    SCALER_FILE,
)
from hextrack.hextrack_ai.model import DEFAULT_DROPOUT, WinPredictionNet, describe_architecture

logger = logging.getLogger(__name__)

#: Refuse to train on fewer participant rows than this (20 full matches).
MIN_TRAIN_ROWS: Final = 200
DEFAULT_SEED: Final = 41
VAL_FRACTION: Final = 0.2
BATCH_SIZE: Final = 64
LEARNING_RATE: Final = 1e-3
#: Match ids created by ``hextrack seed-demo`` start with this prefix.
DEMO_MATCH_PREFIX: Final = "DEMO_"
VERSION_FORMAT: Final = "%Y%m%d-%H%M%S"

FloatArray = npt.NDArray[np.float64]


@dataclass(slots=True)
class TrainReport:
    version: str
    model_dir: Path
    n_matches: int
    n_rows: int
    n_train: int
    n_val: int
    epochs: int
    val_auc: float
    val_accuracy: float
    val_loss: float
    activated: bool
    curve_path: Path | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    #: Participant rows re-scored with the new model after activation (None: not rescored).
    rescored_rows: int | None = None


class NotEnoughData(Exception):
    """Too few scorable matches to train."""


@dataclass(slots=True)
class TrainingData:
    """Scorable participant rows as arrays (one entry per participant)."""

    match_ids: npt.NDArray[np.str_]
    labels: FloatArray
    features: FloatArray
    game_starts: list[datetime]
    #: patch -> number of matches.
    patches: dict[str, int]

    @property
    def n_rows(self) -> int:
        return int(self.labels.shape[0])

    @property
    def n_matches(self) -> int:
        return int(np.unique(self.match_ids).shape[0])


@dataclass(slots=True)
class EpochStats:
    epoch: int
    train_loss: float
    val_loss: float
    val_accuracy: float
    val_auc: float | None


# --- data ----------------------------------------------------------------------------------


def load_training_data(
    engine: Engine,
    *,
    since: datetime | None,
    queues: Sequence[int],
    feature_names: Sequence[str] = FEATURE_NAMES,
) -> TrainingData:
    """Participants of scorable matches in ``queues`` (and on/after ``since``)."""
    stmt = (
        select(
            MatchParticipant.match_id,
            MatchParticipant.win,
            Match.game_duration,
            Match.game_start,
            Match.patch,
            *registry.participant_feature_columns(feature_names),
        )
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(registry.scorable_match_clause(), Match.queue_id.in_(list(queues)))
        .order_by(MatchParticipant.match_id, MatchParticipant.participant_id)
    )
    if since is not None:
        stmt = stmt.where(Match.game_start >= since)
    with engine.connect() as conn:
        rows = conn.execute(stmt).all()

    match_ids = np.array([row.match_id for row in rows], dtype=np.str_)
    labels = np.fromiter((1.0 if row.win else 0.0 for row in rows), np.float64, len(rows))
    features = registry.feature_matrix_from_result_rows(rows, feature_names)
    starts: dict[str, datetime] = {}
    patches: dict[str, str] = {}
    for row in rows:
        starts.setdefault(row.match_id, row.game_start)
        patches.setdefault(row.match_id, row.patch)
    return TrainingData(
        match_ids=match_ids,
        labels=labels,
        features=features,
        game_starts=sorted(starts.values()),
        patches=dict(sorted(Counter(patches.values()).items())),
    )


def group_split(
    match_ids: npt.NDArray[np.str_], *, val_fraction: float, seed: int
) -> tuple[npt.NDArray[np.bool_], int, int]:
    """Boolean validation mask over rows, holding out ``val_fraction`` of the matches.
    Returns ``(val_mask, n_train_matches, n_val_matches)``."""
    unique = np.unique(match_ids)
    n_val = max(1, int(round(unique.shape[0] * val_fraction)))
    if unique.shape[0] - n_val < 1:
        raise NotEnoughData(f"need at least 2 matches to split, found {unique.shape[0]}")
    rng = np.random.default_rng(seed)
    val_ids = unique[rng.permutation(unique.shape[0])[:n_val]]
    return np.isin(match_ids, val_ids), int(unique.shape[0] - n_val), n_val


# --- metrics -------------------------------------------------------------------------------


def _auc(labels: FloatArray, probs: FloatArray) -> float | None:
    if np.unique(labels).shape[0] < 2:
        return None
    return float(roc_auc_score(labels, probs))


def _log_loss(labels: FloatArray, probs: FloatArray) -> float:
    p = np.clip(probs, 1e-7, 1 - 1e-7)
    return float(-np.mean(labels * np.log(p) + (1 - labels) * np.log(1 - p)))


def _evaluate(model: WinPredictionNet, x: torch.Tensor, labels: FloatArray) -> dict[str, Any]:
    model.eval()
    with torch.inference_mode():
        logits = model(x).reshape(-1).to(torch.float64).numpy()
    probs = 0.5 * (1.0 + np.tanh(0.5 * logits))
    return {
        "loss": _log_loss(labels, probs),
        "accuracy": float(np.mean((logits > 0.0) == (labels > 0.5))),
        "auc": _auc(labels, probs),
    }


def _fit(
    x_train: torch.Tensor,
    y_train: torch.Tensor,
    x_val: torch.Tensor,
    y_val: FloatArray,
    *,
    epochs: int,
    batch_size: int,
    lr: float,
    seed: int,
) -> tuple[WinPredictionNet, list[EpochStats], int]:
    """Train and return the best-validation-log-loss model, the history and best epoch."""
    n_train = x_train.shape[0]
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = WinPredictionNet(x_train.shape[1])
        generator = torch.Generator().manual_seed(seed)
        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=lr)

        history: list[EpochStats] = []
        best_loss = math.inf
        best_epoch = 0
        best_state: dict[str, torch.Tensor] = copy.deepcopy(model.state_dict())
        log_every = max(1, epochs // 10)
        for epoch in range(1, epochs + 1):
            model.train()
            order = torch.randperm(n_train, generator=generator)
            running = 0.0
            for start in range(0, n_train, batch_size):
                idx = order[start : start + batch_size]
                optimizer.zero_grad(set_to_none=True)
                loss = criterion(model(x_train[idx]), y_train[idx])
                loss.backward()
                optimizer.step()
                running += float(loss.item()) * idx.shape[0]
            train_loss = running / n_train
            val = _evaluate(model, x_val, y_val)
            history.append(EpochStats(epoch, train_loss, val["loss"], val["accuracy"], val["auc"]))
            if val["loss"] < best_loss:
                best_loss = val["loss"]
                best_epoch = epoch
                best_state = copy.deepcopy(model.state_dict())
            if epoch % log_every == 0 or epoch == epochs:
                auc = val["auc"]
                logger.info(
                    "epoch %d/%d  train loss %.4f  val loss %.4f  val acc %.2f%%  val AUC %s",
                    epoch,
                    epochs,
                    train_loss,
                    val["loss"],
                    100 * val["accuracy"],
                    f"{auc:.4f}" if auc is not None else "n/a",
                )
    model.load_state_dict(best_state)
    model.eval()
    return model, history, best_epoch


# --- artifacts -----------------------------------------------------------------------------

# Chart colors (validated reference palette, light surface): series 1 blue, series 2 orange.
_SURFACE = "#fcfcfb"
_TEXT = "#0b0b0b"
_TEXT_MUTED = "#52514e"
_GRID = "#e4e3de"
_SERIES = ("#2a78d6", "#eb6834")


def plot_training_curve(history: Sequence[EpochStats], path: Path, *, best_epoch: int) -> None:
    """Two panels (never a dual axis): train/validation log loss, and validation
    accuracy / AUC. Rendered with the Agg canvas; nothing is shown on screen."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    epochs = [h.epoch for h in history]
    fig = Figure(figsize=(11, 4.2), dpi=120, facecolor=_SURFACE)
    FigureCanvasAgg(fig)
    loss_ax, metric_ax = fig.subplots(1, 2)
    panels: list[tuple[Any, str, list[tuple[str, list[float | None]]]]] = [
        (
            loss_ax,
            "Log loss",
            [
                ("Train", [h.train_loss for h in history]),
                ("Validation", [h.val_loss for h in history]),
            ],
        ),
        (
            metric_ax,
            "Validation accuracy and AUC",
            [
                ("Accuracy", [h.val_accuracy for h in history]),
                ("ROC AUC", [h.val_auc for h in history]),
            ],
        ),
    ]
    for ax, title, series in panels:
        ax.set_facecolor(_SURFACE)
        for (label, values), color in zip(series, _SERIES, strict=True):
            ys = [math.nan if v is None else v for v in values]
            ax.plot(
                epochs,
                ys,
                color=color,
                linewidth=1.6,
                label=label,
                marker="o" if len(epochs) == 1 else None,
            )
        ax.axvline(
            best_epoch,
            color=_TEXT_MUTED,
            linewidth=1.0,
            linestyle=(0, (3, 3)),
            label=f"Kept checkpoint (epoch {best_epoch})",
        )
        ax.set_title(title, color=_TEXT, fontsize=11, loc="left")
        ax.set_xlabel("Epoch", color=_TEXT_MUTED, fontsize=9)
        ax.tick_params(colors=_TEXT_MUTED, labelsize=8, length=0)
        ax.grid(True, color=_GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(_GRID)
        legend = ax.legend(
            fontsize=9, loc="best", facecolor=_SURFACE, edgecolor="none", framealpha=1.0
        )
        for text in legend.get_texts():
            text.set_color(_TEXT)
    metric_ax.axhline(0.5, color=_GRID, linewidth=1.0)
    fig.tight_layout()
    fig.savefig(path, facecolor=_SURFACE)


def save_artifacts(
    version_dir: Path,
    *,
    model: WinPredictionNet,
    scaler: StandardScaler,
    meta: dict[str, Any],
    history: Sequence[EpochStats] | None = None,
    best_epoch: int | None = None,
) -> Path | None:
    """Write model.pth, scaler.pkl, meta.json (and train_curve.png when ``history`` is
    given) into ``version_dir`` atomically: files go to a hidden sibling directory that is
    renamed into place, so a crash never leaves a half-written version. Returns the curve
    path (None when not written). ``version_dir`` must not exist yet."""
    if version_dir.exists():
        raise FileExistsError(f"{version_dir} already exists")
    parent = version_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".tmp-{version_dir.name}-{uuid.uuid4().hex[:8]}"
    tmp.mkdir()
    curve: Path | None = None
    try:
        torch.save(model.state_dict(), tmp / MODEL_FILE)
        joblib.dump(scaler, tmp / SCALER_FILE)
        (tmp / META_FILE).write_text(
            json.dumps(meta, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        if history:
            try:
                plot_training_curve(history, tmp / CURVE_FILE, best_epoch=best_epoch or 1)
                curve = version_dir / CURVE_FILE
            except Exception:  # a failed chart must not lose a trained model
                logger.exception("could not write %s", CURVE_FILE)
        os.replace(tmp, version_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return curve


def _new_version(model_dir: Path, session: Session, trained_at: datetime) -> str:
    base = trained_at.strftime(VERSION_FORMAT)
    version, n = base, 1
    while (model_dir / version).exists() or session.get(AiModel, version) is not None:
        n += 1
        version = f"{base}-{n}"
    return version


def _json_float(value: float | None) -> float | None:
    return None if value is None or not math.isfinite(value) else round(float(value), 6)


# --- entry point ---------------------------------------------------------------------------


def train(
    settings: Settings,
    *,
    since: datetime | None = None,
    queues: Sequence[int] = (420, 440),
    epochs: int = 100,
    activate: bool = True,
    rescore: bool = True,
    seed: int = DEFAULT_SEED,
    batch_size: int = BATCH_SIZE,
    learning_rate: float = LEARNING_RATE,
    val_fraction: float = VAL_FRACTION,
    min_rows: int = MIN_TRAIN_ROWS,
) -> TrainReport:
    """Train on scorable matches (optionally since ``since``) in ``queues``; write
    model.pth, scaler.pkl, meta.json, train_curve.png into a versioned directory under
    ``settings.model_dir``; insert an ``ai_models`` row; when ``activate``, make it the
    active model and re-score the stored games with it unless ``rescore`` is off (see
    :func:`hextrack.hextrack_ai.registry.activate`; averages and trends only count games
    scored by the active model, so a new model without a rescore empties the AI Score UI).

    Raises :class:`NotEnoughData` below ``min_rows`` participant rows.
    """
    queue_list = sorted({int(q) for q in queues})
    if not queue_list:
        raise ValueError("at least one queue id is required")
    if epochs < 1:
        raise ValueError("epochs must be at least 1")
    if not 0.0 < val_fraction < 1.0:
        raise ValueError("val_fraction must be between 0 and 1")
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)

    engine = make_sync_engine(settings)
    try:
        data = load_training_data(engine, since=since, queues=queue_list)
        scope = f"queues {','.join(map(str, queue_list))}" + (
            f" since {since.date().isoformat()}" if since else ""
        )
        if data.n_rows < min_rows:
            raise NotEnoughData(
                f"need at least {min_rows} scorable participant rows to train, found "
                f"{data.n_rows} ({data.n_matches} matches) in {scope}. Ingest more matches "
                "(hextrack worker / import-legacy / seed-demo) and try again."
            )
        if np.unique(data.labels).shape[0] < 2:
            raise NotEnoughData("training data contains only wins or only losses")

        val_mask, n_train_matches, n_val_matches = group_split(
            data.match_ids, val_fraction=val_fraction, seed=seed
        )
        train_mask = ~val_mask
        y_train, y_val = data.labels[train_mask], data.labels[val_mask]
        if np.unique(y_train).shape[0] < 2:
            raise NotEnoughData("the training split contains only wins or only losses")

        scaler = StandardScaler()
        x_train = scaler.fit_transform(data.features[train_mask])
        x_val = scaler.transform(data.features[val_mask])
        logger.info(
            "training on %d rows (%d matches), validating on %d rows (%d matches), %s",
            x_train.shape[0],
            n_train_matches,
            x_val.shape[0],
            n_val_matches,
            scope,
        )
        xt = torch.as_tensor(x_train, dtype=torch.float32)
        xv = torch.as_tensor(x_val, dtype=torch.float32)
        model, history, best_epoch = _fit(
            xt,
            torch.as_tensor(y_train, dtype=torch.float32).reshape(-1, 1),
            xv,
            y_val,
            epochs=epochs,
            batch_size=batch_size,
            lr=learning_rate,
            seed=seed,
        )
        val = _evaluate(model, xv, y_val)
        train_eval = _evaluate(model, xt, y_train)
        baseline = _log_loss(y_val, np.full_like(y_val, float(np.mean(y_train))))

        trained_at = datetime.now(UTC).replace(microsecond=0)
        factory = make_sync_session_factory(engine)
        with factory() as session:
            version = _new_version(settings.model_dir, session, trained_at)
        version_dir = settings.model_dir / version

        metrics: dict[str, Any] = {
            "val_auc": _json_float(val["auc"]),
            "val_accuracy": _json_float(val["accuracy"]),
            "val_loss": _json_float(val["loss"]),
            "train_auc": _json_float(train_eval["auc"]),
            "train_accuracy": _json_float(train_eval["accuracy"]),
            "train_loss": _json_float(train_eval["loss"]),
            "baseline_val_loss": _json_float(baseline),
            "best_epoch": best_epoch,
            "epochs": epochs,
            "n_train": int(x_train.shape[0]),
            "n_val": int(x_val.shape[0]),
            "n_train_matches": n_train_matches,
            "n_val_matches": n_val_matches,
        }
        unique_ids = np.unique(data.match_ids)
        demo_matches = int(np.char.startswith(unique_ids, DEMO_MATCH_PREFIX).sum())
        meta: dict[str, Any] = {
            "version": version,
            "feature_set": FEATURE_SET,
            "feature_names": list(FEATURE_NAMES),
            "n_features": len(FEATURE_NAMES),
            "architecture": describe_architecture(len(FEATURE_NAMES), DEFAULT_DROPOUT),
            "n_train": int(x_train.shape[0]),
            "n_val": int(x_val.shape[0]),
            "metrics": metrics,
            "trained_at": trained_at.isoformat(),
            "hyperparameters": {
                "epochs": epochs,
                "batch_size": batch_size,
                "learning_rate": learning_rate,
                "optimizer": "adam",
                "loss": "bce_with_logits",
                "val_fraction": val_fraction,
                "split": "group_by_match_id",
                "checkpoint": "best_val_log_loss",
                "seed": seed,
            },
            "data": {
                "n_rows": data.n_rows,
                "n_matches": data.n_matches,
                "queues": queue_list,
                "since": since.isoformat() if since else None,
                "first_game_start": data.game_starts[0].isoformat(),
                "last_game_start": data.game_starts[-1].isoformat(),
                "win_rate": _json_float(float(np.mean(data.labels))),
                "patches": data.patches,
                "demo_matches": demo_matches,
                "demo_only": demo_matches == data.n_matches,
            },
            "scaler": {
                "mean": [_json_float(float(v)) for v in scaler.mean_],
                "scale": [_json_float(float(v)) for v in scaler.scale_],
            },
            "versions": {
                "torch": torch.__version__,
                "scikit_learn": sklearn.__version__,
                "numpy": np.__version__,
            },
        }
        curve = save_artifacts(
            version_dir,
            model=model,
            scaler=scaler,
            meta=meta,
            history=history,
            best_epoch=best_epoch,
        )
        try:
            with factory() as session, session.begin():
                session.add(
                    AiModel(
                        version=version,
                        feature_names=list(FEATURE_NAMES),
                        metrics=metrics,
                        trained_at=trained_at,
                        is_active=False,
                    )
                )
        except BaseException:
            with contextlib.suppress(OSError):
                shutil.rmtree(version_dir)
            raise
    finally:
        engine.dispose()

    logger.info(
        "trained model %s: val AUC %s, val accuracy %.2f%%, val log loss %.4f (best epoch %d)",
        version,
        f"{val['auc']:.4f}" if val["auc"] is not None else "n/a",
        100 * val["accuracy"],
        val["loss"],
        best_epoch,
    )
    if demo_matches:
        logger.warning(
            "%d of %d training matches are synthetic demo data (%s*)",
            demo_matches,
            data.n_matches,
            DEMO_MATCH_PREFIX,
        )
    activated = False
    rescored_rows: int | None = None
    if activate:
        info = registry.activate(settings, version, rescore_stored=rescore)
        activated = True
        rescored_rows = info.rescored_rows
        if rescored_rows is not None:
            logger.info(
                "re-scored %d stored participant rows with model %s", rescored_rows, version
            )
        else:
            logger.warning(
                "model %s is active but the stored games still carry the previous model's "
                "scores; run `hextrack model rescore` or AI averages and trends stay empty",
                version,
            )
    else:
        logger.info(
            "model %s was not activated; `hextrack model activate %s` switches to it and "
            "re-scores the stored games",
            version,
            version,
        )

    return TrainReport(
        version=version,
        model_dir=version_dir,
        n_matches=data.n_matches,
        n_rows=data.n_rows,
        n_train=int(x_train.shape[0]),
        n_val=int(x_val.shape[0]),
        epochs=epochs,
        val_auc=float(val["auc"]) if val["auc"] is not None else math.nan,
        val_accuracy=float(val["accuracy"]),
        val_loss=float(val["loss"]),
        activated=activated,
        curve_path=curve,
        metrics=metrics,
        rescored_rows=rescored_rows,
    )
