"""Match detail route."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from hextrack.api.deps import SAFE_TEXT, ApiError, SessionDep, error_responses
from hextrack.api.schemas import MatchDetail
from hextrack.stats import queries

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
) -> MatchDetail:
    detail = await queries.match_detail(session, match_id)
    if detail is None:
        raise ApiError(404, f"Match {match_id} not found", "not_found")
    return detail
