"""Feature definitions: names (the model contract), labels, guards and vectorisation."""

from __future__ import annotations

import math
from typing import get_args

import numpy as np
import pytest

from hextrack.api.schemas import FeatureGroup
from hextrack.hextrack_ai import features as F
from hextrack.ingest.mapping import PING_FIELDS, map_participant, ms_to_datetime
from tests.factories import make_match_json, spec
from tests.test_ai_support import mapped_participants

#: The legacy data_loader feature_columns order, minus the duplicate turretKillsPerMinute.
EXPECTED_NAMES = (
    "killsPerMinute",
    "deathsPerMinute",
    "assistsPerMinute",
    "visionPerMinute",
    "controlWardsPerMinute",
    "wardsKilledPerMinute",
    "goldPerMinute",
    "minionsPerMinute",
    "neutralMinionsPerMinute",
    "totalAllyJungleMinionsKilledPerMinute",
    "damagePerMinute",
    "damageTakenPerMinute",
    "timeCCingOthersPerMinute",
    "healPerMinute",
    "objectiveDamagePerMinute",
    "turretsPerMinute",
    "tripleKillsPerMinute",
    "quadraKillsPerMinute",
    "pentaKillsPerMinute",
    "pingsPerMinute",
    "killsPerGold",
    "deathsPerGold",
    "assistsPerGold",
    "damagePerGold",
    "largestKillingSpree",
    "killingSprees",
    "longestTimeSpentLiving",
    "kills",
    "deaths",
    "assists",
)


def _participant(**overrides: object) -> tuple[int, dict]:
    raw = make_match_json("NA1_42", [spec("me", "Me", "NA1", **overrides)], duration_s=1800)
    duration, rows = mapped_participants(raw)
    return duration, rows[0]


def _col(name: str) -> int:
    return F.FEATURE_NAMES.index(name)


def test_thirty_unique_features_in_contract_order():
    assert F.FEATURE_SET == "v2-30"
    assert len(F.FEATURE_NAMES) == 30
    assert len(set(F.FEATURE_NAMES)) == 30
    assert F.FEATURE_NAMES == EXPECTED_NAMES
    assert "turretKillsPerMinute" not in F.FEATURE_NAMES
    assert "killParticipation" not in F.FEATURE_NAMES  # behind the flag, off by default
    assert F.INCLUDE_PARTICIPATION is False


def test_labels_and_groups_cover_every_feature():
    assert set(F.FEATURE_LABELS) == set(F.FEATURE_NAMES)
    assert set(F.FEATURE_GROUPS) == set(F.FEATURE_NAMES)
    labels = list(F.FEATURE_LABELS.values())
    assert all(label.strip() for label in labels)
    assert len(set(labels)) == len(labels)
    assert F.FEATURE_LABELS["deathsPerMinute"] == "Deaths per minute"
    assert set(F.FEATURE_GROUPS.values()) <= set(get_args(FeatureGroup))
    # every explain-UI group is used at least once
    assert set(F.FEATURE_GROUPS.values()) == set(get_args(FeatureGroup))


def test_feature_columns_exist_on_match_participants():
    from hextrack.db.models import MatchParticipant

    table_cols = set(MatchParticipant.__table__.columns.keys())
    assert set(F.FEATURE_COLUMNS) <= table_cols


def test_pings_counted_once_each():
    pings = {field: i + 1 for i, field in enumerate(PING_FIELDS)}  # 1..6, getBack = 2
    raw = make_match_json("NA1_7", [spec("me", **pings)])
    participant = raw["info"]["participants"][0]
    row = map_participant(
        participant,
        index=0,
        match_id="NA1_7",
        game_start=ms_to_datetime(raw["info"]["gameStartTimestamp"]),
        queue_id=420,
    )
    assert row["pings_total"] == 21  # the legacy formula would have given 23
    vec = F.compute_features(1200, row)
    assert vec[_col("pingsPerMinute")] == pytest.approx(21 / 20)


