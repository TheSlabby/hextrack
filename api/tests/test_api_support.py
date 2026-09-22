"""Seeding helpers shared by the ``test_api_*`` modules (this module has no tests).

Rows are written directly: match payloads from :mod:`tests.factories` go through
:func:`hextrack.ingest.mapping.map_match` and plain INSERTs, never through the ingest
service, so the API tests only exercise the read side.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import AiModel, Match, MatchParticipant, RankSnapshot, Summoner
from hextrack.ingest.mapping import MappedMatch, map_match
from hextrack.rank import rank_value

SCORED_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)


async def add_summoner(
    session: AsyncSession,
    puuid: str,
    game_name: str,
    tag_line: str,
    *,
    tracked: bool = False,
    platform: str = "na1",
    profile_icon_id: int | None = 29,
    summoner_level: int | None = 100,
    tracked_since: datetime | None = None,
    last_refreshed_at: datetime | None = None,
) -> Summoner:
    summoner = Summoner(
        puuid=puuid,
        game_name=game_name,
        tag_line=tag_line,
        platform=platform,
        profile_icon_id=profile_icon_id,
        summoner_level=summoner_level,
        is_tracked=tracked,
        tracked_since=tracked_since or (datetime(2026, 1, 1, tzinfo=UTC) if tracked else None),
        last_refreshed_at=last_refreshed_at,
    )
    session.add(summoner)
    await session.flush()
    return summoner


async def add_match(
    session: AsyncSession,
    raw: dict[str, Any],
    *,
    scores: Mapping[str, float] | None = None,
    model_version: str = "v1",
    scored_at: datetime = SCORED_AT,
) -> MappedMatch:
    """Insert one mapped match; ``scores`` (puuid -> AI Score) are stored with
    ``model_version``."""
    mapped = map_match(raw)
    await session.execute(insert(Match).values(**mapped.match))
    rows = []
    for participant in mapped.participants:
        row = dict(participant)
        if scores and participant["puuid"] in scores:
            row.update(
                ai_score=scores[participant["puuid"]],
                model_version=model_version,
                ai_scored_at=scored_at,
            )
        rows.append(row)
    await session.execute(insert(MatchParticipant), rows)
    return mapped


def score_all(raw: dict[str, Any], base: float = 0.3, step: float = 0.05) -> dict[str, float]:
    """Distinct scores for every participant of ``raw``: slot i gets ``base + i * step``."""
    return {p["puuid"]: base + i * step for i, p in enumerate(raw["info"]["participants"])}


async def add_rank(
    session: AsyncSession,
    puuid: str,
    queue_type: str,
    tier: str,
    rank: str | None,
    lp: int,
    *,
    taken_at: datetime,
    wins: int = 10,
    losses: int = 10,
) -> RankSnapshot:
    snapshot = RankSnapshot(
        puuid=puuid,
        queue_type=queue_type,
        tier=tier,
        rank=rank,
        lp=lp,
        wins=wins,
        losses=losses,
        rank_value=rank_value(tier, rank, lp),
        taken_at=taken_at,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def add_model(session: AsyncSession, version: str, *, active: bool = True) -> AiModel:
    model = AiModel(
        version=version,
        feature_names=["kills_per_min"],
        metrics={"val_auc": 0.8},
        trained_at=datetime(2026, 9, 1, tzinfo=UTC),
        is_active=active,
    )
    session.add(model)
    await session.flush()
    return model


class StubScorer:
    """Stands in for a loaded :class:`hextrack.hextrack_ai.inference.Scorer`."""

    def __init__(self, version: str = "v1") -> None:
        self.version = version
        self.meta: dict[str, Any] = {}
        self.feature_names = ["kills_per_min", "vision_per_min"]

    @property
    def trained_at(self) -> datetime:
        return datetime(2026, 9, 1, 12, tzinfo=UTC)

    @property
    def n_features(self) -> int:
        return len(self.feature_names)


class FakeDDragon:
    """Data Dragon stand-in for /meta (never touches the network)."""

    def __init__(self, version: str | None = "16.19.1", error: Exception | None = None) -> None:
        self.version = version
        self.error = error
        self.calls = 0

    async def latest_version(self) -> str | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.version

    async def aclose(self) -> None:
        return None
