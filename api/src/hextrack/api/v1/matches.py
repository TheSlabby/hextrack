"""Match detail route."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query
from fastapi.concurrency import run_in_threadpool

from hextrack.api.deps import (
    SAFE_TEXT,
    ApiError,
    OptionalScorerDep,
    ScorerDep,
    SessionDep,
    error_responses,
)
from hextrack.api.schemas import FeatureAttribution, MatchAiExplain, MatchDetail
from hextrack.hextrack_ai import explain, inference, registry
from hextrack.hextrack_ai.inference import Scorer
from hextrack.stats import queries
from hextrack.stats.metrics import clamp_rate
from hextrack.stats.role_percentile import ROLE_PERCENTILES

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get(
    "/{match_id}",
    response_model=MatchDetail,
    summary="Both teams, objectives, bans and AI scores for one stored match",
    responses=error_responses(404),
)
async def get_match(
    match_id: Annotated[
        str, Path(min_length=1, max_length=64, pattern=SAFE_TEXT, examples=["NA1_5012345678"])
    ],
    session: SessionDep,
    scorer: OptionalScorerDep,
) -> MatchDetail:
    version = await queries.resolve_model_version(session, scorer)
    table = await ROLE_PERCENTILES.ensure_loaded(session, model_version=version)
    detail = await queries.match_detail(session, match_id, role_percentiles=table)
    if detail is None:
        raise ApiError(404, f"Match {match_id} not found", "not_found")
    return detail


@router.get(
    "/{match_id}/ai-explain",
    response_model=MatchAiExplain,
    summary="Which stats moved one player's AI Score in this game",
    responses=error_responses(404, 409, 503),
)
async def get_match_ai_explain(
    match_id: Annotated[
        str, Path(min_length=1, max_length=64, pattern=SAFE_TEXT, examples=["NA1_5012345678"])
    ],
    puuid: Annotated[str, Query(min_length=1, max_length=100, pattern=SAFE_TEXT)],
    session: SessionDep,
    scorer: ScorerDep,
) -> MatchAiExplain:
    found = await queries.explain_row(session, match_id, puuid)
    if found is None:
        raise ApiError(404, f"{puuid} didn't play in {match_id}", "not_found")
    participant, duration, scorable = found
    if not scorable:
        # Remakes, Arena and other modes have no AI Score to explain.
        raise ApiError(409, "This game isn't scored by the AI model", "not_scorable")
    row = inference.participant_to_dict(participant)
    population = await registry.population_feature_means(session, scorer)
    attributions, base, score = await run_in_threadpool(
        _explain_game, scorer, duration, row, population
    )
    features = sorted(
        (
            FeatureAttribution(**{k: item.get(k) for k in FeatureAttribution.model_fields})
            for item in attributions
        ),
        key=lambda f: (-f.mean_abs_attribution, f.feature),
    )
    return MatchAiExplain(
        match_id=match_id,
        puuid=puuid,
        model_version=scorer.version,
        win=bool(participant.win),
        base_score=clamp_rate(base),
        score=clamp_rate(score),
        stored_score=clamp_rate(participant.ai_score) if participant.ai_score is not None else None,
        features=features,
    )


def _explain_game(
    scorer: Scorer,
    duration: int,
    row: Mapping[str, Any],
    population: Mapping[str, float] | None,
) -> tuple[list[dict[str, Any]], float | None, float]:
    """CPU-bound model work for one stat line (run in a worker thread)."""
    attributions = explain.explain_player(scorer, [duration], [row], population)
    score = float(scorer.score_rows([duration], [row])[0])
    return attributions, explain.base_score(scorer), score
