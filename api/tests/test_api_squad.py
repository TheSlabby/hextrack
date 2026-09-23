"""GET /squad/pairs: duo synergy grid and who carries whom."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import update

from hextrack.db.models import MatchParticipant
from tests.factories import filler_specs, make_match_json, spec
from tests.test_api_support import add_match, add_model, add_summoner

A, B, C, D, E, U = (
    "puuid-a",
    "puuid-b",
    "puuid-c",
    "puuid-d",
    "puuid-e",
    "puuid-u",
)
SEASON = datetime(2026, 3, 1, 20, tzinfo=UTC)
PRESEASON = datetime(2025, 12, 1, 20, tzinfo=UTC)
URL = "/api/v1/squad/pairs"


def _game(
    match_id: str,
    blue: Sequence[str],
    red: Sequence[str] = (),
    *,
    hour: int,
    blue_wins: bool = True,
    queue_id: int = 420,
    start: datetime | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """A match with the given puuids in the blue (0-4) and red (5-9) slots."""
    blue_specs = [spec(p) for p in blue]
    red_specs = [spec(p) for p in red]
    slots = blue_specs + filler_specs(match_id, 5 - len(blue_specs), offset=len(blue_specs))
    slots += red_specs + filler_specs(match_id, 5 - len(red_specs), offset=5 + len(red_specs))
    return make_match_json(
        match_id,
        slots,
        queue_id=queue_id,
        start=start or SEASON + timedelta(hours=hour),
        winning_team=100 if blue_wins else 200,
        **kwargs,
    )


async def seed_squad(session) -> None:
    """Season (default filters) ground truth, v1 active:

    * A+B same team 7 times (4 wins): M1-M3 solo wins scored (A higher / B higher / tie),
      M4 solo loss with only A scored, M5 flex loss with B scored by the inactive v0,
      M6 flex win on the RED side scored only by v0, M13 solo loss as a trio with D.
    * A vs E (opposite teams) 3 times: never a pair.
    * B+D flex M10 (win) / M11 (loss), unscored; plus the trio M13.
    * A+U (untracked) once: U is not in the squad.
    * C is tracked with no games.
    * Never counted by default: a preseason A+B game (counts with since=all), a remake and
      an ARAM game.
    """
    await add_summoner(session, A, "Alpha", "NA1", tracked=True, profile_icon_id=11)
    await add_summoner(session, B, "bravo", "NA1", tracked=True)
    await add_summoner(session, C, "Charlie", "NA1", tracked=True)
    await add_summoner(session, D, "Delta", "NA1", tracked=True)
    await add_summoner(session, E, "Echo", "NA1", tracked=True)
    await add_summoner(session, U, "Untracked", "NA1", tracked=False)
    await add_model(session, "v0", active=False)
    await add_model(session, "v1", active=True)

    await add_match(session, _game("NA1_1", [A, B], hour=1), scores={A: 0.9, B: 0.3})
    await add_match(session, _game("NA1_2", [A, B], hour=2), scores={A: 0.5, B: 0.7})
    await add_match(session, _game("NA1_3", [A, B], hour=3), scores={A: 0.4, B: 0.4})
    await add_match(session, _game("NA1_4", [A, B], hour=4, blue_wins=False), scores={A: 0.2})
    # A scored by v1, B by the inactive v0: not a scored shared game.
    await add_match(
        session,
        _game("NA1_5", [A, B], hour=5, blue_wins=False, queue_id=440),
        scores={A: 0.95},
    )
    await session.execute(
        update(MatchParticipant)
        .where(MatchParticipant.match_id == "NA1_5", MatchParticipant.puuid == B)
        .values(ai_score=0.1, model_version="v0")
    )
    # Same team on the red side; both scored by the inactive model only.
    await add_match(
        session,
        _game("NA1_6", [], [A, B], hour=6, blue_wins=False, queue_id=440),
        scores={A: 0.99, B: 0.01},
        model_version="v0",
    )
    for i in (7, 8, 9):
        await add_match(
            session,
            _game(f"NA1_{i}", [A], [E], hour=i, blue_wins=False),
            scores={A: 0.3, E: 0.7},
        )
    await add_match(session, _game("NA1_10", [B, D], hour=10, queue_id=440))
    await add_match(session, _game("NA1_11", [B, D], hour=11, blue_wins=False, queue_id=440))
    await add_match(session, _game("NA1_12", [A, U], hour=12), scores={U: 0.1})
    # Unscored trio game.
    await add_match(session, _game("NA1_13", [A, B, D], hour=13, blue_wins=False))
    # Preseason, remake and ARAM.
    await add_match(
        session, _game("NA1_14", [A, B], hour=0, start=PRESEASON), scores={A: 0.1, B: 0.9}
    )
    await add_match(session, _game("NA1_15", [A, B], hour=15, remake=True, duration_s=200))
    await add_match(
        session,
        _game("NA1_16", [A, B], hour=16, queue_id=450, game_mode="ARAM"),
        scores={A: 0.9, B: 0.1},
    )
    await session.commit()


def _pairs(body: dict) -> dict[tuple[str, str], dict]:
    return {(p["a_puuid"], p["b_puuid"]): p for p in body["pairs"]}


async def test_squad_pairs_season_defaults(client, session, settings):
    await seed_squad(session)
    resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["since"] == "season" and body["queue"] == "all"
    assert body["model_version"] == "v1" and body["min_games"] == 5
    assert datetime.fromisoformat(body["season_start"]) == settings.season_start

    # Every tracked player (C without games too), most games first; U is not tracked.
    players = body["players"]
    assert [p["puuid"] for p in players] == [A, B, E, D, C]
    by_id = {p["puuid"]: p for p in players}
    assert by_id[A] == {
        "puuid": A,
        "game_name": "Alpha",
        "tag_line": "NA1",
        "profile_icon_id": 11,
        "games": 11,
        "wins": 5,
        "winrate": pytest.approx(5 / 11, abs=1e-4),
        "avg_ai_score": pytest.approx((0.9 + 0.5 + 0.4 + 0.2 + 0.95 + 3 * 0.3) / 8),
    }
    assert (by_id[B]["games"], by_id[B]["wins"]) == (9, 5)
    assert by_id[B]["avg_ai_score"] == pytest.approx((0.3 + 0.7 + 0.4) / 3)
    assert (by_id[D]["games"], by_id[D]["wins"], by_id[D]["avg_ai_score"]) == (3, 1, None)
    assert (by_id[E]["games"], by_id[E]["wins"]) == (3, 3)
    assert by_id[C] == {
        "puuid": C,
        "game_name": "Charlie",
        "tag_line": "NA1",
        "profile_icon_id": 29,
        "games": 0,
        "wins": 0,
        "winrate": 0.0,
        "avg_ai_score": None,
    }

    # Same team only: A and E always faced each other, U is untracked, C never played.
    assert [(p["a_puuid"], p["b_puuid"]) for p in body["pairs"]] == [(A, B), (B, D), (A, D)]
    pairs = _pairs(body)

    ab = pairs[(A, B)]
    assert (ab["games"], ab["wins"]) == (7, 4)
    assert ab["winrate"] == pytest.approx(4 / 7, abs=1e-4)
    expected = (5 / 11 + 5 / 9) / 2
    assert ab["expected_winrate"] == pytest.approx(expected, abs=1e-4)
    assert ab["winrate_delta"] == pytest.approx(4 / 7 - expected, abs=1e-4)
    # Scored shared games: M1-M3 only (M4 B unscored, M5 B by v0, M6 both by v0).
    assert ab["scored_games"] == 3
    assert (ab["a_higher"], ab["b_higher"], ab["ties"]) == (1, 1, 1)
    assert ab["avg_ai_a"] == pytest.approx((0.9 + 0.5 + 0.4) / 3)
    assert ab["avg_ai_b"] == pytest.approx((0.3 + 0.7 + 0.4) / 3)
    assert ab["avg_score_diff"] == pytest.approx((0.6 - 0.2 + 0.0) / 3)

    bd = pairs[(B, D)]
    assert (bd["games"], bd["wins"]) == (3, 1)
    assert bd["expected_winrate"] == pytest.approx((5 / 9 + 1 / 3) / 2, abs=1e-4)
    assert bd["winrate_delta"] == pytest.approx(1 / 3 - (5 / 9 + 1 / 3) / 2, abs=1e-4)
    assert bd["scored_games"] == 0
    assert (bd["a_higher"], bd["b_higher"], bd["ties"]) == (0, 0, 0)
    assert bd["avg_ai_a"] is None and bd["avg_ai_b"] is None
    assert bd["avg_score_diff"] is None

    ad = pairs[(A, D)]
    assert (ad["games"], ad["wins"], ad["winrate"]) == (1, 0, 0.0)
    assert ad["winrate_delta"] == pytest.approx(-(5 / 11 + 1 / 3) / 2, abs=1e-4)


async def test_squad_pairs_since_all_counts_preseason(client, session):
    await seed_squad(session)
    body = (await client.get(URL, params={"since": "all"})).json()
    assert body["since"] == "all"
    by_id = {p["puuid"]: p for p in body["players"]}
    assert (by_id[A]["games"], by_id[A]["wins"]) == (12, 6)
    assert (by_id[B]["games"], by_id[B]["wins"]) == (10, 6)

    ab = _pairs(body)[(A, B)]
    assert (ab["games"], ab["wins"]) == (8, 5)
    assert ab["expected_winrate"] == pytest.approx((6 / 12 + 6 / 10) / 2, abs=1e-4)
    # The preseason game adds a scored shared game where B was higher.
    assert (ab["scored_games"], ab["a_higher"], ab["b_higher"], ab["ties"]) == (4, 1, 2, 1)
    assert ab["avg_score_diff"] == pytest.approx((0.6 - 0.2 + 0.0 - 0.8) / 4)
    assert ab["avg_ai_a"] - ab["avg_ai_b"] == pytest.approx(ab["avg_score_diff"])


async def test_squad_pairs_queue_filters(client, session):
    await seed_squad(session)

    solo = (await client.get(URL, params={"queue": "solo"})).json()
    assert solo["queue"] == "solo"
    by_id = {p["puuid"]: p for p in solo["players"]}
    assert (by_id[A]["games"], by_id[A]["wins"]) == (9, 4)
    assert (by_id[B]["games"], by_id[B]["wins"]) == (5, 3)
    assert (by_id[D]["games"], by_id[D]["wins"]) == (1, 0)
    pairs = _pairs(solo)
    assert set(pairs) == {(A, B), (A, D), (B, D)}
    assert (pairs[(A, B)]["games"], pairs[(A, B)]["wins"]) == (5, 3)
    assert pairs[(A, B)]["scored_games"] == 3
    assert pairs[(B, D)]["games"] == 1

    flex = (await client.get(URL, params={"queue": "flex"})).json()
    pairs = _pairs(flex)
    assert set(pairs) == {(A, B), (B, D)}
    ab = pairs[(A, B)]
    assert (ab["games"], ab["wins"]) == (2, 1)
    # M5 mixes model versions and M6 only has inactive-model scores.
    assert ab["scored_games"] == 0 and ab["avg_score_diff"] is None
    assert ab["avg_ai_a"] is None and ab["avg_ai_b"] is None
    assert (pairs[(B, D)]["games"], pairs[(B, D)]["wins"]) == (2, 1)


async def test_squad_pairs_without_active_model(client, session):
    """No active model and no loaded scorer: every AI field is None / 0."""
    await add_summoner(session, A, "Alpha", "NA1", tracked=True)
    await add_summoner(session, B, "bravo", "NA1", tracked=True)
    await add_model(session, "v1", active=False)
    await add_match(session, _game("NA1_1", [A, B], hour=1), scores={A: 0.9, B: 0.3})
    await session.commit()

    body = (await client.get(URL)).json()
    assert body["model_version"] is None
    assert all(p["avg_ai_score"] is None for p in body["players"])
    [ab] = body["pairs"]
    assert (ab["games"], ab["wins"], ab["winrate"]) == (1, 1, 1.0)
    assert ab["expected_winrate"] == 1.0 and ab["winrate_delta"] == 0.0
    assert ab["scored_games"] == 0 and ab["avg_score_diff"] is None


async def test_squad_pairs_empty_roster(client, session):
    await add_summoner(session, U, "Untracked", "NA1", tracked=False)
    await add_match(session, _game("NA1_1", [U], hour=1))
    await session.commit()

    resp = await client.get(URL, params={"since": "all", "queue": "flex"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["players"] == [] and body["pairs"] == []
    assert body["since"] == "all" and body["queue"] == "flex" and body["min_games"] == 5


async def test_squad_pair_order_is_code_point_order(client, session):
    """``a_puuid < b_puuid`` as Python / JS compare strings, whatever the database
    collation: under en_US "pME4" sorts before "X1Sy", in code points "X1Sy" is first."""
    upper, lower = "X1Sy-puuid", "pME4-puuid"
    await add_summoner(session, upper, "Upper", "NA1", tracked=True)
    await add_summoner(session, lower, "lower", "NA1", tracked=True)
    await add_model(session, "v1", active=True)
    await add_match(
        session, _game("NA1_1", [lower, upper], hour=1), scores={upper: 0.8, lower: 0.2}
    )
    await session.commit()

    [pair] = (await client.get(URL)).json()["pairs"]
    assert pair["a_puuid"] < pair["b_puuid"]
    assert (pair["a_puuid"], pair["b_puuid"]) == (upper, lower)
    assert (pair["a_higher"], pair["b_higher"]) == (1, 0)
