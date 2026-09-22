"""Model registry: activation, batch rescoring and population statistics (owner: B3).

Each trained model lives in ``settings.model_dir / <version>`` (model.pth, scaler.pkl,
meta.json, train_curve.png). ``settings.model_dir / "ACTIVE"`` names the active version;
that is what :meth:`~hextrack.hextrack_ai.inference.Scorer.load` reads, and
``ai_models.is_active`` mirrors it in the database. Running processes pick up a newly
activated model on restart.

Activation and rescoring belong together: every stored average, trend and leaderboard score
counts only the rows whose ``model_version`` is the active one (see
:func:`hextrack.stats.queries.resolve_model_version`), so a model that is active but has not
scored the stored games yet blanks the whole AI Score UI. :func:`activate` therefore runs
:func:`rescore` right after the switch unless the caller opts out.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
from sqlalchemy import ColumnElement, Engine, Select, and_, exists, func, or_, select, update
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from hextrack.config import Settings
from hextrack.db.engine import make_sync_engine, make_sync_session_factory
from hextrack.db.models import AiModel, Match, MatchParticipant
from hextrack.hextrack_ai.features import (
    TEAM_DEATHS_KEY,
    TEAM_KILLS_KEY,
    feature_matrix_from_columns,
    needs_team_totals,
    required_columns,
)
from hextrack.hextrack_ai.inference import (
    ACTIVE_FILE,
    Scorer,
    is_plain_version_name,
    read_active_version,
    read_meta,
)
from hextrack.ingest.mapping import CLASSIC, GAME_COMPLETE, MIN_COMPLETE_DURATION_SECONDS
from hextrack.queues import RANKED_QUEUES

logger = logging.getLogger(__name__)

#: Matches per transaction in :func:`rescore` (about 10x as many participant rows).
RESCORE_CHUNK_MATCHES: Final = 500
#: How long :func:`population_feature_means` results are reused when the stored matches have
#: not changed (see :func:`_fingerprint`).
POPULATION_CACHE_TTL_SECONDS: Final = 900.0
_POPULATION_CACHE_MAX_ENTRIES: Final = 32


@dataclass(slots=True)
class ModelInfo:
    version: str
    trained_at: datetime
    is_active: bool
    n_features: int
    metrics: dict[str, Any] = field(default_factory=dict)
    #: Participant rows re-scored by :func:`activate` (None when it did not rescore).
    rescored_rows: int | None = None


class UnknownModelVersion(Exception):
    """No artifacts / ai_models row for the requested version."""


class NoActiveModel(Exception):
    """There is no loadable active model in ``settings.model_dir``."""


# --- shared SQL --------------------------------------------------------------------------


def scorable_match_clause() -> ColumnElement[bool]:
    """SQL equivalent of :func:`hextrack.ingest.mapping.is_scorable` on ``matches``."""
    return and_(
        Match.game_mode == CLASSIC,
        Match.remake.is_(False),
        or_(
            Match.end_of_game_result == GAME_COMPLETE,
            and_(
                Match.end_of_game_result.is_(None),
                Match.game_duration > MIN_COMPLETE_DURATION_SECONDS,
            ),
        ),
    )


def participant_feature_columns(feature_names: Collection[str]) -> list[Any]:
    """Selectable ``match_participants`` columns for ``feature_names``, plus labelled
    ``team_kills`` / ``team_deaths`` window sums when the participation features are used
    (the window must run over whole matches, i.e. before any LIMIT on participants)."""
    table = MatchParticipant.__table__
    cols: list[Any] = [table.c[name] for name in required_columns(tuple(feature_names))]
    if needs_team_totals(tuple(feature_names)):
        team = (MatchParticipant.match_id, MatchParticipant.team_id)
        cols.append(func.sum(MatchParticipant.kills).over(partition_by=team).label(TEAM_KILLS_KEY))
        cols.append(
            func.sum(MatchParticipant.deaths).over(partition_by=team).label(TEAM_DEATHS_KEY)
        )
    return cols


def feature_matrix_from_result_rows(
    rows: Collection[Any],
    feature_names: Collection[str],
    *,
    duration_key: str = "game_duration",
) -> np.ndarray:
    """Feature matrix for SQL result rows selected with :func:`participant_feature_columns`
    plus a ``game_duration`` column."""
    names = tuple(feature_names)
    mappings = [row._mapping for row in rows]
    n = len(mappings)

    def column(key: str) -> np.ndarray:
        return np.fromiter((float(m[key] or 0) for m in mappings), dtype=np.float64, count=n)

    columns = {name: column(name) for name in required_columns(names)}
    team_kills = team_deaths = None
    if needs_team_totals(names):
        team_kills, team_deaths = column(TEAM_KILLS_KEY), column(TEAM_DEATHS_KEY)
    return feature_matrix_from_columns(
        column(duration_key),
        columns,
        feature_names=names,
        team_kills=team_kills,
        team_deaths=team_deaths,
    )


# --- activation ----------------------------------------------------------------------------


def _write_active_file(model_dir: Path, version: str | None) -> None:
    """Atomically replace ``model_dir/ACTIVE`` (``None`` removes it)."""
    target = model_dir / ACTIVE_FILE
    if version is None:
        with contextlib.suppress(FileNotFoundError):
            target.unlink()
        return
    tmp = model_dir / f".{ACTIVE_FILE}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        tmp.write_text(version + "\n", encoding="utf-8")
        os.replace(tmp, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def _model_row_from_meta(version: str, meta: dict[str, Any], scorer: Scorer) -> AiModel:
    metrics = meta.get("metrics")
    return AiModel(
        version=version,
        feature_names=list(scorer.feature_names),
        metrics=dict(metrics) if isinstance(metrics, dict) else {},
        trained_at=scorer.trained_at or datetime.now(UTC),
        is_active=False,
    )


def _info(row: AiModel) -> ModelInfo:
    return ModelInfo(
        version=row.version,
        trained_at=row.trained_at,
        is_active=row.is_active,
        n_features=len(row.feature_names or ()),
        metrics=dict(row.metrics or {}),
    )


def activate(settings: Settings, version: str, *, rescore_stored: bool = True) -> ModelInfo:
    """Make ``version`` the active model: point ``model_dir/ACTIVE`` at its directory,
    flip ``ai_models.is_active`` (inserting the row from meta.json if it is missing) and,
    unless ``rescore_stored`` is off, score the stored games with it right away
    (:func:`rescore`, reported as ``ModelInfo.rescored_rows``).

    Rescoring is on by default because averages, trends and leaderboards only count rows
    scored by the active model: skipping it leaves the AI Score UI empty until someone runs
    ``hextrack model rescore``.

    Raises :class:`UnknownModelVersion` when there are no artifacts for ``version`` and
    :class:`~hextrack.hextrack_ai.inference.ModelLoadError` when they cannot be used with
    this build (e.g. a different feature set). Running processes pick the model up on
    restart.
    """
    version = version.strip()
    model_dir = settings.model_dir
    version_dir = model_dir / version
    if not is_plain_version_name(version) or not version_dir.is_dir():
        raise UnknownModelVersion(f"no artifacts for model {version!r} in {model_dir}")
    scorer = Scorer.from_version_dir(version_dir)  # validates compatibility
    meta = read_meta(version_dir)

    engine = make_sync_engine(settings)
    previous = read_active_version(model_dir)
    wrote_file = False
    try:
        factory = make_sync_session_factory(engine)
        with factory() as session, session.begin():
            row = session.get(AiModel, version, with_for_update=True)
            if row is None:
                row = _model_row_from_meta(version, meta, scorer)
                session.add(row)
                session.flush()
            # Two statements so the partial unique index never sees two active rows.
            session.execute(
                update(AiModel)
                .where(AiModel.is_active.is_(True), AiModel.version != version)
                .values(is_active=False)
            )
            session.execute(
                update(AiModel).where(AiModel.version == version).values(is_active=True)
            )
            session.refresh(row)
            info = _info(row)
            _write_active_file(model_dir, version)
            wrote_file = True
            # the transaction commits when the ``begin()`` block exits
    except BaseException:
        if wrote_file and previous != version:
            with contextlib.suppress(OSError):
                _write_active_file(model_dir, previous)
        raise
    finally:
        engine.dispose()
    logger.info("activated AI model %s", version)
    if rescore_stored:
        info.rescored_rows = _rescore_for_activation(settings, scorer)
    return info


def _rescore_for_activation(settings: Settings, scorer: Scorer) -> int:
    """Bring the stored scores in line with a just-activated model."""
    logger.info("re-scoring stored games with model %s", scorer.version)
    try:
        return rescore(settings, all_rows=False, scorer=scorer)
    except BaseException:
        logger.error(
            "model %s is active but re-scoring the stored games did not finish; AI averages "
            "and trends stay empty until `hextrack model rescore` completes",
            scorer.version,
        )
        raise


def list_models(settings: Settings) -> list[ModelInfo]:
    """All ``ai_models`` rows, newest first."""
    engine = make_sync_engine(settings)
    try:
        with Session(engine) as session:
            rows = session.scalars(
                select(AiModel).order_by(AiModel.trained_at.desc(), AiModel.version.desc())
            ).all()
            return [_info(row) for row in rows]
    finally:
        engine.dispose()


# --- rescoring ------------------------------------------------------------------------------


def _load_active_scorer(settings: Settings) -> Scorer:
    scorer = Scorer.load(settings.model_dir)
    if scorer is None:
        raise NoActiveModel(
            f"no usable AI model in {settings.model_dir}; run `hextrack train --activate` "
            "or `hextrack model activate VERSION`"
        )
    return scorer


def _warn_if_db_disagrees(factory: sessionmaker[Session], version: str) -> None:
    with factory() as session:
        active = session.scalar(select(AiModel.version).where(AiModel.is_active.is_(True)))
    if active != version:
        logger.warning(
            "model_dir says the active model is %s but ai_models.is_active says %s; "
            "run `hextrack model activate %s` to reconcile",
            version,
            active,
            version,
        )


def _rescore_chunk(
    session: Session,
    scorer: Scorer,
    match_rows: list[Any],
    feature_columns: list[Any],
) -> int:
    durations = {row.match_id: row.game_duration for row in match_rows}
    ids = list(durations)
    rows = session.execute(
        select(
            MatchParticipant.match_id,
            MatchParticipant.puuid,
            Match.game_duration,
            *feature_columns,
        )
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(MatchParticipant.match_id.in_(ids))
    ).all()
    if not rows:
        return 0
    features = feature_matrix_from_result_rows(rows, scorer.feature_names)
    probs = scorer.probabilities(scorer.logits_from_scaled(scorer.scale(features)))
    now = datetime.now(UTC)
    session.execute(
        update(MatchParticipant),
        [
            {
                "match_id": row.match_id,
                "puuid": row.puuid,
                "ai_score": float(prob),
                "ai_scored_at": now,
                "model_version": scorer.version,
            }
            for row, prob in zip(rows, probs, strict=True)
        ],
    )
    session.execute(
        update(Match)
        .where(Match.match_id.in_(ids))
        .values(scored_at=now, model_version=scorer.version)
    )
    return len(rows)


def rescore(
    settings: Settings,
    *,
    all_rows: bool,
    chunk_matches: int = RESCORE_CHUNK_MATCHES,
    scorer: Scorer | None = None,
) -> int:
    """Score participants with the active model: unscored/other-version rows only, or every
    scorable row when ``all_rows``. Returns the number of participant rows updated.

    Works match by match (all participants of a match get the same model version, and
    ``matches.scored_at`` / ``matches.model_version`` are set), committing every
    ``chunk_matches`` matches. ``scorer`` (the model :func:`activate` has just loaded)
    saves reading the artifacts again; without it the active model is loaded, which raises
    :class:`NoActiveModel` when there is none.
    """
    if chunk_matches < 1:
        raise ValueError("chunk_matches must be positive")
    scorer = scorer if scorer is not None else _load_active_scorer(settings)
    version = scorer.version
    feature_columns = participant_feature_columns(scorer.feature_names)
    engine = make_sync_engine(settings)
    total = 0
    n_matches = 0
    last_id = ""
    try:
        factory = make_sync_session_factory(engine)
        _warn_if_db_disagrees(factory, version)
        while True:
            stmt = select(Match.match_id, Match.game_duration).where(
                scorable_match_clause(), Match.match_id > last_id
            )
            if not all_rows:
                stale_participant = exists().where(
                    MatchParticipant.match_id == Match.match_id,
                    or_(
                        MatchParticipant.ai_score.is_(None),
                        MatchParticipant.model_version.is_distinct_from(version),
                    ),
                )
                stmt = stmt.where(
                    or_(
                        stale_participant,
                        Match.scored_at.is_(None),
                        Match.model_version.is_distinct_from(version),
                    )
                )
            stmt = stmt.order_by(Match.match_id).limit(chunk_matches)
            with factory() as session, session.begin():
                match_rows = list(session.execute(stmt).all())
                if not match_rows:
                    break
                total += _rescore_chunk(session, scorer, match_rows, feature_columns)
            n_matches += len(match_rows)
            last_id = match_rows[-1].match_id
            logger.info("rescored %d participant rows in %d matches so far", total, n_matches)
    finally:
        engine.dispose()
    logger.info("rescore with model %s done: %d rows, %d matches", version, total, n_matches)
    return total


# --- population statistics ----------------------------------------------------------------


#: Identifies the stored matches a cached result was computed from: (count, newest start).
Fingerprint = tuple[int, str]


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    at: float
    fingerprint: Fingerprint
    values: dict[str, float]


_population_cache: dict[tuple[str, str, tuple[int, ...], int], _CacheEntry] = {}


def clear_population_cache() -> None:
    """Forget cached :func:`population_feature_means` results."""
    _population_cache.clear()


def _bind_key(session_or_engine: AsyncSession | AsyncEngine) -> str:
    if isinstance(session_or_engine, AsyncEngine):
        url = session_or_engine.url
    else:
        bind: Engine | Any = session_or_engine.get_bind()
        url = getattr(bind, "engine", bind).url
    return url.render_as_string(hide_password=True)


def _fingerprint_stmt(queue_key: tuple[int, ...]) -> Select[tuple[int, datetime | None]]:
    """How many matches of these queues are stored and when the newest one started.

    One index scan over ``ix_matches_queue_id_game_start``. Any ingest, import or delete in
    another process (``clear-demo``, ``import-legacy``, the poller) moves it, which is what
    makes cached means fall out of date.
    """
    return select(func.count(), func.max(Match.game_start)).where(Match.queue_id.in_(queue_key))


async def _fingerprint(
    conn: AsyncSession | AsyncConnection, queue_key: tuple[int, ...]
) -> Fingerprint:
    count, newest = (await conn.execute(_fingerprint_stmt(queue_key))).one()
    return int(count or 0), "" if newest is None else newest.isoformat()


async def population_feature_means(
    session: AsyncSession | AsyncEngine,
    scorer: Scorer,
    *,
    queues: Collection[int] = RANKED_QUEUES,
    limit: int = 5000,
) -> dict[str, float]:
    """Mean raw feature values over the most recent ``limit`` scorable participant rows,
    keyed by feature name (used for AiExplain.population_value).

    ``session`` may also be an ``AsyncEngine``. Results are cached in memory per database,
    model version, queue set and limit for at most :data:`POPULATION_CACHE_TTL_SECONDS`, and
    only while the stored matches still have the fingerprint they were computed from, so a
    CLI command that changes the data in another process cannot leave the API serving
    averages from games that are gone. Returns ``{}`` when there are no rows (not cached, so
    data shows up as soon as it exists).
    """
    queue_key = tuple(sorted({int(q) for q in queues}))
    if not queue_key or limit < 1:
        return {}
    if isinstance(session, AsyncEngine):
        async with session.connect() as conn:
            return await _population_feature_means(conn, session.url, scorer, queue_key, limit)
    return await _population_feature_means(session, None, scorer, queue_key, limit)


async def _population_feature_means(
    conn: AsyncSession | AsyncConnection,
    url: URL | None,
    scorer: Scorer,
    queue_key: tuple[int, ...],
    limit: int,
) -> dict[str, float]:
    key = (
        url.render_as_string(hide_password=True) if url is not None else _bind_key(conn),
        scorer.version,
        queue_key,
        int(limit),
    )
    now = time.monotonic()
    fingerprint = await _fingerprint(conn, queue_key)
    cached = _population_cache.get(key)
    if (
        cached is not None
        and cached.fingerprint == fingerprint
        and now - cached.at < POPULATION_CACHE_TTL_SECONDS
    ):
        return dict(cached.values)

    stmt = (
        select(Match.game_duration, *participant_feature_columns(scorer.feature_names))
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(scorable_match_clause(), Match.queue_id.in_(queue_key))
        .order_by(MatchParticipant.game_start.desc(), MatchParticipant.match_id.desc())
        .limit(int(limit))
    )
    rows = (await conn.execute(stmt)).all()
    if not rows:
        return {}

    matrix = feature_matrix_from_result_rows(rows, scorer.feature_names)
    means = matrix.mean(axis=0)
    values = {name: float(means[j]) for j, name in enumerate(scorer.feature_names)}
    if len(_population_cache) >= _POPULATION_CACHE_MAX_ENTRIES:
        oldest = min(_population_cache, key=lambda k: _population_cache[k].at)
        _population_cache.pop(oldest, None)
    _population_cache[key] = _CacheEntry(at=now, fingerprint=fingerprint, values=values)
    return dict(values)
