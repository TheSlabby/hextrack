"""End-to-end against the test database: train, activate, list, rescore, population means."""

from __future__ import annotations

import json
import logging
import math
import random
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import delete, func, select, update

from hextrack.db.models import AiModel, Match, MatchParticipant
from hextrack.hextrack_ai import registry
from hextrack.hextrack_ai.features import FEATURE_NAMES, FEATURE_SET, compute_feature_matrix
from hextrack.hextrack_ai.inference import ACTIVE_FILE, ModelLoadError, Scorer
from hextrack.hextrack_ai.registry import (
    NoActiveModel,
    UnknownModelVersion,
    activate,
    clear_population_cache,
    list_models,
    population_feature_means,
    rescore,
)
from hextrack.hextrack_ai.train import NotEnoughData, group_split, train
from tests.test_ai_support import (
    BASE_START,
    insert_matches,
    rewrite_meta,
    signal_match,
    signal_matches,
    write_model,
)

N_RANKED = 60
N_DEMO = 6


def _dataset() -> list[dict]:
    """60 ranked solo/flex matches (6 of them DEMO_), plus rows training must skip:
    a normal-draft match (other queue), an ARAM, a remake and an aborted game."""
    rng = random.Random(21)
    raws = signal_matches(N_RANKED - N_DEMO, seed=5)
    raws += [
        signal_match(f"DEMO_{900 + i}", rng, start=BASE_START - timedelta(days=1, hours=i))
        for i in range(N_DEMO)
    ]
    raws[3] = signal_match("NA1_3000000003", rng, start=BASE_START, queue_id=440)
    raws.append(signal_match("NA1_400", rng, start=BASE_START, queue_id=400))
    raws.append(signal_match("NA1_450", rng, start=BASE_START, queue_id=450, game_mode="ARAM"))
    raws.append(signal_match("NA1_REMAKE", rng, start=BASE_START, remake=True))
    raws.append(
        signal_match("NA1_ABORT", rng, start=BASE_START, end_of_game_result="Abort_Unexpected")
    )
    return raws


@pytest.fixture
async def dataset(clean_db, session_factory) -> list[str]:
    clear_population_cache()
    return await insert_matches(session_factory, _dataset())


def test_group_split_keeps_matches_together():
    ids = np.repeat(np.array([f"M{i:03d}" for i in range(50)]), 10)
    val_mask, n_train, n_val = group_split(ids, val_fraction=0.2, seed=41)
    assert (n_train, n_val) == (40, 10)
    assert val_mask.sum() == 100
    for match_id in np.unique(ids):
        side = val_mask[ids == match_id]
        assert side.all() or not side.any()
    again, _, _ = group_split(ids, val_fraction=0.2, seed=41)
    np.testing.assert_array_equal(val_mask, again)
    with pytest.raises(NotEnoughData):
        group_split(np.array(["only"] * 10), val_fraction=0.2, seed=1)


async def test_train_refuses_too_little_data(clean_db, session_factory, settings):
    await insert_matches(session_factory, signal_matches(12, seed=1))
    with pytest.raises(NotEnoughData, match="at least 200"):
        train(settings, epochs=1)
    assert list(settings.model_dir.iterdir()) == []
    with pytest.raises(ValueError):
        train(settings, queues=())


