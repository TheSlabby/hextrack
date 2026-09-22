"""AI Score trend and explanation routes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query
from starlette.concurrency import run_in_threadpool

from hextrack.api.deps import SAFE_TEXT, OptionalScorerDep, ScorerDep, SessionDep, error_responses
from hextrack.api.schemas import AiExplain, AiTrend, AiTrendPoint, FeatureAttribution
from hextrack.api.v1.summoners import require_summoner
from hextrack.hextrack_ai import explain, inference, registry
from hextrack.hextrack_ai.inference import Scorer
from hextrack.stats import queries
from hextrack.stats.metrics import average, clamp_rate

router = APIRouter(prefix="/summoners", tags=["ai"])

Puuid = Annotated[str, Path(min_length=1, max_length=100, pattern=SAFE_TEXT)]


def _attribution(item: Mapping[str, Any]) -> FeatureAttribution:
    """Build the response model from an ``explain_player`` dict (extra keys ignored)."""
    return FeatureAttribution(**{name: item.get(name) for name in FeatureAttribution.model_fields})


def _explain(
    scorer: Scorer,
    durations: Sequence[int],
    rows: Sequence[Mapping[str, Any]],
    population: Mapping[str, float] | None,
) -> tuple[list[dict[str, Any]], float | None]:
    """CPU-bound model work (run in a worker thread)."""
    attributions = explain.explain_player(scorer, durations, rows, population) if rows else []
    return attributions, explain.base_score(scorer)


@router.get(
    "/{puuid}/ai-trend",
    response_model=AiTrend,
    summary="Stored AI scores over recent games (works without a loaded model)",
    responses=error_responses(404),
)
async def get_ai_trend(
    puuid: Puuid,
    session: SessionDep,
    scorer: OptionalScorerDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 40,
) -> AiTrend:
    await require_summoner(session, puuid)
    version = await queries.resolve_model_version(session, scorer, puuid=puuid)
    rows = (
        await queries.ai_trend_rows(session, puuid, model_version=version, limit=limit)
        if version is not None
        else []
    )
    points = [
        AiTrendPoint(
            match_id=row["match_id"],
            game_start=row["game_start"],
            champion_name=row["champion_name"],
            win=bool(row["win"]),
            ai_score=clamp_rate(row["ai_score"]),
        )
        for row in rows
    ]
    return AiTrend(
        puuid=puuid,
        model_version=version,
        average=clamp_rate(average(p.ai_score for p in points)),
        points=points,
    )


@router.get(
    "/{puuid}/ai-explain",
    response_model=AiExplain,
    summary="Which stats drive this player's AI Score (gradient x input)",
    responses=error_responses(404, 503),
)
async def get_ai_explain(
    puuid: Puuid,
    session: SessionDep,
    scorer: ScorerDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
) -> AiExplain:
    await require_summoner(session, puuid)
    matches = await queries.explain_rows(session, puuid, limit=limit)
    durations = [duration for _, duration in matches]
    rows = [inference.participant_to_dict(participant) for participant, _ in matches]
    # Cached per model version inside the registry; an empty dict means "no population".
    population = await registry.population_feature_means(session, scorer) if rows else None
    attributions, base = await run_in_threadpool(_explain, scorer, durations, rows, population)
    features = sorted(
        (_attribution(item) for item in attributions),
        key=lambda f: (-f.mean_abs_attribution, f.feature),
    )
    return AiExplain(
        puuid=puuid,
        model_version=scorer.version,
        n_matches=len(rows),
        base_score=clamp_rate(base),
        features=features,
    )
