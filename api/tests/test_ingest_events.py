"""ingest.events: the outbox vocabulary, payload builders and enqueue_event."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from hextrack.db.repo import events as events_repo
from hextrack.ingest import events
from tests.test_ingest_support import events_of


async def test_enqueue_event_inserts_a_pending_row(session):
    started = datetime(2026, 9, 20, 18, 30, tzinfo=UTC)
    await events.enqueue_event(
        session,
        "great_game",
        {"puuid": "p", "game_start": started, "kda": Decimal("7.5"), "items": (1, 2)},
    )
    await session.commit()

    (row,) = await events_of(session)
    assert row.kind == "great_game"
    assert row.payload == {
        "puuid": "p",
        "game_start": "2026-09-20T18:30:00+00:00",
        "kda": 7.5,
        "items": [1, 2],
    }
    assert row.processed_at is None and row.attempts == 0 and row.created_at is not None
    assert await events_repo.count_pending(session) == 1
    assert await events_repo.count_pending(session, "tier_up") == 0


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("level_up", {"puuid": "p"}),
        ("new_match", {"score": float("nan")}),
        ("new_match", {"when": object()}),
        ("new_match", {1: "non-string key"}),
    ],
)
async def test_enqueue_event_rejects_bad_input(session, kind, payload):
    with pytest.raises(ValueError):
        await events.enqueue_event(session, kind, payload)
    assert await events_of(session) == []


def test_kda_thresholds():
    assert events.kda(3, 0, 4) == 7.0
    assert events.is_great_game(10, 2, 3) is True  # 6.5
    assert events.is_great_game(4, 1, 2) is False  # exactly 6
    assert events.is_bad_game(0, 3, 2) is True  # 0.67
    assert events.is_bad_game(0, 0, 0) is False  # no deaths: never "bad"
    assert events.is_bad_game(1, 2, 1) is False  # exactly 1
    assert set(events.EVENT_KINDS) == {
        "tier_up",
        "tier_down",
        "great_game",
        "bad_game",
        "new_match",
    }


def test_payload_builders_are_json_ready():
    start = datetime(2026, 9, 20, 18, 30, tzinfo=UTC)
    game = events.game_event_payload(
        puuid="p",
        game_name="Me",
        tag_line="NA1",
        profile_icon_id=1,
        match_id="NA1_1",
        queue_id=420,
        champion_id=103,
        champion_name="Ahri",
        team_position="MIDDLE",
        win=True,
        remake=False,
        kills=11,
        deaths=2,
        assists=8,
        ai_score=0.81,
        model_version="v1",
        game_start=start,
        game_duration=1837,
    )
    assert game["kda"] == 9.5 and game["game_start"] == start.isoformat()
    tier = events.tier_event_payload(
        puuid="p",
        game_name="Me",
        tag_line="NA1",
        platform="na1",
        profile_icon_id=None,
        queue_type="RANKED_SOLO_5x5",
        old_tier="DIAMOND",
        old_rank="I",
        old_lp=88,
        new_tier="MASTER",
        new_rank=None,
        new_lp=3,
        wins=100,
        losses=80,
        rank_value=2803,
    )
    assert tier["old"] == {"tier": "DIAMOND", "rank": "I", "lp": 88}
    assert tier["new"] == {"tier": "MASTER", "rank": None, "lp": 3}
    assert (tier["new_tier"], tier["new_rank"], tier["lp"]) == ("MASTER", None, 3)
