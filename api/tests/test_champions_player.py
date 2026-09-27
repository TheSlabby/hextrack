"""GET /champions/{champion}/players/{puuid}: a roster player's games on one champion."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import Match, MatchTimelinePlayer
from hextrack.stats.champions.cache import CHAMPION_CACHE
from hextrack.stats.champions.items import ItemCatalog
from tests.conftest import FIXTURES_DIR
from tests.factories import make_match_json, make_perks, spec, timeline_plan
from tests.test_api_support import add_match, add_model, add_summoner
from tests.test_champions_api import AHRI, URL, ZED, add_stat, add_total

A, B, U = "puuid-a", "puuid-b", "puuid-u"
START = datetime(2026, 3, 1, 20, tzinfo=UTC)
#: Completed items in the fixture item data: core 3071-6692-6333 or 3078-3071-6333.
CORE_1 = [(1055, 5), (3071, 600), (3047, 700), (6692, 900), (6333, 1300)]
CORE_1_LATE = [(1055, 5), (3071, 700), (6692, 1000), (6333, 1500), (3078, 1800)]
CORE_2 = [(1055, 5), (3078, 500), (3071, 800), (6333, 1100)]
TWO_ITEMS = [(1055, 5), (3071, 600), (6692, 900)]


class FakeDDragon:
    def __init__(self, *, fail: bool = False) -> None:
        self.catalog = ItemCatalog.from_item_json(
            json.loads((FIXTURES_DIR / "item_sample.json").read_text())
        )
        self.fail = fail
        self.patches: list[str] = []

    async def item_catalog(self, patch: str) -> ItemCatalog | None:
        self.patches.append(patch)
        if self.fail:
            raise RuntimeError("no item data")
        return self.catalog

    async def champion_map(self) -> dict[int, str]:
        return {}


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    CHAMPION_CACHE.clear()


@pytest.fixture
def dd(app) -> FakeDDragon:
    fake = FakeDDragon()
    app.state.ddragon = fake
    return fake


def url(champion: str = "Ahri", puuid: str = A) -> str:
    return f"{URL}/{champion}/players/{puuid}"


async def add_game(
    session: AsyncSession,
    n: int,
    puuid: str = A,
    *,
    champion: tuple[int, str] = AHRI,
    position: str = "MIDDLE",
    win: bool = True,
    kills: int = 5,
    deaths: int = 2,
    assists: int = 7,
    score: float | None = None,
    model: str = "v1",
    queue_id: int = 420,
    hours: int | None = None,
    purchases: list[tuple[int, int]] | None = None,
    **overrides: Any,
) -> str:
    match_id = f"NA1_{1000 + n}"
    raw = make_match_json(
        match_id,
        [
            spec(
                puuid,
                champion=champion,
                position=position,
                kills=kills,
                deaths=deaths,
                assists=assists,
                **overrides,
            )
        ],
        start=START + timedelta(hours=n if hours is None else hours),
        queue_id=queue_id,
        winning_team=100 if win else 200,
    )
    await add_match(
        session, raw, scores={puuid: score} if score is not None else None, model_version=model
    )
    if purchases is not None:
        plan = timeline_plan(raw, 1, purchases=purchases, skills=[1, 2, 3])
        await session.execute(
            insert(MatchTimelinePlayer).values(
                match_id=match_id,
                participant_id=1,
                purchases=plan.purchases,
                purchase_s=plan.purchase_s,
                skill_order=plan.skill_order,
            )
        )
        await session.execute(
            update(Match).where(Match.match_id == match_id).values(timeline_state="ok")
        )
    return match_id


async def seed_base(session: AsyncSession) -> None:
    await add_summoner(session, A, "Alpha", "NA1", tracked=True, profile_icon_id=7)
    await add_summoner(session, B, "Bravo", "NA1", tracked=True)
    await add_summoner(session, U, "Untracked", "NA1", tracked=False)
    await add_model(session, "v0", active=False)
    await add_model(session, "v1", active=True)
    await add_total(session, "16.16", 420, 100)
    await add_total(session, "16.17", 420, 100)
    await add_total(session, "16.17", 440, 100)
    # The field: Ahri mid over two season patches (solo) and flex; Ahri top; Zed exists.
    await add_stat(session, AHRI, "MIDDLE", "16.17", games=60, wins=33)
    await add_stat(session, AHRI, "MIDDLE", "16.16", games=40, wins=17)
    await add_stat(session, AHRI, "MIDDLE", "16.17", queue_id=440, games=100, wins=90)
    await add_stat(session, AHRI, "TOP", "16.17", games=10, wins=1)
    await add_stat(session, ZED, "MIDDLE", "16.17", games=5, wins=2)


# --- 404s and empty --------------------------------------------------------------------------


async def test_not_found(client, session) -> None:
    await seed_base(session)
    await session.commit()
    resp = await client.get(url("Nope"))
    assert resp.status_code == 404 and resp.json()["code"] == "champion_not_found"
    for puuid in (U, "nobody"):
        resp = await client.get(url(puuid=puuid))
        assert resp.status_code == 404 and resp.json()["code"] == "player_not_found"


async def test_zero_games(client, session, dd) -> None:
    await seed_base(session)
    await add_game(session, 1, B)
    await add_game(session, 2, A, champion=ZED)
    await session.commit()
    resp = await client.get(url())
    assert resp.status_code == 200
    body = resp.json()
    assert body["champion_id"] == 103 and body["champion_name"] == "Ahri"
    assert body["puuid"] == A and body["game_name"] == "Alpha" and body["profile_icon_id"] == 7
    assert body["model_version"] == "v1" and body["queue"] == "all"
    assert body["games"] == 0 and body["wins"] == 0 and body["win_rate"] is None
    assert body["kda"] == 0 and body["cs_per_min"] == 0 and body["avg_ai_score"] is None
    assert body["main_position"] == "UNKNOWN"
    assert body["field_win_rate"] is None and body["field_kda"] is None
    assert body["squad_rank"] is None and body["squad_players"] == 1
    assert body["core"] is None and body["timeline_games"] == 0
    assert body["rune_page"] is None and body["spells"] is None
    assert body["recent"] == [] and body["best_game"] is None


# --- stats -----------------------------------------------------------------------------------


async def test_stats_field_and_squad(client, session, dd) -> None:
    await seed_base(session)
    await add_game(session, 1, kills=10, deaths=2, assists=4, score=0.9)
    await add_game(session, 2, win=False, kills=2, deaths=6, assists=8, score=0.2)
    await add_game(session, 3, position="TOP", kills=6, deaths=4, assists=0, score=0.7, model="v0")
    # B plays Ahri more: A is 2nd of 2.
    for n in range(10, 14):
        await add_game(session, n, B)
    # Never counted: a crawled game, a remake, preseason, ARAM, another champion.
    crawled = await add_game(session, 20)
    await session.execute(update(Match).where(Match.match_id == crawled).values(source="crawl"))
    await add_game(session, 21)
    raw = make_match_json(
        "NA1_2022",
        [spec(A, champion=AHRI, position="MIDDLE")],
        start=datetime(2025, 12, 1, tzinfo=UTC),
    )
    await add_match(session, raw)
    await add_game(session, 23, queue_id=450)
    await add_game(session, 24, champion=ZED)
    await session.execute(
        update(Match).where(Match.match_id == "NA1_1021").values(game_duration=200, remake=True)
    )
    await session.commit()

    body = (await client.get(url("ahri"))).json()
    assert body["games"] == 3 and body["wins"] == 2
    assert body["win_rate"] == pytest.approx(0.6667, abs=1e-4)
    assert body["avg_kills"] == 6 and body["avg_deaths"] == 4 and body["avg_assists"] == 4
    assert body["kda"] == 2.5  # (18 + 12) / 12
    # Slot 0, 30 minute games: 216 cs each.
    assert body["cs_per_min"] == 7.2
    # damage = 900 * 30 + 300 * kills
    assert body["avg_damage"] == pytest.approx(27_000 + 300 * 6)
    # gold = 400 * 30 + 150 * kills + 80 * assists
    assert body["avg_gold"] == pytest.approx(12_000 + 150 * 6 + 80 * 4)
    assert body["avg_ai_score"] == pytest.approx(0.55)  # v1 only: (0.9 + 0.2) / 2
    assert body["main_position"] == "MIDDLE"
    # Field: Ahri MIDDLE over 16.16 + 16.17, both queues: 200 games, 140 wins.
    assert body["field_win_rate"] == 0.7
    assert body["field_kda"] == 2.75
    assert body["field_cs_per_min"] == 6.0
    assert body["field_avg_damage"] == 20_000
    assert body["squad_rank"] == 2 and body["squad_players"] == 2

    solo = (await client.get(url(), params={"queue": "solo"})).json()
    assert solo["field_win_rate"] == 0.5  # 50 / 100


async def test_queue_filter(client, session, dd) -> None:
    await seed_base(session)
    await add_game(session, 1, score=0.8)
    await add_game(session, 2, queue_id=440, position="TOP", win=False, score=0.3)
    await add_game(session, 3, queue_id=440, position="TOP", score=0.6)
    await add_game(session, 4, B, queue_id=440)
    await session.commit()
    flex = (await client.get(url(), params={"queue": "flex"})).json()
    assert flex["queue"] == "flex"
    assert flex["games"] == 2 and flex["main_position"] == "TOP"
    assert [g["match_id"] for g in flex["recent"]] == ["NA1_1003", "NA1_1002"]
    assert all(g["queue_id"] == 440 for g in flex["recent"])
    # Ahri TOP has no flex rollups: no field numbers.
    assert flex["field_win_rate"] is None
    assert flex["squad_rank"] == 1 and flex["squad_players"] == 2
    solo = (await client.get(url(), params={"queue": "solo"})).json()
    assert solo["games"] == 1 and solo["main_position"] == "MIDDLE"
    assert solo["squad_players"] == 1
    both = (await client.get(url())).json()
    assert both["games"] == 3 and both["main_position"] == "TOP"


# --- builds ----------------------------------------------------------------------------------


async def test_core_runes_spells(client, session, dd) -> None:
    await seed_base(session)
    await add_game(session, 1, purchases=CORE_1)
    await add_game(session, 2, purchases=CORE_1_LATE, win=False)
    await add_game(session, 3, purchases=CORE_2)
    await add_game(session, 4, purchases=TWO_ITEMS)  # a timeline, but no core
    await add_game(session, 5, perks=make_perks(2), summoner2Id=14)  # no timeline
    await add_game(session, 6, perks=make_perks(2), summoner2Id=14)
    # A timeline row stored while the match is not marked "ok" is not used.
    ignored = await add_game(session, 7, purchases=CORE_2)
    await session.execute(
        update(Match).where(Match.match_id == ignored).values(timeline_state="pending")
    )
    await session.commit()

    body = (await client.get(url())).json()
    assert body["games"] == 7
    assert body["timeline_games"] == 4
    core = body["core"]
    assert core["items"] == [3071, 6692, 6333]
    assert core["games"] == 2 and core["wins"] == 1 and core["win_rate"] == 0.5
    assert core["pick_rate"] == pytest.approx(0.6667, abs=1e-4)  # 2 of 3 games with a core
    assert core["avg_time_s"] == 1400  # (1300 + 1500) / 2
    assert set(dd.patches) == {"16.17"}

    page = body["rune_page"]  # slot 0's page (5 games) over slot 2's (2 games)
    assert page["primary_style_id"] == 8000 and page["secondary_style_id"] == 8400
    assert page["rune_ids"] == [8010, 9111, 9104, 8299, 8444, 8451]
    assert page["games"] == 5 and page["pick_rate"] == pytest.approx(5 / 7, abs=1e-4)
    spells = body["spells"]
    assert spells["spell_ids"] == [4, 12] and spells["games"] == 5
    assert spells["pick_rate"] == pytest.approx(5 / 7, abs=1e-4)


async def test_core_none_without_item_data(client, session, app) -> None:
    await seed_base(session)
    await add_game(session, 1, purchases=CORE_1)
    await session.commit()
    app.state.ddragon = FakeDDragon(fail=True)
    body = (await client.get(url())).json()
    assert body["core"] is None and body["timeline_games"] == 1
    assert body["rune_page"] is not None
    app.state.ddragon = None
    body = (await client.get(url())).json()
    assert body["core"] is None


# --- recent and best ------------------------------------------------------------------------


async def test_recent_and_best_game(client, session, dd) -> None:
    await seed_base(session)
    await add_game(session, 1, score=0.7)
    await add_game(session, 2, score=0.95, win=False)  # higher, but a loss
    await add_game(session, 3, score=0.99, model="v0")  # old model: not scored
    await add_game(session, 4, score=0.85)
    await add_game(session, 5, score=0.85)  # tie with 4: the newer one
    await add_game(session, 6)
    await add_game(session, 7, score=0.1)
    await session.commit()

    body = (await client.get(url())).json()
    recent = body["recent"]
    assert [g["match_id"] for g in recent] == [f"NA1_{1000 + n}" for n in (7, 6, 5, 4, 3)]
    first = recent[0]
    assert first["position"] == "MIDDLE" and first["queue_id"] == 420 and first["win"] is True
    assert (first["kills"], first["deaths"], first["assists"]) == (5, 2, 7)
    assert first["cs"] == 216 and first["game_duration"] == 1800
    assert first["items"] == [6692, 3047, 6333, 3071, 1053, 0, 3340]
    assert first["patch"] == "16.17" and first["ai_score"] == 0.1
    assert recent[4]["ai_score"] is None  # scored by v0
    assert recent[1]["ai_score"] is None  # not scored
    assert body["best_game"]["match_id"] == "NA1_1005"
    assert body["best_game"]["ai_score"] == 0.85


async def test_best_game_among_losses(client, session, dd) -> None:
    await seed_base(session)
    await add_game(session, 1, win=False, score=0.3)
    await add_game(session, 2, win=False, score=0.4)
    await add_game(session, 3, win=True)  # a win, but not scored
    await session.commit()
    body = (await client.get(url())).json()
    assert body["best_game"]["match_id"] == "NA1_1002"
    assert body["avg_ai_score"] == pytest.approx(0.35)