async def test_train_end_to_end(dataset, settings, session_factory):
    report = train(settings, epochs=8, activate=True)

    # report
    assert report.n_matches == N_RANKED
    assert report.n_rows == N_RANKED * 10
    assert report.n_train + report.n_val == report.n_rows
    assert report.n_val == 120 and report.n_train == 480  # 80/20 by match
    assert report.activated is True
    assert report.epochs == 8
    assert 0.0 <= report.val_accuracy <= 1.0
    assert report.val_auc > 0.6  # the synthetic stat lines carry a real signal
    assert math.isfinite(report.val_loss)

    # artifacts
    version_dir = settings.model_dir / report.version
    assert report.model_dir == version_dir
    for name in ("model.pth", "scaler.pkl", "meta.json", "train_curve.png"):
        assert (version_dir / name).is_file(), name
    assert report.curve_path == version_dir / "train_curve.png"
    assert (version_dir / "train_curve.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert not [p for p in settings.model_dir.iterdir() if p.name.startswith(".")]
    assert (settings.model_dir / ACTIVE_FILE).read_text().strip() == report.version

    meta = json.loads((version_dir / "meta.json").read_text())
    assert meta["version"] == report.version
    assert meta["feature_set"] == FEATURE_SET
    assert meta["feature_names"] == list(FEATURE_NAMES)
    assert meta["n_train"] == 480 and meta["n_val"] == 120
    assert datetime.fromisoformat(meta["trained_at"]).tzinfo is not None
    for key in ("val_auc", "val_accuracy", "val_loss", "best_epoch", "baseline_val_loss"):
        assert key in meta["metrics"], key
    assert 1 <= meta["metrics"]["best_epoch"] <= 8
    data = meta["data"]
    assert data["n_matches"] == N_RANKED and data["n_rows"] == N_RANKED * 10
    assert data["demo_matches"] == N_DEMO and data["demo_only"] is False
    assert data["queues"] == [420, 440]
    assert data["win_rate"] == pytest.approx(0.5)
    assert sum(data["patches"].values()) == N_RANKED

    # database
    async with session_factory() as session:
        row = await session.get(AiModel, report.version)
        assert row is not None and row.is_active
        assert row.feature_names == list(FEATURE_NAMES)
        assert row.metrics["val_auc"] == pytest.approx(report.val_auc, abs=1e-5)

    # the trained model loads and scores
    scorer = Scorer.load(settings.model_dir)
    assert scorer is not None and scorer.version == report.version
    infos = list_models(settings)
    assert [i.version for i in infos] == [report.version]
    assert infos[0].is_active and infos[0].n_features == 30

    # activating also re-scored the stored games, so averages are not empty afterwards
    n_scorable = N_RANKED + 1  # + the normal-draft match (ARAM / remake / abort are skipped)
    assert report.rescored_rows == n_scorable * 10
    async with session_factory() as session:
        scored = await session.scalar(
            select(func.count())
            .select_from(MatchParticipant)
            .where(MatchParticipant.model_version == report.version)
        )
    assert scored == n_scorable * 10
    assert rescore(settings, all_rows=False) == 0  # nothing left over for a manual rescore


async def test_train_can_skip_the_rescore(dataset, settings, session_factory, caplog):
    caplog.set_level(logging.WARNING, logger="hextrack.hextrack_ai.train")
    report = train(settings, epochs=2, activate=True, rescore=False)
    assert report.activated is True and report.rescored_rows is None
    assert "hextrack model rescore" in caplog.text
    async with session_factory() as session:
        scored = await session.scalar(
            select(func.count())
            .select_from(MatchParticipant)
            .where(MatchParticipant.ai_score.is_not(None))
        )
    assert scored == 0


async def test_train_since_filter_and_no_activate(dataset, settings, session_factory):
    since = BASE_START + timedelta(hours=10)
    with pytest.raises(NotEnoughData):
        train(settings, since=BASE_START + timedelta(days=365), epochs=1)
    report = train(settings, since=since, epochs=2, activate=False)
    assert report.activated is False
    assert report.n_matches == N_RANKED - N_DEMO - 10
    assert not (settings.model_dir / ACTIVE_FILE).exists()
    async with session_factory() as session:
        row = await session.get(AiModel, report.version)
        assert row is not None and row.is_active is False
    meta = json.loads((settings.model_dir / report.version / "meta.json").read_text())
    assert meta["data"]["since"] == since.isoformat()
    assert meta["data"]["demo_matches"] == 0


async def test_activate_rescores_the_stored_games(dataset, settings, session_factory):
    """A new active model must not blank every AI average until someone runs rescore."""
    write_model(settings.model_dir, "v-new", trained_at=datetime(2026, 9, 3, tzinfo=UTC), seed=7)
    n_scorable = N_RANKED + 1

    info = activate(settings, "v-new")
    assert info.is_active and info.rescored_rows == n_scorable * 10
    async with session_factory() as session:
        stale = await session.scalar(
            select(func.count())
            .select_from(MatchParticipant)
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(
                registry.scorable_match_clause(),
                MatchParticipant.model_version.is_distinct_from("v-new"),
            )
        )
    assert stale == 0

    # opting out leaves the rows for a manual rescore
    write_model(settings.model_dir, "v-other", trained_at=datetime(2026, 9, 4, tzinfo=UTC), seed=8)
    info = activate(settings, "v-other", rescore_stored=False)
    assert info.rescored_rows is None
    assert rescore(settings, all_rows=False) == n_scorable * 10


async def test_activate_and_list_models(clean_db, settings, session_factory):
    first = datetime(2026, 9, 1, tzinfo=UTC)
    second = datetime(2026, 9, 5, tzinfo=UTC)
    write_model(settings.model_dir, "v-first", trained_at=first, seed=1)
    write_model(settings.model_dir, "v-second", trained_at=second, seed=2)

    info = activate(settings, "v-first")  # no ai_models row yet: created from meta.json
    assert info.rescored_rows == 0  # no stored matches to score
    assert info.version == "v-first" and info.is_active and info.n_features == 30
    assert info.trained_at == first
    info = activate(settings, "v-second")
    assert info.is_active
    assert (settings.model_dir / ACTIVE_FILE).read_text().strip() == "v-second"

    models = list_models(settings)
    assert [m.version for m in models] == ["v-second", "v-first"]
    assert [m.is_active for m in models] == [True, False]
    assert models[0].metrics["val_auc"] == 0.5

    with pytest.raises(UnknownModelVersion):
        activate(settings, "nope")
    with pytest.raises(UnknownModelVersion):
        activate(settings, "../v-first")

    bad = write_model(settings.model_dir, "v-legacy", trained_at=second, seed=3)
    rewrite_meta(bad, feature_names=list(FEATURE_NAMES[:-1]))
    with pytest.raises(ModelLoadError):
        activate(settings, "v-legacy")
    # a refused activation changes nothing
    assert (settings.model_dir / ACTIVE_FILE).read_text().strip() == "v-second"
    async with session_factory() as session:
        active = (
            await session.scalars(select(AiModel.version).where(AiModel.is_active.is_(True)))
        ).all()
    assert active == ["v-second"]


async def test_rescore_scores_scorable_matches(dataset, settings, session_factory):
    with pytest.raises(NoActiveModel):
        rescore(settings, all_rows=False)

    write_model(settings.model_dir, "v-a", trained_at=datetime(2026, 9, 1, tzinfo=UTC), seed=1)
    activate(settings, "v-a", rescore_stored=False)
    n_scorable = N_RANKED + 1  # + the normal-draft match; ARAM / remake / abort are skipped

    assert rescore(settings, all_rows=False, chunk_matches=7) == n_scorable * 10
    async with session_factory() as session:
        scored = await session.scalar(
            select(func.count())
            .select_from(MatchParticipant)
            .where(MatchParticipant.ai_score.is_not(None))
        )
        assert scored == n_scorable * 10
        versions = (await session.scalars(select(MatchParticipant.model_version).distinct())).all()
        assert set(versions) == {"v-a", None}
        for skipped in ("NA1_450", "NA1_REMAKE", "NA1_ABORT"):
            match = await session.get(Match, skipped)
            assert match is not None and match.scored_at is None and match.model_version is None
        match = await session.get(Match, "NA1_400")
        assert match is not None and match.model_version == "v-a" and match.scored_at is not None
        rows = (
            await session.scalars(
                select(MatchParticipant).where(MatchParticipant.match_id == "NA1_400")
            )
        ).all()
        assert all(0.0 < r.ai_score < 1.0 and r.ai_scored_at is not None for r in rows)

    # stored scores equal what the scorer computes for the same rows
    scorer = Scorer.load(settings.model_dir)
    assert scorer is not None
    by_puuid = {r.puuid: r.ai_score for r in rows}
    expected = scorer.score_match(
        match.game_duration,
        [{c.key: getattr(r, c.key) for c in MatchParticipant.__table__.columns} for r in rows],
    )
    for puuid, value in expected.items():
        assert by_puuid[puuid] == pytest.approx(value, rel=1e-6)

    assert rescore(settings, all_rows=False) == 0  # nothing stale
    assert rescore(settings, all_rows=True) == n_scorable * 10

    # one unscored row makes its whole match stale again
    async with session_factory() as session:
        await session.execute(
            update(MatchParticipant)
            .where(MatchParticipant.match_id == "NA1_400", MatchParticipant.participant_id == 1)
            .values(ai_score=None, model_version=None)
        )
        await session.commit()
    assert rescore(settings, all_rows=False) == 10

    # a newly activated model makes every row stale
    write_model(settings.model_dir, "v-b", trained_at=datetime(2026, 9, 2, tzinfo=UTC), seed=2)
    activate(settings, "v-b", rescore_stored=False)
    assert rescore(settings, all_rows=False) == n_scorable * 10
    async with session_factory() as session:
        versions = (await session.scalars(select(Match.model_version).distinct())).all()
    assert set(versions) == {"v-b", None}


async def test_population_feature_means(dataset, settings, session_factory, engine, monkeypatch):
    write_model(settings.model_dir, "v-pop", trained_at=datetime(2026, 9, 1, tzinfo=UTC))
    scorer = Scorer.load(settings.model_dir)
    assert scorer is not None

    async with session_factory() as session:
        means = await population_feature_means(session, scorer, queues=(420, 440), limit=5000)
    assert set(means) == set(FEATURE_NAMES)
    assert all(math.isfinite(v) for v in means.values())

    # reference: every participant of the 60 ranked matches, computed row by row
    async with session_factory() as session:
        result = await session.execute(
            select(Match.game_duration, MatchParticipant.__table__)
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(
                Match.queue_id.in_((420, 440)),
                Match.game_mode == "CLASSIC",
                Match.match_id.not_in(["NA1_REMAKE", "NA1_ABORT"]),
            )
        )
        rows = [dict(r._mapping) for r in result]
    assert len(rows) == N_RANKED * 10
    reference = compute_feature_matrix([r["game_duration"] for r in rows], rows).mean(axis=0)
    for j, name in enumerate(FEATURE_NAMES):
        assert means[name] == pytest.approx(reference[j]), name

    # most-recent limit, engine input, empty queue set
    newest = await population_feature_means(engine, scorer, queues=(420,), limit=10)
    assert set(newest) == set(FEATURE_NAMES)
    assert await population_feature_means(engine, scorer, queues=(), limit=10) == {}
    assert await population_feature_means(engine, scorer, queues=(900,), limit=10) == {}

    # cached while the stored matches are unchanged: no second pass over the rows
    calls = 0
    real = registry.feature_matrix_from_result_rows

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(registry, "feature_matrix_from_result_rows", counted)
    assert await population_feature_means(engine, scorer, queues=(420,), limit=10) == newest
    assert calls == 0
    clear_population_cache()
    assert await population_feature_means(engine, scorer, queues=(420,), limit=10) == newest
    assert calls == 1

    # a match stored by another process (poller, import-legacy) invalidates the cache ...
    (late,) = await insert_matches(
        session_factory,
        [signal_match("NA1_LATE", random.Random(99), start=BASE_START + timedelta(days=30))],
    )
    fresh = await population_feature_means(engine, scorer, queues=(420,), limit=10)
    assert calls == 2 and fresh != newest

    # ... and so does one removed by another process (clear-demo)
    async with session_factory() as session, session.begin():
        await session.execute(delete(Match).where(Match.match_id == late))
    assert await population_feature_means(engine, scorer, queues=(420,), limit=10) == newest
    assert calls == 3


def test_scorable_clause_matches_is_scorable():
    from sqlalchemy.dialects import postgresql

    sql = str(
        registry.scorable_match_clause().compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "'CLASSIC'" in sql and "'GameComplete'" in sql and "300" in sql
