"""The impact model (the current Hex Score): game assembly, score map, training, scoring,
explanations, and that legacy win-probability models keep working beside it."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
import torch

from hextrack.hextrack_ai import impact
from hextrack.hextrack_ai.explain import base_score_for, explain_player, integrated_gradients
from hextrack.hextrack_ai.features import ROLE_SLOTS, ROLES, UNKNOWN_ROLE_SLOT, role_slot
from hextrack.hextrack_ai.inference import KIND_IMPACT, KIND_WIN_PROBABILITY, Scorer
from hextrack.hextrack_ai.registry import clear_population_cache
from hextrack.hextrack_ai.train import train
from tests.test_ai_support import insert_matches, mapped_participants, signal_matches


@pytest.fixture
async def trained(clean_db, session_factory, settings):
    clear_population_cache()
    await insert_matches(session_factory, signal_matches(40, seed=11))
    report = train(settings, epochs=6, activate=True)
    scorer = Scorer.from_version_dir(report.model_dir)
    return report, scorer


@pytest.fixture
def match_rows():
    return mapped_participants(signal_matches(1, seed=3)[0])


# --- pieces --------------------------------------------------------------------------------


def test_role_slot():
    assert [role_slot(r) for r in ROLES] == list(range(len(ROLES)))
    assert role_slot("utility") == ROLES.index("UTILITY")
    assert role_slot("") == role_slot(None) == role_slot("Invalid") == UNKNOWN_ROLE_SLOT


def test_game_rows_keeps_complete_consistent_games():
    # game 0: complete; game 1: a team-200 player "won" with a losing team; game 2: nine rows
    match_ids = np.repeat([0, 1, 2], 10)[:-1]
    team_ids = np.tile(np.repeat([200, 100], 5), 3)[:-1]  # team 200 first on purpose
    labels = np.tile(np.r_[np.zeros(5), np.ones(5)], 3)[:-1].astype(np.float64)
    labels[10] = 1.0
    rows, y = impact.game_rows(match_ids, team_ids, labels, np.ones(29, dtype=bool))
    assert rows.shape == (1, 10)
    assert (team_ids[rows[0, :5]] == 100).all() and (team_ids[rows[0, 5:]] == 200).all()
    assert y.tolist() == [1.0]  # team 100 (labels 1) won game 0
    empty, _ = impact.game_rows(match_ids, team_ids, labels, np.zeros(29, dtype=bool))
    assert empty.shape == (0, 10)


def test_score_map_is_a_role_percentile_without_champion_strength():
    rng = np.random.default_rng(0)
    n = 6000
    roles = rng.integers(0, len(ROLES), n)
    champions = rng.integers(0, 3, n)
    # champion 2 is "strong": +1 impact for everyone who plays it; roles sit at other levels
    impacts = rng.normal(size=n) + roles * 0.5 + (champions == 2) * 1.0
    score_map = impact.build_score_map(impacts, roles, champions, 3)
    knots = np.asarray(score_map["knots"])
    assert knots.shape == (ROLE_SLOTS, impact.SCORE_LEVELS)
    assert (np.diff(knots, axis=1) > 0).all()
    offsets = score_map["champion_offsets"]
    assert offsets[2] > 0.5 > abs(offsets[0])

    scores = impact.apply_score_map(score_map, impacts, roles, champions)
    assert scores.min() >= 0 and scores.max() <= 1
    for slot in range(len(ROLES)):  # every role averages ~50 and spans the range
        s = scores[roles == slot]
        assert s.mean() == pytest.approx(0.5, abs=0.03)
        assert s.min() < 0.05 and s.max() > 0.95
    # picking the strong champion barely moves the score once its offset is removed
    gap = scores[champions == 2].mean() - scores[champions == 0].mean()
    assert abs(gap) < 0.1
    # monotone in impact within a role and champion
    ordered = impact.apply_score_map(
        score_map, np.linspace(-3, 5, 50), np.zeros(50, np.int64), np.zeros(50, np.int64)
    )
    assert (np.diff(ordered) >= 0).all()


def test_score_metrics():
    scores = np.array([0.9, 0.6, 0.4, 0.2, 0.7, 0.3])
    labels = np.array([1, 1, 0, 0, 1, 0], dtype=np.float64)
    match_ids = np.array([0, 0, 0, 0, 1, 1])
    m = impact.score_metrics(scores, labels, match_ids)
    assert m["player_auc"] == pytest.approx(1.0)
    assert m["mean_score_win"] == pytest.approx(100 * (0.9 + 0.6 + 0.7) / 3)
    # game 0: best loser 0.4 < worst winner 0.6; game 1: 0.3 < 0.7
    assert m["best_loser_beats_worst_winner"] == 0.0


# --- trained model -------------------------------------------------------------------------


async def test_training_writes_an_impact_model(trained, settings):
    report, scorer = trained
    assert scorer.kind == KIND_IMPACT and scorer.uses_context
    meta = json.loads((report.model_dir / "meta.json").read_text())
    assert meta["kind"] == KIND_IMPACT
    assert len(meta["baselines"]) == ROLE_SLOTS
    assert len(meta["score_map"]["knots"]) == ROLE_SLOTS
    assert len(meta["score_map"]["champion_offsets"]) == len(meta["champions"]) + 1
    for key in ("val_auc", "val_player_auc", "val_mean_score_win", "n_train_games"):
        assert key in meta["metrics"], key
    assert report.val_auc > 0.6  # the ten impacts explain which team won
    assert meta["metrics"]["val_mean_score_win"] > meta["metrics"]["val_mean_score_loss"]
    assert "HexImpactNet" in meta["architecture"]


async def test_impact_scores_depend_on_role_and_stay_in_range(trained, match_rows):
    _, scorer = trained
    duration, rows = match_rows
    scores = scorer.score_match(duration, rows)
    assert len(scores) == 10
    assert all(0.0 < s < 1.0 for s in scores.values())
    row = dict(rows[0])
    as_top = scorer.score_rows([duration], [{**row, "team_position": "TOP"}])[0]
    as_support = scorer.score_rows([duration], [{**row, "team_position": "UTILITY"}])[0]
    unknown = scorer.score_rows([duration], [{**row, "team_position": ""}])[0]
    assert as_top != as_support
    assert 0.0 < unknown < 1.0
    # a champion the model never saw falls back to the unknown slot instead of failing
    assert 0.0 < scorer.score_rows([duration], [{**row, "champion_id": 999_999}])[0] < 1.0


async def test_score_tensor_matches_numpy_scores(trained, match_rows):
    _, scorer = trained
    duration, rows = match_rows
    scaled = scorer.scale(scorer.features([duration] * len(rows), rows))
    roles, champions = scorer.context(rows)
    expected = scorer.scores_from_scaled(scaled, roles, champions)
    with torch.inference_mode():
        got = scorer.score_tensor(
            torch.as_tensor(scaled, dtype=torch.float32),
            torch.as_tensor(roles),
            torch.as_tensor(champions),
        ).numpy()
    np.testing.assert_allclose(got, expected, atol=1e-4)


async def test_impact_attributions_add_up_from_the_role_baseline(trained, match_rows):
    _, scorer = trained
    duration, rows = match_rows
    scaled = scorer.scale(scorer.features([duration] * len(rows), rows))
    roles, champions = scorer.context(rows)
    attr = integrated_gradients(scorer, scaled, roles, champions)
    target = scorer.scores_from_scaled(scaled, roles, champions) - scorer.base_scores(
        roles, champions
    )
    np.testing.assert_allclose(attr.sum(axis=1), target, atol=1e-6)

    # explain_player: bars in score points add up to score - base_score_for(rows)
    one = [rows[2]]
    base = base_score_for(scorer, one)
    assert base is not None and 0.0 < base < 1.0
    items = explain_player(scorer, [duration], one, None)
    points = sum(i["mean_attribution"] for i in items) * base * (1 - base)
    score = float(scorer.score_rows([duration], one)[0])
    assert points == pytest.approx(score - base, abs=1e-6)
    assert not any(i["feature"] in ROLES for i in items)  # context is never credited


async def test_a_legacy_model_trains_loads_and_rescores(clean_db, session_factory, settings):
    await insert_matches(session_factory, signal_matches(30, seed=12))
    report = train(settings, epochs=2, activate=True, kind=KIND_WIN_PROBABILITY)
    scorer = Scorer.from_version_dir(report.model_dir)
    assert scorer.kind == KIND_WIN_PROBABILITY and not scorer.uses_context
    assert report.rescored_rows == 300
    meta = json.loads((report.model_dir / "meta.json").read_text())
    assert meta["kind"] == KIND_WIN_PROBABILITY
    assert math.isclose(scorer.base_probability(), float(scorer.base_scores()[0]))


def test_unknown_kind_is_refused(settings):
    with pytest.raises(ValueError, match="unknown model kind"):
        train(settings, kind="nope")
