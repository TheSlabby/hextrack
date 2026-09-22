"""Scorer loading / scoring, explain output and the network itself (no training)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import numpy as np
import pytest
import torch
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from hextrack.api.schemas import FeatureAttribution
from hextrack.db.models import Match, MatchParticipant
from hextrack.hextrack_ai.explain import (
    base_score,
    display_groups,
    explain_player,
    integrated_gradients,
)
from hextrack.hextrack_ai.features import FEATURE_GROUPS, FEATURE_LABELS, FEATURE_NAMES
from hextrack.hextrack_ai.inference import (
    ACTIVE_FILE,
    ModelLoadError,
    Scorer,
    participant_to_dict,
)
from hextrack.hextrack_ai.model import WinPredictionNet
from tests.test_ai_support import (
    insert_matches,
    mapped_participants,
    rewrite_meta,
    signal_matches,
    write_model,
)

T1 = datetime(2026, 9, 1, 12, tzinfo=UTC)
T2 = datetime(2026, 9, 10, 12, tzinfo=UTC)
LEGACY_31 = [*FEATURE_NAMES[:20], "turretKillsPerMinute", *FEATURE_NAMES[20:]]


@pytest.fixture
def model_dir(tmp_path):
    path = tmp_path / "artifacts"
    path.mkdir()
    return path


@pytest.fixture
def scorer(model_dir) -> Scorer:
    write_model(model_dir, "20260901-120000", trained_at=T1)
    loaded = Scorer.load(model_dir)
    assert loaded is not None
    return loaded


@pytest.fixture
def match_rows():
    raw = signal_matches(1, seed=3)[0]
    return mapped_participants(raw)


# --- network -------------------------------------------------------------------------------


def test_network_architecture_matches_legacy():
    net = WinPredictionNet(30)
    linears = [m for m in net.modules() if isinstance(m, torch.nn.Linear)]
    assert [(m.in_features, m.out_features) for m in linears] == [
        (30, 64),
        (64, 32),
        (32, 16),
        (16, 1),
    ]
    dropouts = [m for m in net.modules() if isinstance(m, torch.nn.Dropout)]
    assert len(dropouts) == 2 and all(d.p == 0.2 for d in dropouts)
    assert net(torch.zeros(4, 30)).shape == (4, 1)
    with pytest.raises(ValueError):
        WinPredictionNet(0)


# --- loading -------------------------------------------------------------------------------


def test_load_returns_none_without_artifacts(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="hextrack.hextrack_ai.inference")
    assert Scorer.load(tmp_path / "does-not-exist") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert Scorer.load(empty) is None
    assert "no AI model artifacts" in caplog.text


def test_round_trip_via_active_file(model_dir):
    write_model(model_dir, "20260901-120000", trained_at=T1, seed=1)
    write_model(model_dir, "20260910-120000", trained_at=T2, seed=2)
    (model_dir / ACTIVE_FILE).write_text("20260901-120000\n")

    scorer = Scorer.load(model_dir)
    assert scorer is not None
    assert scorer.version == "20260901-120000"
    assert scorer.feature_names == list(FEATURE_NAMES)
    assert scorer.n_features == 30
    assert scorer.trained_at == T1
    assert scorer.trained_at.tzinfo is not None
    assert scorer.path == model_dir / "20260901-120000"
    assert scorer.meta["metrics"]["val_auc"] == 0.5
    assert not scorer.model.training


def test_falls_back_to_newest_version(model_dir, caplog):
    write_model(model_dir, "20260901-120000", trained_at=T1, seed=1)
    write_model(model_dir, "20260910-120000", trained_at=T2, seed=2)
    (model_dir / ".tmp-20260920-000000-abcd").mkdir()  # in-progress training is ignored
    scorer = Scorer.load(model_dir)
    assert scorer is not None and scorer.version == "20260910-120000"

    caplog.set_level(logging.WARNING, logger="hextrack.hextrack_ai.inference")
    (model_dir / ACTIVE_FILE).write_text("20250101-000000")
    scorer = Scorer.load(model_dir)
    assert scorer is not None and scorer.version == "20260910-120000"
    assert "does not exist" in caplog.text

    (model_dir / ACTIVE_FILE).write_text("../escape")
    scorer = Scorer.load(model_dir)
    assert scorer is not None and scorer.version == "20260910-120000"


def test_flat_model_dir_is_loaded_directly(tmp_path):
    version_dir = write_model(tmp_path, "flat", trained_at=T1)
    scorer = Scorer.load(version_dir)
    assert scorer is not None and scorer.version == "flat"


def test_feature_mismatch_is_rejected(model_dir, caplog):
    version_dir = write_model(model_dir, "20260901-120000", trained_at=T1)
    rewrite_meta(version_dir, feature_names=LEGACY_31, feature_set="legacy-31")
    caplog.set_level(logging.WARNING, logger="hextrack.hextrack_ai.inference")
    assert Scorer.load(model_dir) is None
    assert "legacy-31" in caplog.text
    with pytest.raises(ModelLoadError, match="Retrain"):
        Scorer.from_version_dir(version_dir)

    # same names in a different order are also incompatible
    rewrite_meta(version_dir, feature_names=list(reversed(FEATURE_NAMES)))
    with pytest.raises(ModelLoadError):
        Scorer.from_version_dir(version_dir)


def test_broken_artifacts_are_rejected(model_dir):
    version_dir = write_model(model_dir, "20260901-120000", trained_at=T1)
    (version_dir / "scaler.pkl").write_bytes(b"not a pickle")
    with pytest.raises(ModelLoadError, match="scaler"):
        Scorer.from_version_dir(version_dir)
    assert Scorer.load(model_dir) is None

    (version_dir / "scaler.pkl").unlink()
    with pytest.raises(ModelLoadError, match="missing"):
        Scorer.from_version_dir(version_dir)

    other = write_model(model_dir, "20260902-120000", trained_at=T2)
    (other / "meta.json").write_text("{not json")
    with pytest.raises(ModelLoadError, match="JSON"):
        Scorer.from_version_dir(other)


# --- scoring -------------------------------------------------------------------------------


def test_score_match_returns_probabilities_by_puuid(scorer, match_rows):
    duration, rows = match_rows
    scores = scorer.score_match(duration, rows)
    assert set(scores) == {r["puuid"] for r in rows}
    assert all(isinstance(v, float) and 0.0 < v < 1.0 for v in scores.values())
    by_rows = scorer.score_rows([duration] * len(rows), rows)
    assert by_rows.shape == (10,)
    np.testing.assert_allclose([scores[r["puuid"]] for r in rows], by_rows)
    assert scorer.score_match(duration, rows) == scores  # deterministic (eval mode)
    assert scorer.score_match(duration, []) == {}


def test_score_match_validates_puuids(scorer, match_rows):
    duration, rows = match_rows
    with pytest.raises(ValueError, match="duplicate"):
        scorer.score_match(duration, [rows[0], rows[0]])
    with pytest.raises(ValueError, match="puuid"):
        scorer.score_match(duration, [dict(rows[0], puuid=None)])


def test_scores_stay_strictly_inside_unit_interval(scorer, match_rows):
    duration, rows = match_rows
    extreme = [dict(rows[0], kills=10**7, gold_earned=1, deaths=0), dict(rows[1], deaths=10**7)]
    probs = scorer.score_rows([duration, duration], extreme)
    assert np.all((probs > 0.0) & (probs < 1.0))


# --- explain -------------------------------------------------------------------------------


def test_explain_player_shape(scorer, match_rows):
    duration, rows = match_rows
    player_rows = rows[:3]
    population = {name: 1.0 + i for i, name in enumerate(FEATURE_NAMES)}
    result = explain_player(scorer, [duration] * 3, player_rows, population)

    headlines = [headline for headline, _ in display_groups(FEATURE_NAMES)]
    assert len(result) == len(headlines) == 21  # 30 inputs, 5 collinear groups
    assert {r["feature"] for r in result} == set(headlines)
    for item in result:
        assert set(item) == set(FeatureAttribution.model_fields)
        FeatureAttribution.model_validate(item)
        assert item["label"] == FEATURE_LABELS[item["feature"]]
        assert item["group"] == FEATURE_GROUPS[item["feature"]]
        assert item["population_value"] == population[item["feature"]]
        assert item["mean_abs_attribution"] >= abs(item["mean_attribution"]) - 1e-12
    abs_values = [r["mean_abs_attribution"] for r in result]
    assert abs_values == sorted(abs_values, reverse=True)
    assert any(v > 0 for v in abs_values)

    raw = scorer.features([duration] * 3, player_rows)
    kills = next(r for r in result if r["feature"] == "kills")
    assert kills["player_value"] == pytest.approx(raw[:, FEATURE_NAMES.index("kills")].mean())
    # the shared model's parameters never get gradients
    assert all(p.grad is None for p in scorer.model.parameters())


def test_explain_player_without_population_or_rows(scorer, match_rows):
    duration, rows = match_rows
    result = explain_player(scorer, [duration], rows[:1], None)
    assert all(item["population_value"] is None for item in result)
    assert explain_player(scorer, [], [], None) == []


def test_display_groups_cover_every_feature_once():
    groups = display_groups(FEATURE_NAMES)
    members = [name for _, names in groups for name in names]
    assert sorted(members) == sorted(FEATURE_NAMES)  # a partition: no gaps, no duplicates
    by_headline = dict(groups)
    assert by_headline["deaths"] == (
        "deaths",
        "deathsPerMinute",
        "deathsPerGold",
        "longestTimeSpentLiving",
    )
    assert by_headline["kills"] == ("kills", "killsPerMinute", "killsPerGold")
    assert by_headline["goldPerMinute"] == ("goldPerMinute",)
    # entries keep model feature order (kills per minute is the first kill input)
    assert [headline for headline, _ in groups][:3] == ["kills", "deaths", "assists"]
    # a model without the per-gold inputs keeps the remaining members together
    trimmed = [n for n in FEATURE_NAMES if not n.endswith("PerGold")]
    assert dict(display_groups(trimmed))["kills"] == ("kills", "killsPerMinute")


def test_attributions_are_complete_in_score_points(scorer, match_rows):
    """Each game's attributions add up to its score minus the average-line score, so the
    bars of a player add up to the gap between their average score and that line."""
    duration, rows = match_rows
    scaled = scorer.scale(scorer.features([duration] * 10, rows))
    per_game = integrated_gradients(scorer, scaled)
    base = base_score(scorer)
    assert base is not None
    probabilities = scorer.probabilities(scorer.logits_from_scaled(scaled))
    # float32 forward passes differ in the last digits between batches: 1e-6 is 0.0001 points
    np.testing.assert_allclose(per_game.sum(axis=1), probabilities - base, atol=1e-6)

    result = explain_player(scorer, [duration] * 10, rows, None)
    slope = base * (1.0 - base)
    # what the web app shows: mean_attribution * b * (1 - b) * 100 AI Score points
    bars = sum(item["mean_attribution"] for item in result) * slope
    assert bars == pytest.approx(float(probabilities.mean()) - base, abs=1e-6)
    assert max(abs(item["mean_attribution"]) * slope * 100 for item in result) < 100


def test_grouped_attribution_is_the_sum_of_its_inputs(scorer, match_rows):
    duration, rows = match_rows
    scaled = scorer.scale(scorer.features([duration] * 10, rows))
    base = base_score(scorer)
    assert base is not None
    per_game = integrated_gradients(scorer, scaled) / (base * (1.0 - base))
    index = {name: j for j, name in enumerate(FEATURE_NAMES)}

    result = {r["feature"]: r for r in explain_player(scorer, [duration] * 10, rows, None)}
    for headline, members in display_groups(FEATURE_NAMES):
        totals = per_game[:, [index[m] for m in members]].sum(axis=1)
        assert result[headline]["mean_attribution"] == pytest.approx(totals.mean())
        assert result[headline]["mean_abs_attribution"] == pytest.approx(np.abs(totals).mean())


def test_integrated_gradients_leave_the_model_alone(scorer, match_rows):
    duration, rows = match_rows
    scaled = scorer.scale(scorer.features([duration] * 4, rows[:4]))
    before = [p.detach().clone() for p in scorer.model.parameters()]
    attr = integrated_gradients(scorer, scaled, steps=8)
    assert attr.shape == scaled.shape
    assert all(p.grad is None for p in scorer.model.parameters())
    after = scorer.model.parameters()
    assert all(torch.equal(p, saved) for p, saved in zip(after, before, strict=True))
    assert integrated_gradients(scorer, scaled[:0]).shape == (0, 30)
    with pytest.raises(ValueError):
        integrated_gradients(scorer, scaled, steps=0)


def test_base_score(scorer):
    value = base_score(scorer)
    assert value is not None and 0.0 < value < 1.0


# --- ORM rows ------------------------------------------------------------------------------


async def test_participant_to_dict_matches_mapping(session_factory, clean_db, scorer):
    raw = signal_matches(1, seed=11)[0]
    duration, mapped_rows = mapped_participants(raw)
    (match_id,) = await insert_matches(session_factory, [raw])
    async with session_factory() as session:
        match = await session.scalar(
            select(Match)
            .where(Match.match_id == match_id)
            .options(selectinload(Match.participants))
        )
        assert match is not None
        orm_rows = [participant_to_dict(p) for p in match.participants]
        result_rows = (
            await session.execute(
                select(MatchParticipant.__table__).where(MatchParticipant.match_id == match_id)
            )
        ).all()

    assert "match" not in orm_rows[0]  # relationships are not included
    assert orm_rows[0]["puuid"] == mapped_rows[0]["puuid"]
    from_orm = scorer.score_match(duration, orm_rows)
    from_mapping = scorer.score_match(duration, mapped_rows)
    assert from_orm.keys() == from_mapping.keys()
    for puuid, value in from_mapping.items():
        assert from_orm[puuid] == pytest.approx(value)

    # Core result rows and plain mappings are accepted too
    as_rows = [participant_to_dict(r) for r in result_rows]
    assert {r["puuid"] for r in as_rows} == set(from_mapping)
    assert participant_to_dict(mapped_rows[0]) == mapped_rows[0]
    with pytest.raises(TypeError):
        participant_to_dict(object())