def test_values_match_the_legacy_formulas():
    duration, row = _participant(
        kills=9,
        deaths=3,
        assists=12,
        goldEarned=13_500,
        totalDamageDealtToChampions=27_000,
        visionScore=45,
        visionWardsBoughtInGame=6,
        turretKills=2,
        largestKillingSpree=5,
        killingSprees=2,
        longestTimeSpentLiving=640,
    )
    minutes = duration / 60
    vec = F.compute_features(duration, row)
    assert vec.dtype == np.float64 and vec.shape == (30,)
    expected = {
        "killsPerMinute": 9 / minutes,
        "deathsPerMinute": 3 / minutes,
        "assistsPerMinute": 12 / minutes,
        "visionPerMinute": 45 / minutes,
        "controlWardsPerMinute": 6 / minutes,
        "goldPerMinute": 13_500 / minutes,
        "damagePerMinute": 27_000 / minutes,
        "turretsPerMinute": 2 / minutes,
        "minionsPerMinute": row["total_minions_killed"] / minutes,
        "healPerMinute": row["total_heal"] / minutes,
        "killsPerGold": 9 / 13_500,
        "deathsPerGold": 3 / 13_500,
        "assistsPerGold": 12 / 13_500,
        "damagePerGold": 27_000 / 13_500,
        "largestKillingSpree": 5,
        "killingSprees": 2,
        "longestTimeSpentLiving": 640,
        "kills": 9,
        "deaths": 3,
        "assists": 12,
    }
    for name, value in expected.items():
        assert vec[_col(name)] == pytest.approx(value), name


def test_zero_duration_and_zero_gold_are_guarded():
    _, row = _participant(kills=4, deaths=2, assists=3, goldEarned=0)
    vec = F.compute_features(0, row)
    assert np.all(np.isfinite(vec))
    for name in F.FEATURE_NAMES:
        if name.endswith("PerMinute") or name.endswith("PerGold"):
            assert vec[_col(name)] == 0.0, name
    assert vec[_col("kills")] == 4
    assert vec[_col("deaths")] == 2

    negative = F.compute_features(-60, row)
    assert negative[_col("killsPerMinute")] == 0.0


def test_none_and_non_finite_values_count_as_zero():
    _, row = _participant()
    row = dict(row, kills=None, vision_score=math.nan, total_heal=math.inf)
    vec = F.compute_features(1800, row)
    assert np.all(np.isfinite(vec))
    assert vec[_col("kills")] == 0.0
    assert vec[_col("visionPerMinute")] == 0.0
    assert vec[_col("healPerMinute")] == 0.0


def test_missing_column_is_an_error():
    _, row = _participant()
    del row["vision_score"]
    with pytest.raises(ValueError, match="vision_score"):
        F.compute_features(1800, row)
    with pytest.raises(ValueError, match="durations"):
        F.compute_feature_matrix([1800, 1800], [row])
    with pytest.raises(ValueError, match="unknown feature"):
        F.compute_features(1800, row, feature_names=("nope",))


def test_matrix_matches_row_by_row():
    raws = [make_match_json(f"NA1_{i}", duration_s=1500 + 60 * i) for i in range(3)]
    durations: list[int] = []
    rows: list[dict] = []
    for raw in raws:
        duration, participants = mapped_participants(raw)
        durations += [duration] * len(participants)
        rows += participants
    matrix = F.compute_feature_matrix(durations, rows)
    assert matrix.shape == (30, 30)
    stacked = np.stack([F.compute_features(d, r) for d, r in zip(durations, rows, strict=True)])
    np.testing.assert_allclose(matrix, stacked)

    columns = {c: np.array([r[c] for r in rows]) for c in F.FEATURE_COLUMNS}
    np.testing.assert_allclose(F.feature_matrix_from_columns(durations, columns), matrix)

    assert F.compute_feature_matrix([], []).shape == (0, 30)


def test_participation_features_behind_flag():
    names = F.FEATURE_SETS[F.PARTICIPATION_FEATURE_SET]
    assert len(names) == 32 and names[:30] == F.FEATURE_NAMES
    raw = make_match_json("NA1_9")
    duration, rows = mapped_participants(raw)
    matrix = F.compute_feature_matrix([duration] * 10, rows, feature_names=names)
    blue = [r for r in rows if r["team_id"] == 100]
    blue_kills = sum(r["kills"] for r in blue)
    blue_deaths = sum(r["deaths"] for r in blue)
    first = rows[0]
    assert first["team_id"] == 100
    kp = matrix[0, names.index("killParticipation")]
    dp = matrix[0, names.index("deathParticipation")]
    assert kp == pytest.approx((first["kills"] + first["assists"]) / blue_kills)
    assert dp == pytest.approx(first["deaths"] / blue_deaths)

    # a single row needs explicit team totals
    with pytest.raises(ValueError, match="team_kills"):
        F.compute_features(duration, first, feature_names=names)
    one = F.compute_features(
        duration, dict(first, team_kills=blue_kills, team_deaths=blue_deaths), feature_names=names
    )
    np.testing.assert_allclose(one, matrix[0])
    # a team with zero kills / deaths counts as 1 (legacy guard)
    zero = F.compute_features(
        duration, dict(first, team_kills=0, team_deaths=0), feature_names=names
    )
    assert np.all(np.isfinite(zero))
