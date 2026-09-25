"""AI Score trend and explanation routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from hextrack.hextrack_ai import explain, inference, registry
from tests.factories import make_match_json, spec
from tests.fakes import install_fakes
from tests.test_api_support import StubScorer, add_match, add_model, add_summoner

ME = "puuid-me"
T0 = datetime(2026, 3, 1, 20, tzinfo=UTC)


async def seed_scores(session) -> None:
    """Six games: v1 scores on 0-2, v2 scores on 3-4 (scored later), game 5 unscored."""
    await add_summoner(session, ME, "Hex Walker", "NA1")
    for i in range(6):
        raw = make_match_json(
            f"NA1_{100 + i}",
            [spec(ME, champion=(103, "Ahri") if i % 2 else (64, "LeeSin"))],
            start=T0 + timedelta(hours=i),
            winning_team=100 if i % 2 == 0 else 200,
        )
        if i < 3:
            await add_match(session, raw, scores={ME: 0.2 + 0.1 * i}, model_version="v1")
        elif i < 5:
            await add_match(
                session,
                raw,
                scores={ME: 0.5 + 0.1 * i},
                model_version="v2",
                scored_at=datetime(2026, 9, 10, tzinfo=UTC),
            )
        else:
            await add_match(session, raw)


async def test_ai_trend_uses_active_model(client, session):
    await seed_scores(session)
    await add_model(session, "v1", active=True)
    await add_model(session, "v2", active=False)
    await session.commit()

    body = (await client.get(f"/api/v1/summoners/{ME}/ai-trend")).json()
    assert body["puuid"] == ME and body["model_version"] == "v1"
    points = body["points"]
    assert [p["match_id"] for p in points] == ["NA1_100", "NA1_101", "NA1_102"]  # oldest first
    assert [p["ai_score"] for p in points] == pytest.approx([0.2, 0.3, 0.4])
    assert [p["champion_name"] for p in points] == ["LeeSin", "Ahri", "LeeSin"]
    assert [p["win"] for p in points] == [True, False, True]
    assert body["average"] == pytest.approx(0.3)

    limited = (await client.get(f"/api/v1/summoners/{ME}/ai-trend?limit=2")).json()
    assert [p["match_id"] for p in limited["points"]] == ["NA1_101", "NA1_102"]
    assert limited["average"] == pytest.approx(0.35)


async def test_ai_trend_falls_back_to_latest_scored_version(client, session):
    await seed_scores(session)
    await session.commit()
    body = (await client.get(f"/api/v1/summoners/{ME}/ai-trend")).json()
    assert body["model_version"] == "v2"
    assert [p["match_id"] for p in body["points"]] == ["NA1_103", "NA1_104"]
    assert body["average"] == pytest.approx((0.8 + 0.9) / 2)


async def test_ai_trend_prefers_loaded_model_over_history(app, client, session):
    await seed_scores(session)
    await session.commit()
    install_fakes(app, scorer=StubScorer("v1"))
    body = (await client.get(f"/api/v1/summoners/{ME}/ai-trend")).json()
    assert body["model_version"] == "v1" and len(body["points"]) == 3


async def test_ai_trend_without_scores(client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await session.commit()
    body = (await client.get(f"/api/v1/summoners/{ME}/ai-trend")).json()
    assert body == {"puuid": ME, "model_version": None, "average": None, "points": []}
    assert (await client.get("/api/v1/summoners/nobody/ai-trend")).status_code == 404


async def test_ai_explain_requires_model(client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await session.commit()
    resp = await client.get(f"/api/v1/summoners/{ME}/ai-explain")
    assert resp.status_code == 503
    assert resp.json() == {"detail": "AI model not loaded", "code": "model_missing"}


@pytest.fixture
def explain_fakes(monkeypatch) -> dict[str, list[Any]]:
    """Stand-ins for the B3 model code: record what the route passes in."""
    calls: dict[str, list[Any]] = {"explain": [], "population": [], "rows": []}

    def participant_to_dict(orm_row):
        calls["rows"].append(orm_row.match_id)
        return {"puuid": orm_row.puuid, "kills": orm_row.kills, "match_id": orm_row.match_id}

    def explain_player(scorer, durations, rows, population_means):
        calls["explain"].append((list(durations), list(rows), population_means))
        return [
            {
                "feature": "vision_per_min",
                "label": "Vision / min",
                "group": "vision",
                "mean_attribution": -0.1,
                "mean_abs_attribution": 0.2,
                "player_value": 0.9,
                "population_value": population_means.get("vision_per_min"),
            },
            {
                "feature": "kills_per_min",
                "label": "Kills / min",
                "group": "combat",
                "mean_attribution": 0.5,
                "mean_abs_attribution": 0.6,
                "player_value": 0.3,
                "population_value": population_means.get("kills_per_min"),
                "unexpected_extra_key": "ignored",
            },
        ]

    async def population_feature_means(session, scorer, **kwargs):
        calls["population"].append(scorer.version)
        return {"kills_per_min": 0.25, "vision_per_min": 1.1}

    monkeypatch.setattr(inference, "participant_to_dict", participant_to_dict)
    monkeypatch.setattr(explain, "explain_player", explain_player)
    monkeypatch.setattr(explain, "base_score", lambda scorer: 0.5)
    monkeypatch.setattr(registry, "population_feature_means", population_feature_means)
    return calls


async def test_ai_explain_happy_path(app, client, session, explain_fakes):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    for i in range(4):
        await add_match(
            session,
            make_match_json(
                f"NA1_{i}", [spec(ME)], start=T0 + timedelta(hours=i), duration_s=1500 + i
            ),
        )
    # Not explainable: a remake, an ARAM game and an aborted game.
    await add_match(session, make_match_json("NA1_90", [spec(ME)], remake=True, start=T0))
    await add_match(
        session,
        make_match_json("NA1_91", [spec(ME)], queue_id=450, game_mode="ARAM", start=T0),
    )
    await add_match(
        session,
        make_match_json("NA1_92", [spec(ME)], end_of_game_result="Abort_Unexpected", start=T0),
    )
    await session.commit()
    install_fakes(app, scorer=StubScorer("v7"))

    resp = await client.get(f"/api/v1/summoners/{ME}/ai-explain?limit=3")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["puuid"] == ME and body["model_version"] == "v7"
    assert body["n_matches"] == 3 and body["base_score"] == 0.5
    assert [f["feature"] for f in body["features"]] == ["kills_per_min", "vision_per_min"]
    assert body["features"][0] == {
        "feature": "kills_per_min",
        "label": "Kills / min",
        "group": "combat",
        "mean_attribution": 0.5,
        "mean_abs_attribution": 0.6,
        "player_value": 0.3,
        "population_value": 0.25,
    }
    ((durations, rows, population),) = explain_fakes["explain"]
    assert durations == [1503, 1502, 1501]  # newest first, ranked + scorable only
    assert [r["match_id"] for r in rows] == ["NA1_3", "NA1_2", "NA1_1"]
    assert population == {"kills_per_min": 0.25, "vision_per_min": 1.1}

    # Default limit covers all four explainable games.
    body = (await client.get(f"/api/v1/summoners/{ME}/ai-explain")).json()
    assert body["n_matches"] == 4
    assert explain_fakes["population"] == ["v7", "v7"]


async def test_ai_explain_without_games(app, client, session, explain_fakes):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await session.commit()
    install_fakes(app, scorer=StubScorer("v7"))
    body = (await client.get(f"/api/v1/summoners/{ME}/ai-explain")).json()
    assert body["n_matches"] == 0 and body["features"] == [] and body["base_score"] == 0.5
    assert explain_fakes["explain"] == [] and explain_fakes["population"] == []


async def test_ai_explain_unknown_summoner(app, client, explain_fakes):
    install_fakes(app, scorer=StubScorer("v7"))
    resp = await client.get("/api/v1/summoners/nobody/ai-explain")
    assert resp.status_code == 404 and resp.json()["code"] == "not_found"


class _ScoringStub(StubScorer):
    """StubScorer that can also score a stat line (the per-game explain route needs it)."""

    def score_rows(self, durations, rows):
        return [0.83 for _ in rows]


async def test_match_ai_explain_happy_path(app, client, session, explain_fakes):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await add_match(
        session,
        make_match_json("NA1_7", [spec(ME)], start=T0, duration_s=1800),
        scores={ME: 0.8},
    )
    await session.commit()
    install_fakes(app, scorer=_ScoringStub("v7"))

    resp = await client.get("/api/v1/matches/NA1_7/ai-explain", params={"puuid": ME})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["match_id"], body["puuid"], body["model_version"]) == ("NA1_7", ME, "v7")
    assert body["base_score"] == 0.5 and body["score"] == 0.83 and body["stored_score"] == 0.8
    assert isinstance(body["win"], bool)
    assert [f["feature"] for f in body["features"]] == ["kills_per_min", "vision_per_min"]
    ((durations, rows, population),) = explain_fakes["explain"]
    assert durations == [1800] and [r["match_id"] for r in rows] == ["NA1_7"]
    assert population == {"kills_per_min": 0.25, "vision_per_min": 1.1}


async def test_match_ai_explain_errors(app, client, session, explain_fakes):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await add_match(session, make_match_json("NA1_8", [spec(ME)], remake=True, start=T0))
    await add_match(session, make_match_json("NA1_9", [spec(ME)], start=T0))
    await session.commit()
    install_fakes(app, scorer=_ScoringStub("v7"))

    missing = await client.get("/api/v1/matches/NA1_9/ai-explain", params={"puuid": "nobody"})
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    remake = await client.get("/api/v1/matches/NA1_8/ai-explain", params={"puuid": ME})
    assert remake.status_code == 409 and remake.json()["code"] == "not_scorable"
    no_puuid = await client.get("/api/v1/matches/NA1_9/ai-explain")
    assert no_puuid.status_code == 422
    assert explain_fakes["explain"] == []


async def test_match_ai_explain_requires_model(app, client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await add_match(session, make_match_json("NA1_9", [spec(ME)], start=T0))
    await session.commit()
    install_fakes(app, scorer=None)
    resp = await client.get("/api/v1/matches/NA1_9/ai-explain", params={"puuid": ME})
    assert resp.status_code == 503
