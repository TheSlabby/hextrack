"""Single source of truth for AI Score features (owner: B3).

Features are computed from ``match_participants`` column dicts (as produced by
``hextrack.ingest.mapping.map_participant`` or :func:`hextrack.hextrack_ai.inference.
participant_to_dict`), identically for training and inference.

Port of the legacy ``hextrack-ai/data_loader.get_features_from_df`` with two fixes:

* the duplicate ``turretKillsPerMinute`` column (identical to ``turretsPerMinute``) is gone;
* pings are ``pings_total`` (hold + getBack + onMyWay + needVision + enemyMissing +
  enemyVision, each counted once; the legacy sum counted ``getBackPings`` twice).

That makes the default feature set 30 features wide (``FEATURE_SET = "v2-30"``); models
trained on the legacy 31-feature set are rejected at load time by design.

Guards: per-minute features are 0 when the duration is not positive, per-gold features are
0 when ``gold_earned`` is not positive, and missing (``None``) or non-finite stat values
count as 0, so every feature value is finite.

``killParticipation`` / ``deathParticipation`` (legacy, commented out there) are available
behind :data:`INCLUDE_PARTICIPATION` (off by default). They need team totals: see
:func:`compute_feature_matrix`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

import numpy as np
import numpy.typing as npt

FeatureGroup = Literal["combat", "economy", "vision", "objectives", "survival", "teamplay"]

FloatArray = npt.NDArray[np.float64]

#: Participation features change the model input; flipping this requires retraining.
INCLUDE_PARTICIPATION: Final[bool] = False

BASE_FEATURE_SET: Final = "v2-30"
PARTICIPATION_FEATURE_SET: Final = "v2-32-participation"
#: Identifies the feature definition a model was trained with (stored in meta.json).
FEATURE_SET: Final[str] = PARTICIPATION_FEATURE_SET if INCLUDE_PARTICIPATION else BASE_FEATURE_SET

#: Optional per-row keys with the participant's team kill / death totals (used by the
#: participation features when present).
TEAM_KILLS_KEY: Final = "team_kills"
TEAM_DEATHS_KEY: Final = "team_deaths"


@dataclass(frozen=True, slots=True)
class _Inputs:
    """Column arrays for a batch of participant rows."""

    minutes: FloatArray
    columns: Mapping[str, FloatArray]
    team_kills: FloatArray | None = None
    team_deaths: FloatArray | None = None

    def col(self, name: str) -> FloatArray:
        return self.columns[name]


def _safe_div(numerator: FloatArray, denominator: FloatArray) -> FloatArray:
    """``numerator / denominator`` with 0 wherever the denominator is not positive."""
    out = np.zeros_like(numerator, dtype=np.float64)
    np.divide(numerator, denominator, out=out, where=denominator > 0)
    return out


def _per_minute(column: str) -> Callable[[_Inputs], FloatArray]:
    def compute(x: _Inputs) -> FloatArray:
        return _safe_div(x.col(column), x.minutes)

    return compute


def _per_gold(column: str) -> Callable[[_Inputs], FloatArray]:
    def compute(x: _Inputs) -> FloatArray:
        return _safe_div(x.col(column), x.col("gold_earned"))

    return compute


def _raw(column: str) -> Callable[[_Inputs], FloatArray]:
    def compute(x: _Inputs) -> FloatArray:
        return x.col(column).copy()

    return compute


def _kill_participation(x: _Inputs) -> FloatArray:
    if x.team_kills is None:
        raise ValueError("killParticipation needs team kill totals")
    # Legacy: a team with 0 kills counts as 1 so the ratio stays finite.
    return (x.col("kills") + x.col("assists")) / np.maximum(x.team_kills, 1.0)


def _death_participation(x: _Inputs) -> FloatArray:
    if x.team_deaths is None:
        raise ValueError("deathParticipation needs team death totals")
    return x.col("deaths") / np.maximum(x.team_deaths, 1.0)


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """One model input: its contract name, chart label, explain group and formula."""

    name: str
    label: str
    group: FeatureGroup
    compute: Callable[[_Inputs], FloatArray]
    #: ``match_participants`` columns the formula reads.
    columns: tuple[str, ...]
    needs_team_totals: bool = False


def _spec(
    name: str,
    label: str,
    group: FeatureGroup,
    kind: Literal["per_minute", "per_gold", "raw"],
    column: str,
) -> FeatureSpec:
    if kind == "per_minute":
        return FeatureSpec(name, label, group, _per_minute(column), (column,))
    if kind == "per_gold":
        return FeatureSpec(name, label, group, _per_gold(column), (column, "gold_earned"))
    return FeatureSpec(name, label, group, _raw(column), (column,))


#: The 30 default features, in contract order (legacy order minus the duplicate).
_BASE_SPECS: Final[tuple[FeatureSpec, ...]] = (
    # KDA
    _spec("killsPerMinute", "Kills per minute", "combat", "per_minute", "kills"),
    _spec("deathsPerMinute", "Deaths per minute", "survival", "per_minute", "deaths"),
    _spec("assistsPerMinute", "Assists per minute", "teamplay", "per_minute", "assists"),
    # vision
    _spec("visionPerMinute", "Vision score per minute", "vision", "per_minute", "vision_score"),
    _spec(
        "controlWardsPerMinute",
        "Control wards bought per minute",
        "vision",
        "per_minute",
        "vision_wards_bought",
    ),
    _spec(
        "wardsKilledPerMinute", "Wards destroyed per minute", "vision", "per_minute", "wards_killed"
    ),
    # gold
    _spec("goldPerMinute", "Gold per minute", "economy", "per_minute", "gold_earned"),
    # cs
    _spec(
        "minionsPerMinute",
        "Minions killed per minute",
        "economy",
        "per_minute",
        "total_minions_killed",
    ),
    _spec(
        "neutralMinionsPerMinute",
        "Jungle monsters killed per minute",
        "economy",
        "per_minute",
        "neutral_minions_killed",
    ),
    _spec(
        "totalAllyJungleMinionsKilledPerMinute",
        "Own-jungle monsters killed per minute",
        "economy",
        "per_minute",
        "total_ally_jungle_minions_killed",
    ),
    # damage
    _spec(
        "damagePerMinute",
        "Damage to champions per minute",
        "combat",
        "per_minute",
        "total_damage_dealt_to_champions",
    ),
    _spec(
        "damageTakenPerMinute",
        "Damage taken per minute",
        "survival",
        "per_minute",
        "total_damage_taken",
    ),
    # cc & support
    _spec(
        "timeCCingOthersPerMinute",
        "Crowd control score per minute",
        "teamplay",
        "per_minute",
        "time_ccing_others",
    ),
    _spec("healPerMinute", "Healing done per minute", "teamplay", "per_minute", "total_heal"),
    # objectives
    _spec(
        "objectiveDamagePerMinute",
        "Objective damage per minute",
        "objectives",
        "per_minute",
        "damage_dealt_to_objectives",
    ),
    _spec(
        "turretsPerMinute",
        "Turrets destroyed per minute",
        "objectives",
        "per_minute",
        "turret_kills",
    ),
    _spec(
        "tripleKillsPerMinute", "Triple kills per minute", "combat", "per_minute", "triple_kills"
    ),
    _spec(
        "quadraKillsPerMinute", "Quadra kills per minute", "combat", "per_minute", "quadra_kills"
    ),
    _spec("pentaKillsPerMinute", "Penta kills per minute", "combat", "per_minute", "penta_kills"),
    # pings
    _spec("pingsPerMinute", "Pings per minute", "teamplay", "per_minute", "pings_total"),
    # per-gold efficiency
    _spec("killsPerGold", "Kills per gold earned", "economy", "per_gold", "kills"),
    _spec("deathsPerGold", "Deaths per gold earned", "economy", "per_gold", "deaths"),
    _spec("assistsPerGold", "Assists per gold earned", "economy", "per_gold", "assists"),
    _spec(
        "damagePerGold",
        "Damage to champions per gold earned",
        "economy",
        "per_gold",
        "total_damage_dealt_to_champions",
    ),
    # other raw stats
    _spec("largestKillingSpree", "Largest killing spree", "combat", "raw", "largest_killing_spree"),
    _spec("killingSprees", "Killing sprees", "combat", "raw", "killing_sprees"),
    _spec(
        "longestTimeSpentLiving",
        "Longest time alive (seconds)",
        "survival",
        "raw",
        "longest_time_spent_living",
    ),
    _spec("kills", "Kills", "combat", "raw", "kills"),
    _spec("deaths", "Deaths", "survival", "raw", "deaths"),
    _spec("assists", "Assists", "teamplay", "raw", "assists"),
)

_PARTICIPATION_SPECS: Final[tuple[FeatureSpec, ...]] = (
    FeatureSpec(
        "killParticipation",
        "Kill participation",
        "teamplay",
        _kill_participation,
        ("kills", "assists"),
        needs_team_totals=True,
    ),
    FeatureSpec(
        "deathParticipation",
        "Share of team deaths",
        "survival",
        _death_participation,
        ("deaths",),
        needs_team_totals=True,
    ),
)

#: Every known feature, by name.
FEATURE_SPECS: Final[dict[str, FeatureSpec]] = {
    s.name: s for s in (*_BASE_SPECS, *_PARTICIPATION_SPECS)
}
#: Feature names of each known feature set.
FEATURE_SETS: Final[dict[str, tuple[str, ...]]] = {
    BASE_FEATURE_SET: tuple(s.name for s in _BASE_SPECS),
    PARTICIPATION_FEATURE_SET: tuple(s.name for s in (*_BASE_SPECS, *_PARTICIPATION_SPECS)),
}

#: Ordered feature names (30 in the default FEATURE_SET). The order is the model contract.
FEATURE_NAMES: Final[tuple[str, ...]] = FEATURE_SETS[FEATURE_SET]
#: feature name -> human label for charts.
FEATURE_LABELS: Final[dict[str, str]] = {name: FEATURE_SPECS[name].label for name in FEATURE_NAMES}
#: feature name -> group.
FEATURE_GROUPS: Final[dict[str, FeatureGroup]] = {
    name: FEATURE_SPECS[name].group for name in FEATURE_NAMES
}


def _lookup(name: str) -> FeatureSpec:
    try:
        return FEATURE_SPECS[name]
    except KeyError:
        raise ValueError(f"unknown feature {name!r}") from None


def required_columns(feature_names: Sequence[str] = FEATURE_NAMES) -> tuple[str, ...]:
    """``match_participants`` columns needed to compute ``feature_names`` (sorted)."""
    cols: set[str] = set()
    for name in feature_names:
        cols.update(_lookup(name).columns)
    return tuple(sorted(cols))


#: Columns the default feature set reads (what training / population queries select).
FEATURE_COLUMNS: Final[tuple[str, ...]] = required_columns(FEATURE_NAMES)


def needs_team_totals(feature_names: Sequence[str]) -> bool:
    return any(_lookup(name).needs_team_totals for name in feature_names)


def _clean(values: npt.ArrayLike) -> FloatArray:
    arr = np.asarray(values, dtype=np.float64)
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


def feature_matrix_from_columns(
    durations_seconds: npt.ArrayLike,
    columns: Mapping[str, npt.ArrayLike],
    *,
    feature_names: Sequence[str] = FEATURE_NAMES,
    team_kills: npt.ArrayLike | None = None,
    team_deaths: npt.ArrayLike | None = None,
) -> FloatArray:
    """Vectorised core: an ``(n_rows, len(feature_names))`` float64 matrix.

    ``columns`` maps ``match_participants`` column names to length-``n`` arrays and
    ``durations_seconds`` holds each row's game duration. ``team_kills`` / ``team_deaths``
    are only read by the participation features.
    """
    durations = _clean(durations_seconds).reshape(-1)
    n = durations.shape[0]
    needed = required_columns(feature_names)
    missing = [c for c in needed if c not in columns]
    if missing:
        raise ValueError(f"missing match_participants columns: {', '.join(missing)}")
    cols: dict[str, FloatArray] = {}
    for name in needed:
        arr = _clean(columns[name]).reshape(-1)
        if arr.shape[0] != n:
            raise ValueError(f"column {name!r} has {arr.shape[0]} values, expected {n}")
        cols[name] = arr

    inputs = _Inputs(
        minutes=np.where(durations > 0, durations / 60.0, 0.0),
        columns=cols,
        team_kills=None if team_kills is None else _clean(team_kills).reshape(-1),
        team_deaths=None if team_deaths is None else _clean(team_deaths).reshape(-1),
    )
    if not feature_names:
        return np.zeros((n, 0), dtype=np.float64)
    out = np.empty((n, len(feature_names)), dtype=np.float64)
    for j, name in enumerate(feature_names):
        out[:, j] = _lookup(name).compute(inputs)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _team_totals(rows: Sequence[Mapping[str, Any]]) -> tuple[FloatArray, FloatArray]:
    """Per-row team kill / death totals: from ``team_kills`` / ``team_deaths`` keys when
    every row has them, otherwise summed over rows sharing (match_id, team_id)."""
    if all(TEAM_KILLS_KEY in r and TEAM_DEATHS_KEY in r for r in rows):
        return (
            _clean([r[TEAM_KILLS_KEY] or 0 for r in rows]),
            _clean([r[TEAM_DEATHS_KEY] or 0 for r in rows]),
        )
    kills: dict[tuple[Any, Any], float] = {}
    deaths: dict[tuple[Any, Any], float] = {}
    keys: list[tuple[Any, Any]] = []
    for i, r in enumerate(rows):
        if "match_id" not in r or "team_id" not in r:
            raise ValueError(
                f"row {i}: participation features need match_id and team_id "
                f"(or {TEAM_KILLS_KEY!r} / {TEAM_DEATHS_KEY!r})"
            )
        key = (r["match_id"], r["team_id"])
        keys.append(key)
        kills[key] = kills.get(key, 0.0) + float(r.get("kills") or 0)
        deaths[key] = deaths.get(key, 0.0) + float(r.get("deaths") or 0)
    return (
        np.array([kills[k] for k in keys], dtype=np.float64),
        np.array([deaths[k] for k in keys], dtype=np.float64),
    )


def compute_feature_matrix(
    durations_seconds: Sequence[int | float],
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_names: Sequence[str] = FEATURE_NAMES,
) -> FloatArray:
    """Feature matrix ``(len(rows), len(feature_names))`` for participant column dicts.

    ``durations_seconds[i]`` is the game duration of ``rows[i]``. Every column the features
    read must be present as a key (``None`` counts as 0). Participation features (only in
    the non-default feature set) use each row's ``team_kills`` / ``team_deaths`` keys, or
    else sum kills / deaths over the rows sharing ``(match_id, team_id)``, in which case
    ``rows`` must contain every participant of those teams.
    """
    if len(durations_seconds) != len(rows):
        raise ValueError(f"{len(durations_seconds)} durations for {len(rows)} rows")
    needed = required_columns(feature_names)
    for i, r in enumerate(rows):
        missing = [c for c in needed if c not in r]
        if missing:
            raise ValueError(f"row {i} is missing columns: {', '.join(missing)}")
    columns = {c: [r[c] if r[c] is not None else 0 for r in rows] for c in needed}
    team_kills: FloatArray | None = None
    team_deaths: FloatArray | None = None
    if rows and needs_team_totals(feature_names):
        team_kills, team_deaths = _team_totals(rows)
    return feature_matrix_from_columns(
        list(durations_seconds),
        columns,
        feature_names=feature_names,
        team_kills=team_kills,
        team_deaths=team_deaths,
    )


def compute_features(
    duration_seconds: int | float,
    row: Mapping[str, Any],
    *,
    feature_names: Sequence[str] = FEATURE_NAMES,
) -> FloatArray:
    """Feature vector (float64, ``len(feature_names)``) for one participant row.

    Participation features need ``team_kills`` / ``team_deaths`` keys in ``row``.
    """
    if needs_team_totals(feature_names) and not (TEAM_KILLS_KEY in row and TEAM_DEATHS_KEY in row):
        raise ValueError(
            f"participation features need {TEAM_KILLS_KEY!r} and {TEAM_DEATHS_KEY!r} in the row"
        )
    return compute_feature_matrix([duration_seconds], [row], feature_names=feature_names)[0]
