"""Loading and running the AI Score model (owner: B3).

Artifact layout under ``settings.model_dir``::

    ACTIVE                      # text file: the active version name
    <version>/model.pth         # WinPredictionNet state_dict
    <version>/scaler.pkl        # sklearn StandardScaler fit on the training split
    <version>/meta.json         # version, feature_set, feature_names, metrics, trained_at...
    <version>/train_curve.png

:meth:`Scorer.load` reads ``ACTIVE``; without it (or when it names a missing directory) it
falls back to the newest version directory. A ``model_dir`` that itself holds the three
artifact files is loaded directly. Models whose ``meta.feature_names`` differ from
:data:`~hextrack.hextrack_ai.features.FEATURE_NAMES` are refused.

Scoring runs on CPU under ``torch.inference_mode`` with one intra-op thread (the API and
worker score one match at a time; more threads only add contention).
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import joblib
import numpy as np
import numpy.typing as npt
import torch
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import NoInspectionAvailable

from hextrack.hextrack_ai.features import FEATURE_NAMES, FEATURE_SET, compute_feature_matrix
from hextrack.hextrack_ai.model import WinPredictionNet

logger = logging.getLogger(__name__)

MODEL_FILE = "model.pth"
SCALER_FILE = "scaler.pkl"
META_FILE = "meta.json"
CURVE_FILE = "train_curve.png"
#: Text file in ``model_dir`` naming the active version directory.
ACTIVE_FILE = "ACTIVE"
ARTIFACT_FILES: Final[tuple[str, ...]] = (MODEL_FILE, SCALER_FILE, META_FILE)

#: Scores are clipped to [PROB_EPS, 1 - PROB_EPS] so they stay strictly inside (0, 1).
PROB_EPS: Final = 1e-6

FloatArray = npt.NDArray[np.float64]


class ModelLoadError(Exception):
    """Artifacts exist but are inconsistent (e.g. feature names differ from FEATURE_NAMES)."""


def parse_timestamp(value: object) -> datetime | None:
    """ISO-8601 string -> tz-aware UTC datetime (naive values are taken as UTC)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def read_meta(version_dir: Path) -> dict[str, Any]:
    """Parse ``version_dir/meta.json``; raises :class:`ModelLoadError` when unreadable."""
    path = version_dir / META_FILE
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelLoadError(f"{path} is missing") from exc
    except (OSError, ValueError) as exc:
        raise ModelLoadError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(meta, dict):
        raise ModelLoadError(f"{path} must contain a JSON object")
    return meta


def is_plain_version_name(name: str) -> bool:
    """A version is a single path component: no separators, not hidden, not '.'/'..'."""
    return bool(name) and "/" not in name and "\\" not in name and not name.startswith(".")


def is_version_dir(path: Path) -> bool:
    """True when ``path`` holds every artifact file."""
    return path.is_dir() and all((path / name).is_file() for name in ARTIFACT_FILES)


def version_dirs(model_dir: Path) -> list[Path]:
    """Complete version directories under ``model_dir``, newest first (by meta
    ``trained_at``, then name). Hidden directories (in-progress training) are skipped."""
    if not model_dir.is_dir():
        return []
    found: list[tuple[datetime, str, Path]] = []
    for child in model_dir.iterdir():
        if child.name.startswith(".") or not is_version_dir(child):
            continue
        try:
            trained = parse_timestamp(read_meta(child).get("trained_at"))
        except ModelLoadError:
            trained = None
        found.append((trained or datetime.min.replace(tzinfo=UTC), child.name, child))
    found.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [path for _, _, path in found]


def read_active_version(model_dir: Path) -> str | None:
    """Contents of ``model_dir/ACTIVE`` (stripped), or None when absent or empty."""
    path = model_dir / ACTIVE_FILE
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("cannot read %s: %s", path, exc)
        return None
    return text or None


def _array(value: object, n: int, default: float) -> FloatArray:
    if value is None:
        return np.full(n, default, dtype=np.float64)
    arr = np.asarray(value, dtype=np.float64).reshape(-1)
    if arr.shape[0] != n:
        raise ModelLoadError(f"scaler has {arr.shape[0]} values, expected {n}")
    return arr


