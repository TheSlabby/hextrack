"""GET /meta: static data the frontend needs at startup."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Final

from fastapi import APIRouter

from hextrack.api.deps import DDragonDep, OptionalScorerDep, SettingsDep
from hextrack.api.schemas import Meta
from hextrack.hextrack_ai.inference import Scorer
from hextrack.queues import queue_labels_json
from hextrack.riot.ddragon import CDN, FALLBACK_VERSION, DDragon

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta"])

#: /meta is on the frontend's startup path: never wait long for Data Dragon.
DDRAGON_TIMEOUT_SECONDS: Final = 3.0


async def ddragon_version(ddragon: DDragon) -> str:
    """Latest Data Dragon version, or :data:`FALLBACK_VERSION` if it cannot be fetched."""
    try:
        version = await asyncio.wait_for(ddragon.latest_version(), DDRAGON_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("meta: Data Dragon version unavailable (%s); using fallback", exc)
        return FALLBACK_VERSION
    return version if isinstance(version, str) and version.strip() else FALLBACK_VERSION


def _trained_at(scorer: Scorer | None) -> datetime | None:
    if scorer is None:
        return None
    try:
        return scorer.trained_at
    except Exception as exc:
        logger.warning("meta: model trained_at unavailable (%s)", exc)
        return None


@router.get("/meta", response_model=Meta, summary="Data Dragon version, region, queues")
async def get_meta(settings: SettingsDep, ddragon: DDragonDep, scorer: OptionalScorerDep) -> Meta:
    return Meta(
        ddragon_version=await ddragon_version(ddragon),
        ddragon_cdn=CDN,
        platform=settings.riot_platform,
        region=settings.riot_region,
        season_start=settings.season_start,
        model_version=scorer.version if scorer is not None else None,
        model_trained_at=_trained_at(scorer),
        queues=queue_labels_json(),
    )
