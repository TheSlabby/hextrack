"""Helpers shared by the ``test_ai_*`` modules (this module defines no tests).

* :func:`signal_match` builds a match-v5 payload whose stat lines correlate with winning,
  so a model trained on a few dozen of them learns something measurable.
* :func:`insert_matches` stores payloads through ``hextrack.ingest.mapping.map_match``
  (the same rows ingestion writes) without depending on the ingest service.
* :func:`write_model` writes a complete, untrained model version directory.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import torch
from sklearn.preprocessing import StandardScaler
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.db.models import Match, MatchParticipant
from hextrack.hextrack_ai.features import FEATURE_NAMES, FEATURE_SET, compute_feature_matrix
from hextrack.hextrack_ai.inference import META_FILE
from hextrack.hextrack_ai.model import WinPredictionNet
from hextrack.hextrack_ai.train import save_artifacts
from hextrack.ingest.mapping import map_match
from tests.factories import make_match_json, spec

BASE_START = datetime(2026, 3, 1, 18, 0, tzinfo=UTC)
PLAYER_POOL = tuple(f"pool-player-{i:02d}" for i in range(40))


def signal_match(
    match_id: str,
    rng: random.Random,
    *,
    start: datetime,
    queue_id: int = 420,
    game_mode: str = "CLASSIC",
    remake: bool = False,
    end_of_game_result: str | None = "GameComplete",
) -> dict[str, Any]:
    """A 10-player payload where winners tend to have better stat lines."""
    duration = rng.randint(1500, 2400)
    minutes = duration / 60
    winning_team = rng.choice((100, 200))
    puuids = rng.sample(PLAYER_POOL, 10)
    specs = []
    for i, puuid in enumerate(puuids):
        won = (100 if i < 5 else 200) == winning_team
        kills = rng.randint(3, 12) if won else rng.randint(0, 7)
        deaths = rng.randint(0, 5) if won else rng.randint(3, 10)
        assists = rng.randint(4, 16) if won else rng.randint(1, 9)
        gold = int(minutes * (rng.uniform(390, 480) if won else rng.uniform(300, 400)))
        specs.append(
            spec(
                puuid,
                f"Pool{puuid[-2:]}",
                "NA1",
                kills=kills,
                deaths=deaths,
                assists=assists,
                goldEarned=gold,
                turretKills=rng.randint(1, 3) if won else rng.randint(0, 1),
                damageDealtToObjectives=int(minutes * rng.uniform(300 if won else 120, 900)),
                longestTimeSpentLiving=rng.randint(400, 900) if won else rng.randint(150, 600),
            )
        )
    return make_match_json(
        match_id,
        specs,
        queue_id=queue_id,
        duration_s=duration,
        start=start,
        game_mode=game_mode,
        winning_team=winning_team,
        remake=remake,
        end_of_game_result=end_of_game_result,
    )


def signal_matches(
    count: int,
    *,
    seed: int = 7,
    prefix: str = "NA1_",
    first_id: int = 7_000_000_000,
    queue_id: int = 420,
    start: datetime = BASE_START,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    return [
        signal_match(
            f"{prefix}{first_id + i}",
            rng,
            start=start + timedelta(hours=i),
            queue_id=queue_id,
        )
        for i in range(count)
    ]


async def insert_matches(
    session_factory: async_sessionmaker[AsyncSession], raws: Iterable[dict[str, Any]]
) -> list[str]:
    """Map and insert payloads; returns their match ids."""
    mapped = [map_match(raw) for raw in raws]
    if not mapped:
        return []
    async with session_factory() as session:
        await session.execute(insert(Match), [m.match for m in mapped])
        await session.execute(insert(MatchParticipant), [p for m in mapped for p in m.participants])
        await session.commit()
    return [m.match_id for m in mapped]


def mapped_participants(raw: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """``(game_duration, participant column dicts)`` for one payload."""
    mapped = map_match(raw)
    return int(mapped.match["game_duration"]), mapped.participants


def write_model(
    model_dir: Path,
    version: str,
    *,
    trained_at: datetime,
    seed: int = 0,
    feature_names: Sequence[str] = FEATURE_NAMES,
) -> Path:
    """Write an untrained (randomly initialised) but complete model version directory."""
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = WinPredictionNet(len(feature_names))
    durations: list[int] = []
    rows: list[dict[str, Any]] = []
    for raw in signal_matches(6, seed=seed + 100, prefix="FIT_"):
        duration, participants = mapped_participants(raw)
        durations += [duration] * len(participants)
        rows += participants
    scaler = StandardScaler().fit(
        compute_feature_matrix(durations, rows, feature_names=feature_names)
    )
    meta = {
        "version": version,
        "feature_set": FEATURE_SET,
        "feature_names": list(feature_names),
        "n_features": len(feature_names),
        "trained_at": trained_at.isoformat(),
        "metrics": {"val_auc": 0.5, "val_accuracy": 0.5, "val_loss": 0.693},
    }
    version_dir = model_dir / version
    save_artifacts(version_dir, model=model, scaler=scaler, meta=meta)
    return version_dir


def rewrite_meta(version_dir: Path, **changes: Any) -> None:
    path = version_dir / META_FILE
    meta = json.loads(path.read_text())
    meta.update(changes)
    path.write_text(json.dumps(meta))