class Scorer:
    """A loaded model + scaler. Immutable after load; safe to share across requests."""

    #: Model version string, e.g. "20260921-183005".
    version: str
    #: Parsed meta.json (feature_names, metrics, trained_at, ...).
    meta: dict[str, Any]
    feature_names: list[str]
    #: Directory the artifacts were loaded from.
    path: Path
    #: The network, in eval mode. Never call ``.train()`` on it.
    model: WinPredictionNet

    def __init__(
        self,
        *,
        version: str,
        meta: dict[str, Any],
        model: WinPredictionNet,
        scaler_mean: FloatArray,
        scaler_scale: FloatArray,
        path: Path,
    ) -> None:
        self.version = version
        self.meta = meta
        self.feature_names = list(meta.get("feature_names", FEATURE_NAMES))
        self.path = path
        model.eval()
        for param in model.parameters():
            param.requires_grad_(False)
        self.model = model
        self._mean = scaler_mean.astype(np.float64)
        scale = scaler_scale.astype(np.float64)
        # StandardScaler stores 1.0 for zero-variance features; keep that guarantee.
        self._scale = np.where((scale == 0) | ~np.isfinite(scale), 1.0, scale)

    def __repr__(self) -> str:
        return f"Scorer(version={self.version!r}, n_features={self.n_features})"

    # --- loading ------------------------------------------------------------------------

    @classmethod
    def load(cls, model_dir: Path) -> Scorer | None:
        """Load the active model from ``model_dir``.

        Returns None (and logs a warning) when there are no artifacts or they cannot be
        used: missing directory, missing files, or a feature set different from
        ``FEATURE_NAMES``. Use :meth:`from_version_dir` to get the error instead.
        """
        model_dir = Path(model_dir)
        target = cls._resolve(model_dir)
        if target is None:
            return None
        try:
            scorer = cls.from_version_dir(target)
        except ModelLoadError as exc:
            logger.warning("AI model in %s not loaded: %s", target, exc)
            return None
        torch.set_num_threads(1)
        return scorer

    @staticmethod
    def _resolve(model_dir: Path) -> Path | None:
        if not model_dir.is_dir():
            logger.warning("AI model directory %s does not exist", model_dir)
            return None
        if is_version_dir(model_dir):
            return model_dir
        active = read_active_version(model_dir)
        if active is not None:
            candidate = model_dir / active
            if is_plain_version_name(active) and candidate.is_dir():
                return candidate
            logger.warning(
                "%s names version %r but %s does not exist; using the newest version",
                model_dir / ACTIVE_FILE,
                active,
                candidate,
            )
        versions = version_dirs(model_dir)
        if not versions:
            logger.warning("no AI model artifacts in %s", model_dir)
            return None
        return versions[0]

    @classmethod
    def from_version_dir(cls, version_dir: Path) -> Scorer:
        """Load one version directory. Raises :class:`ModelLoadError` on any problem."""
        version_dir = Path(version_dir)
        missing = [name for name in ARTIFACT_FILES if not (version_dir / name).is_file()]
        if missing:
            raise ModelLoadError(f"{version_dir} is missing {', '.join(missing)}")
        meta = read_meta(version_dir)

        names = meta.get("feature_names")
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise ModelLoadError("meta.json has no feature_names list")
        if tuple(names) != FEATURE_NAMES:
            raise ModelLoadError(
                f"model was trained on feature set {meta.get('feature_set')!r} "
                f"({len(names)} features); this build uses {FEATURE_SET!r} "
                f"({len(FEATURE_NAMES)} features). Retrain with `hextrack train`."
            )
        n = len(names)
        version = meta.get("version")
        if not isinstance(version, str) or not version:
            version = version_dir.name
            meta["version"] = version

        try:
            state = torch.load(version_dir / MODEL_FILE, map_location="cpu", weights_only=True)
        except Exception as exc:  # corrupt / foreign pickle
            raise ModelLoadError(f"cannot read {version_dir / MODEL_FILE}: {exc}") from exc
        model = WinPredictionNet(n)
        try:
            model.load_state_dict(state)
        except (RuntimeError, TypeError, AttributeError) as exc:
            raise ModelLoadError(
                f"{MODEL_FILE} does not match WinPredictionNet({n}): {exc}"
            ) from exc

        try:
            scaler = joblib.load(version_dir / SCALER_FILE)
        except Exception as exc:
            raise ModelLoadError(f"cannot read {version_dir / SCALER_FILE}: {exc}") from exc
        n_in = getattr(scaler, "n_features_in_", None)
        if n_in != n:
            raise ModelLoadError(f"scaler was fit on {n_in} features, expected {n}")
        mean = _array(getattr(scaler, "mean_", None), n, 0.0)
        scale = _array(getattr(scaler, "scale_", None), n, 1.0)
        if not (np.all(np.isfinite(mean)) and np.all(np.isfinite(scale))):
            raise ModelLoadError("scaler contains non-finite values")

        return cls(
            version=version,
            meta=meta,
            model=model,
            scaler_mean=mean,
            scaler_scale=scale,
            path=version_dir,
        )

    # --- metadata -------------------------------------------------------------------------

    @property
    def trained_at(self) -> datetime | None:
        """``meta["trained_at"]`` parsed as a tz-aware datetime."""
        return parse_timestamp(self.meta.get("trained_at"))

    @property
    def n_features(self) -> int:
        return len(self.feature_names)

    @property
    def metrics(self) -> dict[str, Any]:
        metrics = self.meta.get("metrics")
        return dict(metrics) if isinstance(metrics, dict) else {}

    # --- scoring --------------------------------------------------------------------------

    def features(
        self, durations_seconds: Sequence[int | float], rows: Sequence[Mapping[str, Any]]
    ) -> FloatArray:
        """Raw (unscaled) feature matrix for ``rows``."""
        return compute_feature_matrix(durations_seconds, rows, feature_names=self.feature_names)

    def scale(self, features: FloatArray) -> FloatArray:
        """Apply the training StandardScaler."""
        return (np.asarray(features, dtype=np.float64) - self._mean) / self._scale

    def logits_from_scaled(self, scaled: FloatArray) -> FloatArray:
        """Model logits (float64, shape (n,)) for already-scaled inputs."""
        if scaled.shape[0] == 0:
            return np.zeros(0, dtype=np.float64)
        with torch.inference_mode():
            out = self.model(torch.as_tensor(scaled, dtype=torch.float32))
        return out.reshape(-1).to(torch.float64).numpy()

    @staticmethod
    def probabilities(logits: FloatArray) -> FloatArray:
        """Sigmoid, clipped to [PROB_EPS, 1 - PROB_EPS]."""
        probs = 0.5 * (1.0 + np.tanh(0.5 * np.asarray(logits, dtype=np.float64)))
        return np.clip(probs, PROB_EPS, 1.0 - PROB_EPS)

    def score_rows(
        self,
        durations_seconds: Sequence[int | float],
        rows: Sequence[Mapping[str, Any]],
    ) -> np.ndarray:
        """Win probabilities in (0, 1), shape (len(rows),). ``durations_seconds[i]`` is the
        game duration of ``rows[i]``."""
        scaled = self.scale(self.features(durations_seconds, rows))
        return self.probabilities(self.logits_from_scaled(scaled))

    def score_match(
        self, game_duration_seconds: int, participants: Sequence[Mapping[str, Any]]
    ) -> dict[str, float]:
        """Score every participant of one match; returns ``{puuid: probability}``."""
        if not participants:
            return {}
        puuids: list[str] = []
        for i, p in enumerate(participants):
            puuid = p.get("puuid")
            if not isinstance(puuid, str) or not puuid:
                raise ValueError(f"participant {i} has no puuid")
            puuids.append(puuid)
        if len(set(puuids)) != len(puuids):
            raise ValueError("participants contain duplicate puuids")
        probs = self.score_rows([game_duration_seconds] * len(participants), participants)
        return {puuid: float(prob) for puuid, prob in zip(puuids, probs, strict=True)}

    def base_probability(self) -> float:
        """Probability for the all-mean (scaled zero) input."""
        logit = self.logits_from_scaled(np.zeros((1, self.n_features), dtype=np.float64))[0]
        if not math.isfinite(logit):
            raise ValueError("model produced a non-finite logit")
        return float(self.probabilities(np.array([logit]))[0])


def participant_to_dict(orm_row: Any) -> dict[str, Any]:
    """Convert a ``MatchParticipant`` ORM row to the column dict the feature code reads.

    Also accepts SQLAlchemy ``Row`` objects (``row._mapping``) and plain mappings. Only
    column attributes are read, so no relationship is lazy-loaded.
    """
    if isinstance(orm_row, Mapping):
        return dict(orm_row)
    mapping = getattr(orm_row, "_mapping", None)
    if isinstance(mapping, Mapping):
        return {str(key): value for key, value in mapping.items()}
    try:
        state = sa_inspect(orm_row)
    except NoInspectionAvailable as exc:
        raise TypeError(f"cannot convert {type(orm_row).__name__} to a participant dict") from exc
    mapper = getattr(state, "mapper", None)
    if mapper is None:
        raise TypeError(f"{type(orm_row).__name__} is not an ORM instance")
    return {attr.key: getattr(orm_row, attr.key) for attr in mapper.column_attrs}
