"""Loading and running the AI Score model (owner: B3).

Artifact layout under ``settings.model_dir``::

    ACTIVE                      # text file: the active version name
    <version>/model.pth         # HexImpactNet (or legacy WinPredictionNet) state_dict
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

from hextrack.hextrack_ai.features import (
    FEATURE_NAMES,
    FEATURE_SET,
    ROLE_SLOTS,
    ROLES,
    UNKNOWN_ROLE_SLOT,
    compute_feature_matrix,
    role_slots,
)
from hextrack.hextrack_ai.model import IMPACT_HIDDEN, HexImpactNet, WinPredictionNet

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


#: ``meta["kind"]`` of the current model: impact (see :mod:`hextrack.hextrack_ai.model`),
#: shown as a percentile within the player's role.
KIND_IMPACT: Final = "impact"
#: ``meta["kind"]`` of older models (or none): "chance this stat line is on the winning team".
KIND_WIN_PROBABILITY: Final = "win_probability"
KINDS: Final = frozenset({KIND_IMPACT, KIND_WIN_PROBABILITY})


def _float_matrix(value: object, shape: tuple[int, ...], name: str) -> FloatArray:
    try:
        arr = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ModelLoadError(f"meta.json {name} is not numeric: {exc}") from exc
    if arr.shape != shape:
        raise ModelLoadError(f"meta.json {name} has shape {arr.shape}, expected {shape}")
    if not np.all(np.isfinite(arr)):
        raise ModelLoadError(f"meta.json {name} contains non-finite values")
    return arr


class _ScoreMap:
    """Impact -> Hex Score (0..1): the impact, minus its champion's average, as a percentile
    of the training games in the same role (piecewise linear between stored quantiles)."""

    def __init__(self, meta: dict[str, Any], n_champion_slots: int) -> None:
        raw = meta.get("score_map")
        if not isinstance(raw, dict):
            raise ModelLoadError("meta.json has no score_map")
        levels = np.asarray(raw.get("levels"), dtype=np.float64).reshape(-1)
        if levels.shape[0] < 2 or not np.all(np.diff(levels) > 0):
            raise ModelLoadError("score_map.levels must be increasing")
        knots = _float_matrix(raw.get("knots"), (ROLE_SLOTS, levels.shape[0]), "score_map.knots")
        if not np.all(np.diff(knots, axis=1) > 0):
            raise ModelLoadError("score_map.knots must increase along every role")
        offsets = _float_matrix(
            raw.get("champion_offsets", [0.0] * n_champion_slots),
            (n_champion_slots,),
            "score_map.champion_offsets",
        )
        self.levels = levels
        self.knots = knots
        self.offsets = offsets
        self._levels_t = torch.as_tensor(levels, dtype=torch.float32)
        self._knots_t = torch.as_tensor(knots, dtype=torch.float32)
        self._offsets_t = torch.as_tensor(offsets, dtype=torch.float32)

    def __call__(
        self, impact: FloatArray, roles: npt.NDArray[np.int64], champions: npt.NDArray[np.int64]
    ) -> FloatArray:
        value = np.asarray(impact, dtype=np.float64) - self.offsets[champions]
        out = np.empty_like(value)
        for slot in np.unique(roles):
            mask = roles == slot
            out[mask] = np.interp(value[mask], self.knots[slot], self.levels)
        return out

    def tensor(
        self, impact: torch.Tensor, roles: torch.Tensor, champions: torch.Tensor
    ) -> torch.Tensor:
        """Differentiable twin of ``__call__`` (same interpolation, clamped at the ends)."""
        value = impact - self._offsets_t[champions]
        knots = self._knots_t[roles]
        last = knots.shape[1] - 1
        upper = torch.searchsorted(knots, value.unsqueeze(-1).contiguous()).squeeze(-1)
        upper = upper.clamp(1, last)
        x0 = knots.gather(1, (upper - 1).unsqueeze(-1)).squeeze(-1)
        x1 = knots.gather(1, upper.unsqueeze(-1)).squeeze(-1)
        t = ((value - x0) / (x1 - x0).clamp_min(1e-12)).clamp(0.0, 1.0)
        y0 = self._levels_t[upper - 1]
        y1 = self._levels_t[upper]
        return y0 + t * (y1 - y0)


class Scorer:
    """A loaded model + scaler. Immutable after load; safe to share across requests.

    Two kinds (``meta["kind"]``): :data:`KIND_IMPACT`, whose score is the player's impact as a
    percentile of games in their role (it reads each row's ``team_position`` and
    ``champion_id`` as context), and the legacy :data:`KIND_WIN_PROBABILITY`, the sigmoid of
    a :class:`WinPredictionNet` over the stats alone. Callers use the kind-neutral methods
    (:meth:`score_rows`, :meth:`scores_from_scaled`, :meth:`score_tensor`, ...).
    """

    #: Model version string, e.g. "20260921-183005".
    version: str
    #: Parsed meta.json (feature_names, metrics, trained_at, ...).
    meta: dict[str, Any]
    feature_names: list[str]
    #: Directory the artifacts were loaded from.
    path: Path
    #: The network, in eval mode. Never call ``.train()`` on it.
    model: WinPredictionNet | HexImpactNet
    kind: str

    def __init__(
        self,
        *,
        version: str,
        meta: dict[str, Any],
        model: WinPredictionNet | HexImpactNet,
        scaler_mean: FloatArray,
        scaler_scale: FloatArray,
        path: Path,
    ) -> None:
        self.version = version
        self.meta = meta
        self.feature_names = list(meta.get("feature_names", FEATURE_NAMES))
        self.path = path
        self.kind = str(meta.get("kind") or KIND_WIN_PROBABILITY)
        model.eval()
        for param in model.parameters():
            param.requires_grad_(False)
        self.model = model
        self._mean = scaler_mean.astype(np.float64)
        scale = scaler_scale.astype(np.float64)
        # StandardScaler stores 1.0 for zero-variance features; keep that guarantee.
        self._scale = np.where((scale == 0) | ~np.isfinite(scale), 1.0, scale)
        n = len(self.feature_names)
        self._champions: dict[int, int] = {}
        self._score_map: _ScoreMap | None = None
        self._baselines = np.zeros((ROLE_SLOTS, n), dtype=np.float64)
        if self.kind == KIND_IMPACT:
            champions = meta.get("champions") or []
            self._champions = {int(c): i + 1 for i, c in enumerate(champions)}
            self._score_map = _ScoreMap(meta, len(champions) + 1)
            self._baselines = _float_matrix(meta.get("baselines"), (ROLE_SLOTS, n), "baselines")

    def __repr__(self) -> str:
        return f"Scorer(version={self.version!r}, kind={self.kind!r}, n_features={self.n_features})"

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
        kind = str(meta.get("kind") or KIND_WIN_PROBABILITY)
        if kind not in KINDS:
            raise ModelLoadError(f"unknown model kind {kind!r}; this build knows {sorted(KINDS)}")
        n = len(names)
        version = meta.get("version")
        if not isinstance(version, str) or not version:
            version = version_dir.name
            meta["version"] = version

        try:
            state = torch.load(version_dir / MODEL_FILE, map_location="cpu", weights_only=True)
        except Exception as exc:  # corrupt / foreign pickle
            raise ModelLoadError(f"cannot read {version_dir / MODEL_FILE}: {exc}") from exc
        model: WinPredictionNet | HexImpactNet
        if kind == KIND_IMPACT:
            champions = meta.get("champions") or []
            network = meta.get("network") if isinstance(meta.get("network"), dict) else {}
            try:
                hidden = tuple(int(h) for h in network.get("hidden", IMPACT_HIDDEN))
                model = HexImpactNet(n, n_champions=len(champions), hidden=hidden)
            except (TypeError, ValueError) as exc:
                raise ModelLoadError(f"meta.json network is invalid: {exc}") from exc
        else:
            model = WinPredictionNet(n)
        try:
            model.load_state_dict(state)
        except (RuntimeError, TypeError, AttributeError) as exc:
            raise ModelLoadError(
                f"{MODEL_FILE} does not match {type(model).__name__}({n}): {exc}"
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

    @property
    def uses_context(self) -> bool:
        """True when scores depend on each row's role and champion, not only its stats."""
        return self.kind == KIND_IMPACT

    # --- scoring --------------------------------------------------------------------------

    def features(
        self, durations_seconds: Sequence[int | float], rows: Sequence[Mapping[str, Any]]
    ) -> FloatArray:
        """Raw (unscaled) feature matrix for ``rows``."""
        return compute_feature_matrix(durations_seconds, rows, feature_names=self.feature_names)

    def context(
        self, rows: Sequence[Mapping[str, Any]]
    ) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
        """``(role slots, champion slots)`` for ``rows`` (from ``team_position`` and
        ``champion_id``; missing keys mean an unknown role / champion)."""
        roles = role_slots([r.get("team_position") for r in rows])
        champions = np.fromiter(
            (self._champions.get(_int_or_zero(r.get("champion_id")), 0) for r in rows),
            dtype=np.int64,
            count=len(rows),
        )
        return roles, champions

    def scale(self, features: FloatArray) -> FloatArray:
        """Apply the training StandardScaler."""
        return (np.asarray(features, dtype=np.float64) - self._mean) / self._scale

    def _context_tensors(
        self,
        n: int,
        roles: npt.NDArray[np.int64] | None,
        champions: npt.NDArray[np.int64] | None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        r = np.full(n, UNKNOWN_ROLE_SLOT, np.int64) if roles is None else np.asarray(roles)
        c = np.zeros(n, np.int64) if champions is None else np.asarray(champions)
        return torch.as_tensor(r, dtype=torch.long), torch.as_tensor(c, dtype=torch.long)

    def _forward(
        self, x: torch.Tensor, roles: torch.Tensor, champions: torch.Tensor
    ) -> torch.Tensor:
        if isinstance(self.model, HexImpactNet):
            return self.model(x, roles, champions)
        return self.model(x).reshape(-1)

    def logits_from_scaled(
        self,
        scaled: FloatArray,
        roles: npt.NDArray[np.int64] | None = None,
        champions: npt.NDArray[np.int64] | None = None,
    ) -> FloatArray:
        """Raw network output (float64, shape (n,)): win logits for the legacy kind, impact
        (logits of the team's win chance) for the impact kind."""
        if scaled.shape[0] == 0:
            return np.zeros(0, dtype=np.float64)
        r, c = self._context_tensors(scaled.shape[0], roles, champions)
        with torch.inference_mode():
            out = self._forward(torch.as_tensor(scaled, dtype=torch.float32), r, c)
        return out.reshape(-1).to(torch.float64).numpy()

    @staticmethod
    def probabilities(logits: FloatArray) -> FloatArray:
        """Sigmoid, clipped to [PROB_EPS, 1 - PROB_EPS]."""
        probs = 0.5 * (1.0 + np.tanh(0.5 * np.asarray(logits, dtype=np.float64)))
        return np.clip(probs, PROB_EPS, 1.0 - PROB_EPS)

    def scores_from_scaled(
        self,
        scaled: FloatArray,
        roles: npt.NDArray[np.int64] | None = None,
        champions: npt.NDArray[np.int64] | None = None,
    ) -> FloatArray:
        """Scores in (0, 1) for already-scaled inputs and their context."""
        n = scaled.shape[0]
        if self._score_map is None:
            return self.probabilities(self.logits_from_scaled(scaled, roles, champions))
        r = np.full(n, UNKNOWN_ROLE_SLOT, np.int64) if roles is None else np.asarray(roles)
        c = np.zeros(n, np.int64) if champions is None else np.asarray(champions)
        out = self._score_map(self.logits_from_scaled(scaled, r, c), r, c)
        # No position (rare): the network never trained on that slot, so average the five roles.
        unknown = r == UNKNOWN_ROLE_SLOT
        if unknown.any():
            sub, sub_c = scaled[unknown], c[unknown]
            total = np.zeros(sub.shape[0])
            for slot in range(len(ROLES)):
                rr = np.full(sub.shape[0], slot, np.int64)
                total += self._score_map(self.logits_from_scaled(sub, rr, sub_c), rr, sub_c)
            out[unknown] = total / len(ROLES)
        return np.clip(out, PROB_EPS, 1.0 - PROB_EPS)

    def score_tensor(
        self, scaled: torch.Tensor, roles: torch.Tensor, champions: torch.Tensor
    ) -> torch.Tensor:
        """Differentiable scores (0..1, unclipped) for a float32 tensor of scaled inputs."""
        raw = self._forward(scaled, roles, champions)
        if self._score_map is None:
            return torch.sigmoid(raw)
        out = self._score_map.tensor(raw, roles, champions)
        unknown = roles == UNKNOWN_ROLE_SLOT
        if bool(unknown.any()):
            total = torch.zeros_like(out)
            for slot in range(len(ROLES)):
                rr = torch.full_like(roles, slot)
                total = total + self._score_map.tensor(
                    self._forward(scaled, rr, champions), rr, champions
                )
            out = torch.where(unknown, total / len(ROLES), out)
        return out

    def score_rows(
        self,
        durations_seconds: Sequence[int | float],
        rows: Sequence[Mapping[str, Any]],
    ) -> np.ndarray:
        """Scores in (0, 1), shape (len(rows),). ``durations_seconds[i]`` is the game
        duration of ``rows[i]``."""
        scaled = self.scale(self.features(durations_seconds, rows))
        roles, champions = self.context(rows)
        return self.scores_from_scaled(scaled, roles, champions)

    def score_match(
        self, game_duration_seconds: int, participants: Sequence[Mapping[str, Any]]
    ) -> dict[str, float]:
        """Score every participant of one match; returns ``{puuid: score}``."""
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

    # --- baselines (what an average stat line scores) ---------------------------------------

    def baseline_scaled(self, roles: npt.NDArray[np.int64] | None = None) -> FloatArray:
        """Scaled stat line of an average player in each row's role, shape (n, n_features):
        the training mean (zeros) for the legacy kind, the role's mean for the impact kind."""
        if roles is None:
            roles = np.array([UNKNOWN_ROLE_SLOT], dtype=np.int64)
        return self._baselines[np.asarray(roles, dtype=np.int64)].copy()

    def base_scores(
        self,
        roles: npt.NDArray[np.int64] | None = None,
        champions: npt.NDArray[np.int64] | None = None,
    ) -> FloatArray:
        """Score of :meth:`baseline_scaled` for each row's context."""
        base = self.baseline_scaled(roles)
        return self.scores_from_scaled(base, roles, champions)

    def base_probability(self) -> float:
        """Score of the average stat line: the all-mean input for the legacy kind, the mean
        over the five roles of their average line for the impact kind."""
        if self.kind == KIND_IMPACT:
            roles = np.arange(len(ROLES), dtype=np.int64)
            scores = self.base_scores(roles, np.zeros_like(roles))
        else:
            scores = self.scores_from_scaled(np.zeros((1, self.n_features), dtype=np.float64))
        value = float(np.mean(scores))
        if not math.isfinite(value):
            raise ValueError("model produced a non-finite score")
        return value


def _int_or_zero(value: object) -> int:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0


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
