"""GET /leaderboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.factories import filler_specs, make_match_json, spec
from tests.fakes import install_fakes
from tests.test_api_support import StubScorer, add_match, add_model, add_rank, add_summoner

A, B, C, E, U = "puuid-a", "puuid-b", "puuid-c", "puuid-e", "puuid-u"
SEASON = datetime(2026, 3, 1, 20, tzinfo=UTC)
PRESEASON = datetime(2025, 12, 1, 20, tzinfo=UTC)


def _blue_red(match_id: str, blue: list, red: list, **kwargs):
    """Specs in blue slots 0.. and red slots 5.., fillers elsewhere."""
    slots = blue + filler_specs(match_id, 5 - len(blue), offset=len(blue))
    slots += red + filler_specs(match_id, 5 - len(red), offset=5 + len(red))
    return make_match_json(match_id, slots, **kwargs)


async def seed_roster(session) -> None:
    """A and B duo 3 times; A faces tracked E 4 times; A plays with untracked U 5 times;
    C is tracked but has no games."""
    await add_summoner(session, A, "Alpha", "NA1", tracked=True)
    await add_summoner(session, B, "bravo", "NA1", tracked=True)
    await add_summoner(session, C, "Charlie", "NA1", tracked=True)
    await add_summoner(session, E, "Echo", "NA1", tracked=True)
    await add_summoner(session, U, "Untracked", "NA1", tracked=False)
    await add_model(session, "v1", active=True)

    n = 0

    def start() -> datetime:
        return SEASON + timedelta(hours=n)

    # A + B same team, 3 games (2 wins), solo queue.
    for i in range(3):
        n += 1
        raw = _blue_red(
            f"NA1_{n}",
            [
                spec(A, "Alpha", "NA1", champion=(103, "Ahri"), kills=8, deaths=2, assists=4),
                spec(B, "bravo", "NA1", champion=(64, "LeeSin")),
            ],
            [],
            start=start(),
            winning_team=100 if i < 2 else 200,
        )
        await add_match(session, raw, scores={A: 0.8, B: 0.6})
    # A (blue) vs E (red), 4 games: E is tracked but an enemy, never A's ally.
    for _ in range(4):
        n += 1
        raw = _blue_red(
            f"NA1_{n}",
            [spec(A, "Alpha", "NA1", champion=(222, "Jinx"), kills=2, deaths=6, assists=3)],
            [spec(E, "Echo", "NA1")],
            queue_id=440,
            start=start(),
            winning_team=200,
        )
        await add_match(session, raw, scores={A: 0.8})
    # A + U (untracked) same team, 5 games: U never counts as an ally.
    for _ in range(5):
        n += 1
        raw = _blue_red(
            f"NA1_{n}",
            [
                spec(A, "Alpha", "NA1", champion=(103, "Ahri"), kills=4, deaths=4, assists=4),
                spec(U, "Untracked", "NA1"),
            ],
            [],
            start=start(),
            winning_team=100,
        )
        await add_match(session, raw, scores={A: 0.8})
    # B: scores from an inactive model must not move B's average.
    n += 1
    await add_match(
        session,
        _blue_red(f"NA1_{n}", [spec(B, "bravo", "NA1")], [], start=start()),
        scores={B: 0.99},
        model_version="v0",
    )
    # Never counted: a remake and a preseason game for A with B.
    n += 1
    await add_match(
        session,
        _blue_red(f"NA1_{n}", [spec(A), spec(B)], [], start=start(), remake=True),
    )
    await add_match(session, _blue_red("NA1_900", [spec(A), spec(B)], [], start=PRESEASON))

    # A's solo ladder: preseason row ignored, first season row is the baseline.
    await add_rank(session, A, "RANKED_SOLO_5x5", "DIAMOND", "I", 99, taken_at=PRESEASON)
    await add_rank(session, A, "RANKED_SOLO_5x5", "GOLD", "IV", 10, taken_at=SEASON)
    await add_rank(
        session, A, "RANKED_SOLO_5x5", "PLATINUM", "IV", 20, taken_at=SEASON + timedelta(days=9)
    )
    await add_rank(session, A, "RANKED_FLEX_SR", "SILVER", "I", 5, taken_at=SEASON)
    # C only has a preseason snapshot: unranked this season, and no season delta.
    await add_rank(session, C, "RANKED_SOLO_5x5", "IRON", "II", 1, taken_at=PRESEASON)
    await session.commit()


async def test_leaderboard_all_queues(client, session, settings):
    await seed_roster(session)
    resp = await client.get("/api/v1/leaderboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["queue"] == "all" and body["model_version"] == "v1"
    assert datetime.fromisoformat(body["season_start"]) == settings.season_start

    entries = body["entries"]
    # Only tracked players; avg AI desc, unscored last (then winrate desc).
    assert [e["puuid"] for e in entries] == [A, B, E, C]
    by_id = {e["puuid"]: e for e in entries}

    a = by_id[A]
    assert a["games"] == 12 and a["wins"] == 2 + 5 and a["losses"] == 5
    assert a["winrate"] == pytest.approx(7 / 12, abs=1e-4)
    kills, deaths, assists = 3 * 8 + 4 * 2 + 5 * 4, 3 * 2 + 4 * 6 + 5 * 4, 3 * 4 + 4 * 3 + 5 * 4
    assert a["kda"] == pytest.approx((kills + assists) / deaths, abs=1e-4)
    assert a["avg_kills"] == pytest.approx(kills / 12, abs=1e-4)
    assert a["avg_ai_score"] == pytest.approx(0.8)
    assert a["best_ally"] == {
        "puuid": B,
        "game_name": "bravo",
        "tag_line": "NA1",
        "games": 3,
        "wins": 2,
        "winrate": pytest.approx(2 / 3, abs=1e-4),
    }
    assert a["top_champions"] == ["Ahri", "Jinx"]
    # Newest first: 5 U wins, then 4 losses vs E, then the last A+B game (a loss) ...
    assert a["recent_form"] == [True] * 5 + [False] * 4 + [False]
    assert a["lp_delta"] == (4 * 400 + 20) - (3 * 400 + 10)
    assert a["solo"]["tier"] == "PLATINUM" and a["flex"]["tier"] == "SILVER"

    b = by_id[B]
    assert b["games"] == 4  # 3 with A + 1 solo game (remake / preseason excluded)
    assert b["avg_ai_score"] == pytest.approx(0.6)  # the v0 score is ignored
    assert b["best_ally"]["puuid"] == A and b["best_ally"]["games"] == 3
    assert b["lp_delta"] is None and b["solo"] is None

    e = by_id[E]
    assert e["games"] == 4 and e["wins"] == 4
    assert e["best_ally"] is None  # its teammates were fillers, and A was an enemy
    assert e["avg_ai_score"] is None

    c = by_id[C]
    assert c == {
        "puuid": C,
        "game_name": "Charlie",
        "tag_line": "NA1",
        "profile_icon_id": 29,
        "summoner_level": 100,
        "solo": c["solo"],
        "flex": None,
        "games": 0,
        "wins": 0,
        "losses": 0,
        "winrate": 0.0,
        "kda": 0.0,
        "avg_kills": 0.0,
        "avg_deaths": 0.0,
        "avg_assists": 0.0,
        "avg_ai_score": None,
        "avg_ai_role_percentile": None,
        "lp_delta": None,
        "best_ally": None,
        "top_champions": [],
        "recent_form": [],
    }
    # Last season's snapshot is not this season's standing.
    assert c["solo"] is None


async def test_leaderboard_queue_filter(client, session):
    await seed_roster(session)
    solo = {
        e["puuid"]: e
        for e in (await client.get("/api/v1/leaderboard?queue=solo")).json()["entries"]
    }
    assert solo[A]["games"] == 8 and solo[E]["games"] == 0
    assert solo[A]["top_champions"] == ["Ahri"]
    flex = {
        e["puuid"]: e
        for e in (await client.get("/api/v1/leaderboard?queue=flex")).json()["entries"]
    }
    assert flex[A]["games"] == 4 and flex[A]["best_ally"] is None
    assert flex[E]["games"] == 4
    assert flex[A]["lp_delta"] == solo[A]["lp_delta"]  # always the solo ladder
    assert (await client.get("/api/v1/leaderboard?queue=aram")).status_code == 422


async def test_leaderboard_without_active_model(app, client, session):
    await add_summoner(session, A, "Alpha", "NA1", tracked=True)
    await add_match(session, _blue_red("NA1_1", [spec(A)], [], start=SEASON), scores={A: 0.7})
    await session.commit()
    body = (await client.get("/api/v1/leaderboard")).json()
    assert body["model_version"] is None
    assert body["entries"][0]["avg_ai_score"] is None
    # A loaded model counts as the active one when no ai_models row is marked active.
    install_fakes(app, scorer=StubScorer("v1"))
    body = (await client.get("/api/v1/leaderboard")).json()
    assert body["model_version"] == "v1"
    assert body["entries"][0]["avg_ai_score"] == pytest.approx(0.7)


async def test_leaderboard_empty_roster(client, session):
    await add_summoner(session, U, "Untracked", "NA1")
    await session.commit()
    body = (await client.get("/api/v1/leaderboard")).json()
    assert body["entries"] == []


async def test_leaderboard_zero_game_roster(client, session):
    await add_summoner(session, C, "Charlie", "NA1", tracked=True)
    await add_summoner(session, "puuid-d", "Delta", "NA1", tracked=True)
    await session.commit()
    entries = (await client.get("/api/v1/leaderboard")).json()["entries"]
    assert [e["game_name"] for e in entries] == ["Charlie", "Delta"]
    assert all(e["games"] == 0 and e["best_ally"] is None for e in entries)
