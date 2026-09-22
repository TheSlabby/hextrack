"""Bot outbox events: vocabulary, payload builders and :func:`enqueue_event`.

Ingestion writes rows to ``bot_events`` in the same transaction as the data that caused
them; the Discord bot consumes them later without making any Riot calls, so every payload
carries everything an embed needs. All values are JSON types; datetimes are ISO-8601
strings with a UTC offset.

``tier_up`` / ``tier_down`` (see :func:`tier_event_payload`)::

    {"puuid", "game_name", "tag_line", "platform", "profile_icon_id", "queue_type",
     "old": {"tier", "rank", "lp"}, "new": {"tier", "rank", "lp"},
     "wins", "losses", "rank_value",
     # when the standing the change is measured against was taken (ISO | None), so a
     # consumer can tell a promotion that just happened from a long-stale comparison:
     "previous_taken_at",
     # flat aliases of the nested values, for convenience:
     "old_tier", "old_rank", "new_tier", "new_rank", "lp"}

``rank`` is None for MASTER / GRANDMASTER / CHALLENGER.

``new_match`` / ``great_game`` / ``bad_game`` (see :func:`game_event_payload`)::

    {"puuid", "game_name", "tag_line", "profile_icon_id", "match_id", "queue_id",
     "champion_id", "champion_name", "team_position", "win", "remake",
     "kills", "deaths", "assists", "kda", "ai_score" (float | None), "model_version",
     "game_start" (ISO), "game_duration" (seconds)}

When they fire (for tracked players only, on newly stored matches whose game ended within
:data:`GAME_EVENT_MAX_AGE`): ``new_match`` always; ``great_game`` when
``(kills + assists) / max(deaths, 1) > GREAT_GAME_KDA``; ``bad_game`` when that KDA is below
:data:`BAD_GAME_KDA` and ``deaths > 0`` (the bot decides whether to post bad games).
Remakes only produce ``new_match``. ``tier_up`` / ``tier_down`` fire when a tracked player's
tier changes between two rank snapshots of the same queue.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.repo import events as events_repo

EventKind = Literal["tier_up", "tier_down", "great_game", "bad_game", "new_match"]
EVENT_KINDS: Final[tuple[str, ...]] = (
    "tier_up",
    "tier_down",
    "great_game",
    "bad_game",
    "new_match",
)
#: KDA strictly above this triggers ``great_game`` (LPBot parity).
GREAT_GAME_KDA: Final = 6.0
#: KDA strictly below this (with at least one death) triggers ``bad_game``.
BAD_GAME_KDA: Final = 1.0
#: Game events are only enqueued for games that ended at most this long ago, so a season
#: backfill (or a worker catching up after downtime) never floods Discord with old games.
#: Matches the bot's policy of dropping outbox rows older than 6 hours.
GAME_EVENT_MAX_AGE: Final = timedelta(hours=6)


def kda(kills: int, deaths: int, assists: int) -> float:
    """``(kills + assists) / max(deaths, 1)``."""
    return (kills + assists) / max(deaths, 1)


def is_great_game(kills: int, deaths: int, assists: int) -> bool:
    return kda(kills, deaths, assists) > GREAT_GAME_KDA


def is_bad_game(kills: int, deaths: int, assists: int) -> bool:
    return deaths > 0 and kda(kills, deaths, assists) < BAD_GAME_KDA


def _rank_dict(tier: str | None, rank: str | None, lp: int | None) -> dict[str, Any]:
    return {"tier": tier, "rank": rank, "lp": lp}


def tier_event_payload(
    *,
    puuid: str,
    game_name: str,
    tag_line: str,
    platform: str,
    profile_icon_id: int | None,
    queue_type: str,
    old_tier: str,
    old_rank: str | None,
    old_lp: int,
    new_tier: str,
    new_rank: str | None,
    new_lp: int,
    wins: int,
    losses: int,
    rank_value: int,
    previous_taken_at: datetime | None = None,
) -> dict[str, Any]:
    """Payload for ``tier_up`` / ``tier_down`` (see the module docstring)."""
    return {
        "puuid": puuid,
        "game_name": game_name,
        "tag_line": tag_line,
        "platform": platform,
        "profile_icon_id": profile_icon_id,
        "queue_type": queue_type,
        "old": _rank_dict(old_tier, old_rank, old_lp),
        "new": _rank_dict(new_tier, new_rank, new_lp),
        "wins": wins,
        "losses": losses,
        "rank_value": rank_value,
        "previous_taken_at": previous_taken_at.isoformat() if previous_taken_at else None,
        "old_tier": old_tier,
        "old_rank": old_rank,
        "new_tier": new_tier,
        "new_rank": new_rank,
        "lp": new_lp,
    }


def game_event_payload(
    *,
    puuid: str,
    game_name: str | None,
    tag_line: str | None,
    profile_icon_id: int | None,
    match_id: str,
    queue_id: int,
    champion_id: int,
    champion_name: str,
    team_position: str,
    win: bool,
    remake: bool,
    kills: int,
    deaths: int,
    assists: int,
    ai_score: float | None,
    model_version: str | None,
    game_start: datetime,
    game_duration: int,
) -> dict[str, Any]:
    """Payload for ``new_match`` / ``great_game`` / ``bad_game`` (see the module docstring)."""
    return {
        "puuid": puuid,
        "game_name": game_name,
        "tag_line": tag_line,
        "profile_icon_id": profile_icon_id,
        "match_id": match_id,
        "queue_id": queue_id,
        "champion_id": champion_id,
        "champion_name": champion_name,
        "team_position": team_position,
        "win": win,
        "remake": remake,
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "kda": round(kda(kills, deaths, assists), 4),
        "ai_score": ai_score,
        "model_version": model_version,
        "game_start": game_start.isoformat(),
        "game_duration": game_duration,
    }


def _jsonable(value: Any, path: str) -> Any:
    """Convert ``value`` to plain JSON types, or raise ValueError naming the bad key."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"event payload {path} is not a finite number: {value!r}")
        return value
    if isinstance(value, Decimal):
        return _jsonable(float(value), path)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"event payload {path} has a non-string key {key!r}")
            out[key] = _jsonable(item, f"{path}.{key}")
        return out
    if isinstance(value, list | tuple):
        return [_jsonable(item, f"{path}[{i}]") for i, item in enumerate(value)]
    raise ValueError(f"event payload {path} is not JSON-serialisable: {type(value).__name__}")


async def enqueue_event(session: AsyncSession, kind: EventKind, payload: dict[str, Any]) -> None:
    """Insert a pending ``bot_events`` row (not committed). Raises ValueError for an
    unknown ``kind`` or a payload that is not JSON-serialisable (datetimes are converted
    to ISO strings)."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown bot event kind {kind!r}; expected one of {EVENT_KINDS}")
    if not isinstance(payload, Mapping):
        raise ValueError("event payload must be a JSON object")
    await events_repo.insert_event(session, kind, _jsonable(payload, "payload"))
