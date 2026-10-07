"""GET /champions/patches, /champions, /champions/{champion} and /champions/{champion}/squad.

The rollup tables are seeded directly (the worker that fills them is tested on its own).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import (
    ChampionBan,
    ChampionMatchup,
    ChampionPatchTotal,
    ChampionRollup,
    ChampionStat,
    Match,
)
from hextrack.stats.champions.cache import CHAMPION_CACHE
from tests.factories import make_match_json, spec
from tests.test_api_support import add_match, add_model, add_summoner

AHRI = (103, "Ahri")
ZED = (238, "Zed")
SYNDRA = (134, "Syndra")
WUKONG = (62, "MonkeyKing")
URL = "/api/v1/champions"


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    CHAMPION_CACHE.clear()


async def add_total(
    session: AsyncSession, patch: str, queue_id: int, matches: int, timeline: int = 0
) -> None:
    await session.execute(
        insert(ChampionPatchTotal).values(
            patch=patch, queue_id=queue_id, matches=matches, timeline_matches=timeline
        )
    )


async def add_stat(
    session: AsyncSession,
    champion: tuple[int, str],
    position: str,
    patch: str,
    *,
    queue_id: int = 420,
    games: int,
    wins: int,
    timeline_games: int = 0,
    kills: int | None = None,
    deaths: int | None = None,
    assists: int | None = None,
) -> None:
    await session.execute(
        insert(ChampionStat).values(
            champion_id=champion[0],
            champion_key=champion[1],
            position=position,
            patch=patch,
            queue_id=queue_id,
            games=games,
            wins=wins,
            kills=games * 5 if kills is None else kills,
            deaths=games * 4 if deaths is None else deaths,
            assists=games * 6 if assists is None else assists,
            damage=games * 20_000,
            cs=games * 180,
            gold=games * 11_000,
            duration_s=games * 1800,
            timeline_games=timeline_games,
            timeline_wins=timeline_games // 2,
        )
    )


async def add_ban(session: AsyncSession, champion_id: int, patch: str, bans: int, queue_id=420):
    await session.execute(
        insert(ChampionBan).values(
            patch=patch, queue_id=queue_id, champion_id=champion_id, bans=bans
        )
    )


async def add_rollups(
    session: AsyncSession,
    champion_id: int,
    position: str,
    patch: str,
    rows: list[tuple[str, str, int, int] | tuple[str, str, int, int, int]],
    *,
    queue_id: int = 420,
) -> None:
    values: list[dict[str, Any]] = []
    for row in rows:
        kind, key, games, wins, *extra = row
        values.append(
            dict(
                champion_id=champion_id,
                position=position,
                patch=patch,
                queue_id=queue_id,
                kind=kind,
                key=key,
                games=games,
                wins=wins,
                extra_sum=extra[0] if extra else 0,
            )
        )
    await session.execute(insert(ChampionRollup), values)


async def add_matchup(
    session: AsyncSession,
    champion_id: int,
    position: str,
    patch: str,
    opponent_id: int,
    games: int,
    wins: int,
    gold_diff_sum: int = 0,
    queue_id: int = 420,
) -> None:
    await session.execute(
        insert(ChampionMatchup).values(
            champion_id=champion_id,
            position=position,
            patch=patch,
            queue_id=queue_id,
            opponent_id=opponent_id,
            games=games,
            wins=wins,
            gold_diff_sum=gold_diff_sum,
        )
    )


# --- patches ---------------------------------------------------------------------------------


async def test_patches_newest_first_numeric(client, session) -> None:
    await add_total(session, "16.8", 420, 50, 10)
    await add_total(session, "16.9", 420, 100, 30)
    await add_total(session, "16.9", 440, 20, 5)
    await add_total(session, "16.10", 420, 80, 20)
    await add_total(session, "16.11", 420, 0, 0)  # no counted games: not a patch
    m1 = await add_match(session, make_match_json("NA1_1"))
    await add_match(session, make_match_json("NA1_2"))
    await add_match(session, make_match_json("NA1_3"))
    await session.execute(
        update(Match).where(Match.match_id == m1.match["match_id"]).values(champ_rollup=1)
    )
    await session.execute(update(Match).where(Match.match_id == "NA1_3").values(champ_rollup=3))
    await session.commit()

    body = (await client.get(f"{URL}/patches")).json()
    assert [p["patch"] for p in body["patches"]] == ["16.10", "16.9", "16.8"]
    assert body["patches"][1] == {"patch": "16.9", "matches": 120, "timeline_matches": 35}
    assert body["recent"] == ["16.10", "16.9"]
    assert body["pending_matches"] == 2  # NA1_2 (0) and NA1_3 (3)


async def test_empty_database(client, session) -> None:
    body = (await client.get(f"{URL}/patches")).json()
    assert body == {"patches": [], "recent": [], "pending_matches": 0}
    listing = (await client.get(URL)).json()
    assert listing["patches"] == [] and listing["rows"] == [] and listing["total_matches"] == 0


# --- list ------------------------------------------------------------------------------------


async def seed_list(session: AsyncSession) -> None:
    for patch, solo, flex in (("16.8", 100, 0), ("16.9", 200, 50), ("16.10", 300, 50)):
        await add_total(session, patch, 420, solo)
        if flex:
            await add_total(session, patch, 440, flex)
    # Ahri: mostly mid, some top; one old-patch game that "recent" does not cover.
    await add_stat(
        session, AHRI, "MIDDLE", "16.10", games=60, wins=33, kills=300, deaths=120, assists=360
    )
    await add_stat(
        session, AHRI, "MIDDLE", "16.9", games=40, wins=20, kills=200, deaths=80, assists=240
    )
    await add_stat(session, AHRI, "TOP", "16.10", games=10, wins=3, kills=20, deaths=40, assists=20)
    await add_stat(session, AHRI, "MIDDLE", "16.9", queue_id=440, games=10, wins=10)
    await add_stat(session, AHRI, "MIDDLE", "16.8", games=500, wins=0)
    await add_stat(session, ZED, "MIDDLE", "16.10", games=20, wins=12)
    # Syndra only on the old patch.
    await add_stat(session, SYNDRA, "MIDDLE", "16.8", games=30, wins=15)
    await add_ban(session, AHRI[0], "16.10", 45)
    await add_ban(session, AHRI[0], "16.9", 15)
    await add_ban(session, AHRI[0], "16.9", 20, queue_id=440)
    await add_ban(session, SYNDRA[0], "16.10", 7)
    await session.commit()


async def test_list_recent(client, session) -> None:
    await seed_list(session)
    body = (await client.get(URL)).json()
    assert body["patch"] == "recent"
    assert body["patches"] == ["16.10", "16.9"]
    assert body["queue"] == "all"
    assert body["total_matches"] == 600
    assert [r["champion_name"] for r in body["rows"]] == ["Ahri", "Zed"]
    ahri = body["rows"][0]
    assert ahri["champion_id"] == 103
    assert ahri["games"] == 120 and ahri["wins"] == 66
    assert ahri["win_rate"] == pytest.approx(0.55)
    assert ahri["pick_rate"] == pytest.approx(0.2)
    assert ahri["ban_rate"] == pytest.approx(80 / 600, abs=1e-4)
    # (300+200+20+50 + 360+240+20+60) / (120+80+40+40)
    assert ahri["kda"] == pytest.approx(1250 / 280, abs=1e-4)
    assert [(r["position"], r["games"]) for r in ahri["roles"]] == [("MIDDLE", 110), ("TOP", 10)]
    assert ahri["roles"][0]["share"] == pytest.approx(110 / 120, abs=1e-4)
    assert ahri["roles"][1]["win_rate"] == pytest.approx(0.3)


async def test_list_queue_filter(client, session) -> None:
    await seed_list(session)
    body = (await client.get(URL, params={"queue": "solo"})).json()
    assert body["total_matches"] == 500
    ahri = body["rows"][0]
    assert ahri["games"] == 110
    assert ahri["ban_rate"] == pytest.approx(60 / 500)
    flex = (await client.get(URL, params={"queue": "flex"})).json()
    assert flex["total_matches"] == 100
    assert [(r["champion_name"], r["games"]) for r in flex["rows"]] == [("Ahri", 10)]


async def test_list_single_patch_and_season(client, session) -> None:
    await seed_list(session)
    one = (await client.get(URL, params={"patch": "16.9"})).json()
    assert one["patches"] == ["16.9"]
    assert one["total_matches"] == 250
    assert [r["games"] for r in one["rows"]] == [50]
    season = (await client.get(URL, params={"patch": "season"})).json()
    assert season["patches"] == ["16.10", "16.9", "16.8"]
    assert [r["champion_name"] for r in season["rows"]] == ["Ahri", "Syndra", "Zed"]


async def test_unknown_patch_is_400(client, session) -> None:
    await seed_list(session)
    for url in (URL, f"{URL}/Ahri"):
        resp = await client.get(url, params={"patch": "16.99"})
        assert resp.status_code == 400
        assert resp.json()["code"] == "unknown_patch"


# --- detail ----------------------------------------------------------------------------------


async def test_unknown_champion_is_404(client, session) -> None:
    await seed_list(session)
    for name in ("Nope", "9999", "Ah"):
        resp = await client.get(f"{URL}/{name}")
        assert resp.status_code == 404, name
        assert resp.json()["code"] == "champion_not_found"
    resp = await client.get(f"{URL}/Nope/squad")
    assert resp.status_code == 404


async def test_non_ascii_digits_are_not_a_champion_id(client, session) -> None:
    """str.isdigit() accepts "²" (int() then raised: a 500) and "١٠٣" (Arabic-Indic 103,
    which int() turned into Ahri's id); only ASCII digits are an id."""
    await seed_list(session)
    for name in ("²", "١٠٣"):
        for path in (f"{URL}/{name}", f"{URL}/{name}/squad", f"{URL}/{name}/players/x"):
            resp = await client.get(path)
            assert resp.status_code == 404, (path, resp.status_code)
            assert resp.json()["code"] == "champion_not_found"


async def test_detail_key_is_case_insensitive_or_numeric(client, session) -> None:
    await seed_list(session)
    await add_stat(session, WUKONG, "TOP", "16.10", games=5, wins=2)
    await session.commit()
    for name in ("ahri", "AHRI", "103"):
        body = (await client.get(f"{URL}/{name}")).json()
        assert body["champion_id"] == 103 and body["champion_name"] == "Ahri"
    body = (await client.get(f"{URL}/monkeyking")).json()
    assert body["champion_name"] == "MonkeyKing"


async def test_detail_without_games_in_window(client, session) -> None:
    await seed_list(session)
    resp = await client.get(f"{URL}/syndra")
    assert resp.status_code == 200
    body = resp.json()
    assert body["champion_id"] == 134 and body["champion_name"] == "Syndra"
    assert body["games"] == 0 and body["win_rate"] is None
    assert body["roles"] == [] and body["role"] is None and body["detail"] is None
    assert body["ban_rate"] == pytest.approx(7 / 600, abs=1e-4)
    assert body["total_matches"] == 600


async def test_detail_roles_shown_and_role_param(client, session) -> None:
    await add_total(session, "16.10", 420, 1000)
    await add_stat(session, AHRI, "MIDDLE", "16.10", games=200, wins=100)
    await add_stat(session, AHRI, "TOP", "16.10", games=30, wins=12)  # 12%: shown
    await add_stat(session, AHRI, "JUNGLE", "16.10", games=20, wins=5)  # 8%: hidden
    await add_stat(session, AHRI, "UTILITY", "16.9", games=50, wins=25)  # outside the window
    await add_total(session, "16.9", 420, 1)
    await add_total(session, "16.8", 420, 1)
    await session.commit()

    body = (await client.get(f"{URL}/Ahri", params={"patch": "16.10"})).json()
    assert [(r["position"], r["shown"]) for r in body["roles"]] == [
        ("MIDDLE", True),
        ("TOP", True),
        ("JUNGLE", False),
    ]
    assert body["games"] == 250 and body["pick_rate"] == pytest.approx(0.25)
    assert body["role"] == "MIDDLE"
    assert body["detail"]["stats"]["games"] == 200
    assert body["detail"]["stats"]["pick_rate"] == pytest.approx(0.2)

    top = (await client.get(f"{URL}/Ahri", params={"patch": "16.10", "role": "TOP"})).json()
    assert top["role"] == "TOP" and top["detail"]["stats"]["games"] == 30
    # A role without games in the window falls back to the most played one.
    fallback = (
        await client.get(f"{URL}/Ahri", params={"patch": "16.10", "role": "UTILITY"})
    ).json()
    assert fallback["role"] == "MIDDLE"
    bad = await client.get(f"{URL}/Ahri", params={"role": "MID"})
    assert bad.status_code == 422


async def test_detail_most_played_role_always_shown(client, session) -> None:
    await add_total(session, "16.10", 420, 100)
    await add_stat(session, AHRI, "MIDDLE", "16.10", games=5, wins=3)
    await session.commit()
    body = (await client.get(f"{URL}/Ahri")).json()
    assert body["roles"][0]["shown"] is True
    assert body["detail"]["stats"]["small_sample"] is True


MID_ROLLUPS: list[tuple[str, str, int, int] | tuple[str, str, int, int, int]] = [
    # Starting items (over 600 timeline games: threshold max(8, 6) = 8).
    ("start", "1056-2003-2003", 400, 210),
    ("start", "1082-2003", 150, 70),
    ("start", "1055", 7, 7),
    # Core: A most common, B best after shrinkage, C too few games for best, D high raw WR.
    ("core", "3078-3071-6333", 300, 150, 300 * 1500),
    ("core", "6655-4645-3089", 100, 65, 100 * 1400),
    ("core", "3152-4645-3089", 19, 19, 19 * 1300),
    ("core", "3165-3089-4645", 40, 28, 40 * 1600),
    # Boots (over 1000 games), "0" = no boots.
    ("boots", "3020", 600, 310),
    ("boots", "3158", 300, 150),
    ("boots", "0", 100, 40),
    ("item4", "3135", 200, 110),
    ("item5", "3089", 150, 80),
    ("item5", "3102", 5, 5),
    # Popular items: 12 with enough games.
    *[("item", str(3000 + i), 500 - i * 10, 250) for i in range(12)],
    ("item", "3999", 9, 9),  # under 1% of 1000
    # Runes.
    ("rune_page", "8200-8300-8112-8139-8138-8135-8345-8347", 700, 360),
    ("rune_page", "8100-8200-8229-8226-8210-8237-8126-8135", 5, 5),
    ("rune", "8112", 700, 360),
    ("rune", "8128", 50, 20),
    ("rune", "9999", 9, 9),  # 0.9%: not a pick
    ("shards", "5008-5008-5011", 600, 300),
    ("shard", "0:5008", 900, 460),
    ("shard", "1:5008", 800, 400),
    ("shard", "2:5011", 700, 350),
    ("shard", "2:5001", 300, 150),
    # Spells over 1000 games: 1% cut and top 5.
    ("spells", "4-14", 500, 250),
    ("spells", "4-12", 300, 150),
    ("spells", "4-7", 100, 50),
    ("spells", "4-6", 50, 25),
    ("spells", "4-11", 20, 10),
    ("spells", "3-4", 12, 6),
    ("spells", "1-4", 9, 9),
    # Skills over 600 timeline games.
    ("skill_max", "1-3-2", 400, 200),
    ("skill_max", "1-2-3", 100, 50),
    ("skill_at", "1:1", 500, 250),
    ("skill_at", "1:3", 100, 50),
    ("skill_at", "2:1", 300, 150),  # illegal: Q is capped at 1 point at level 2
    ("skill_at", "2:3", 250, 125),
    ("skill_at", "3:2", 400, 200),
    ("skill_at", "6:4", 590, 300),
]


async def seed_detail(session: AsyncSession) -> None:
    await add_total(session, "16.10", 420, 1500, 900)
    await add_total(session, "16.9", 420, 500, 300)
    await add_stat(session, AHRI, "MIDDLE", "16.10", games=700, wins=350, timeline_games=400)
    await add_stat(session, AHRI, "MIDDLE", "16.9", games=300, wins=150, timeline_games=200)
    await add_stat(session, ZED, "MIDDLE", "16.10", games=50, wins=20)
    await add_stat(session, SYNDRA, "MIDDLE", "16.10", games=50, wins=20)
    await add_stat(session, WUKONG, "TOP", "16.10", games=50, wins=20)
    # Rollups split over two patches must be summed.
    await add_rollups(session, AHRI[0], "MIDDLE", "16.10", MID_ROLLUPS)
    await add_rollups(session, AHRI[0], "MIDDLE", "16.9", [("spells", "3-4", 1, 1)])
    # Other roles are not mixed in.
    await add_rollups(session, AHRI[0], "TOP", "16.10", [("spells", "4-12", 900, 900)])
    # Matchups: Zed 30 games (split over patches), Syndra 10, Wukong 9 (under min_games).
    await add_matchup(session, AHRI[0], "MIDDLE", "16.10", ZED[0], 20, 14, 20 * 300)
    await add_matchup(session, AHRI[0], "MIDDLE", "16.9", ZED[0], 10, 6, 10 * -150)
    await add_matchup(session, AHRI[0], "MIDDLE", "16.10", SYNDRA[0], 10, 2, -5000)
    await add_matchup(session, AHRI[0], "MIDDLE", "16.10", WUKONG[0], 9, 9, 0)
    await session.commit()


async def test_detail_stats_and_builds(client, session) -> None:
    await seed_detail(session)
    body = (await client.get(f"{URL}/Ahri")).json()
    assert body["patches"] == ["16.10", "16.9"] and body["total_matches"] == 2000
    detail = body["detail"]
    stats = detail["stats"]
    assert stats["games"] == 1000 and stats["timeline_games"] == 600
    assert stats["win_rate"] == 0.5
    assert stats["avg_kills"] == 5 and stats["avg_deaths"] == 4 and stats["avg_assists"] == 6
    assert stats["kda"] == 2.75
    assert stats["avg_cs"] == 180 and stats["cs_per_min"] == 6.0
    assert stats["avg_damage"] == 20_000 and stats["avg_gold"] == 11_000
    assert stats["avg_duration_s"] == 1800
    assert stats["small_sample"] is False

    builds = detail["builds"]
    assert [o["items"] for o in builds["starting"]] == [[1056, 2003, 2003], [1082, 2003]]
    assert builds["starting"][0]["pick_rate"] == pytest.approx(400 / 600, abs=1e-4)
    assert builds["starting"][0]["avg_time_s"] is None
    core = builds["core"]
    assert [o["items"][0] for o in core] == [3078, 6655, 3165, 3152]
    assert core[0]["avg_time_s"] == 1500
    assert builds["core_best"]["items"] == [6655, 4645, 3089]
    assert builds["core_best"]["win_rate"] == 0.65  # raw, not shrunk
    assert builds["core_best"]["avg_time_s"] == 1400
    assert [o["items"] for o in builds["boots"]] == [[3020], [3158]]
    assert builds["no_boots_rate"] == 0.1
    assert [s["slot"] for s in builds["slots"]] == [4, 5, 6]
    assert [o["items"] for o in builds["slots"][1]["options"]] == [[3089]]
    assert builds["slots"][2]["options"] == []
    popular = builds["popular_items"]
    assert len(popular) == 10 and popular[0]["items"] == [3000]
    assert popular[0]["pick_rate"] == 0.5


async def test_detail_runes_spells_skills(client, session) -> None:
    await seed_detail(session)
    detail = (await client.get(f"{URL}/Ahri")).json()["detail"]
    runes = detail["runes"]
    assert len(runes["pages"]) == 1
    page = runes["pages"][0]
    assert page["primary_style_id"] == 8200 and page["secondary_style_id"] == 8300
    assert page["rune_ids"] == [8112, 8139, 8138, 8135, 8345, 8347]
    assert page["pick_rate"] == 0.7
    assert [p["rune_id"] for p in runes["picks"]] == [8112, 8128]
    assert runes["shards"][0]["shard_ids"] == [5008, 5008, 5011]
    assert [(p["row"], p["shard_id"]) for p in runes["shard_picks"]] == [
        (0, 5008),
        (1, 5008),
        (2, 5011),
        (2, 5001),
    ]

    spells = detail["spells"]
    # 3-4 has 12 + 1 games (two patches); 1-4 (9) is under 1% of 1000; top 5.
    assert [o["spell_ids"] for o in spells] == [[4, 14], [4, 12], [4, 7], [4, 6], [4, 11]]

    skills = detail["skills"]
    assert [o["order"] for o in skills["max_orders"]] == [[1, 3, 2], [1, 2, 3]]
    assert skills["max_orders"][0]["pick_rate"] == pytest.approx(400 / 600, abs=1e-4)
    path = skills["path"]
    assert len(path) == 6
    assert path[:3] == [1, 3, 2] and path[5] == 4


async def test_detail_matchups(client, session) -> None:
    await seed_detail(session)
    lanes = (await client.get(f"{URL}/Ahri")).json()["detail"]["matchups"]
    assert lanes["min_games"] == 10
    rows = lanes["rows"]
    assert [(r["champion_id"], r["champion_name"], r["games"]) for r in rows] == [
        (238, "Zed", 30),
        (134, "Syndra", 10),
    ]
    zed = rows[0]
    assert zed["wins"] == 20 and zed["win_rate"] == pytest.approx(0.6667, abs=1e-4)
    # (20 + 20 * 0.5) / (30 + 20)
    assert zed["adjusted_win_rate"] == 0.6
    assert zed["avg_gold_diff"] == pytest.approx((6000 - 1500) / 30, abs=0.1)
    # (2 + 10) / 30
    assert rows[1]["adjusted_win_rate"] == 0.4
    assert rows[1]["avg_gold_diff"] == -500


async def test_detail_no_timeline(client, session) -> None:
    await add_total(session, "16.10", 420, 100)
    await add_stat(session, AHRI, "MIDDLE", "16.10", games=50, wins=25)
    await add_rollups(session, AHRI[0], "MIDDLE", "16.10", [("spells", "4-14", 50, 25)])
    await session.commit()
    detail = (await client.get(f"{URL}/Ahri")).json()["detail"]
    assert detail["skills"] == {"max_orders": [], "path": []}
    assert detail["builds"]["core"] == [] and detail["builds"]["core_best"] is None
    assert detail["matchups"]["rows"] == []
    assert detail["spells"][0]["spell_ids"] == [4, 14]


async def test_core_best_none_when_it_is_the_most_common(client, session) -> None:
    await add_total(session, "16.10", 420, 1000, 1000)
    await add_stat(session, AHRI, "MIDDLE", "16.10", games=500, wins=250, timeline_games=500)
    await add_rollups(
        session,
        AHRI[0],
        "MIDDLE",
        "16.10",
        [("core", "3078-3071-6333", 300, 200, 0), ("core", "6655-4645-3089", 100, 40, 0)],
    )
    await session.commit()
    builds = (await client.get(f"{URL}/Ahri")).json()["detail"]["builds"]
    assert len(builds["core"]) == 2
    assert builds["core_best"] is None


async def test_detail_queue_filter(client, session) -> None:
    await add_total(session, "16.10", 420, 100)
    await add_total(session, "16.10", 440, 100)
    await add_stat(session, AHRI, "MIDDLE", "16.10", games=40, wins=20)
    await add_stat(session, AHRI, "MIDDLE", "16.10", queue_id=440, games=10, wins=10)
    await add_rollups(session, AHRI[0], "MIDDLE", "16.10", [("spells", "4-14", 40, 20)])
    await add_rollups(
        session, AHRI[0], "MIDDLE", "16.10", [("spells", "4-12", 10, 10)], queue_id=440
    )
    await session.commit()
    both = (await client.get(f"{URL}/Ahri")).json()
    assert both["games"] == 50 and both["total_matches"] == 200
    flex = (await client.get(f"{URL}/Ahri", params={"queue": "flex"})).json()
    assert flex["games"] == 10 and flex["total_matches"] == 100
    assert [o["spell_ids"] for o in flex["detail"]["spells"]] == [[4, 12]]


# --- squad -----------------------------------------------------------------------------------

A, B, U = "puuid-a", "puuid-b", "puuid-u"
SEASON = datetime(2026, 3, 1, 20, tzinfo=UTC)


def _game(match_id: str, players: list[tuple[str, str]], *, hour: int, **kwargs: Any):
    """``players``: (puuid, position) on Ahri... in the blue slots; blue wins by default."""
    specs = [
        spec(p, champion=AHRI if i == 0 else ZED, position=pos)
        for i, (p, pos) in enumerate(players)
    ]
    return make_match_json(match_id, specs, start=SEASON + timedelta(hours=hour), **kwargs)


async def test_squad(client, session) -> None:
    await add_summoner(session, A, "Alpha", "NA1", tracked=True, profile_icon_id=7)
    await add_summoner(session, B, "Bravo", "NA1", tracked=True)
    await add_summoner(session, U, "Untracked", "NA1", tracked=False)
    await add_model(session, "v0", active=False)
    await add_model(session, "v1", active=True)
    await add_stat(session, AHRI, "MIDDLE", "16.10", games=1, wins=1)
    await add_stat(session, ZED, "MIDDLE", "16.10", games=1, wins=1)

    # A on Ahri: two solo wins (v1 0.8, v0 0.2), one flex loss on TOP (v1 0.4).
    await add_match(session, _game("NA1_1", [(A, "MIDDLE")], hour=1), scores={A: 0.8})
    await add_match(
        session, _game("NA1_2", [(A, "MIDDLE")], hour=2), scores={A: 0.2}, model_version="v0"
    )
    await add_match(
        session,
        _game("NA1_3", [(A, "TOP")], hour=3, queue_id=440, winning_team=200),
        scores={A: 0.4},
    )
    # B on Ahri once; B on Zed (not counted); U on Ahri (untracked).
    await add_match(session, _game("NA1_4", [(B, "MIDDLE")], hour=4), scores={B: 0.6})
    await add_match(session, _game("NA1_5", [(U, "MIDDLE"), (B, "TOP")], hour=5))
    # Never counted: a crawled game, a preseason game, a remake, an ARAM game.
    await add_match(session, _game("NA1_6", [(A, "MIDDLE")], hour=6))
    await session.execute(update(Match).where(Match.match_id == "NA1_6").values(source="crawl"))
    await add_match(
        session,
        make_match_json(
            "NA1_7",
            [spec(A, champion=AHRI, position="MIDDLE")],
            start=datetime(2025, 12, 1, tzinfo=UTC),
        ),
    )
    await add_match(session, _game("NA1_8", [(A, "MIDDLE")], hour=8, duration_s=200))
    await add_match(session, _game("NA1_9", [(A, "MIDDLE")], hour=9, queue_id=450))
    await session.commit()

    body = (await client.get(f"{URL}/ahri/squad")).json()
    assert body["champion_id"] == 103 and body["champion_name"] == "Ahri"
    assert body["model_version"] == "v1"
    assert [r["puuid"] for r in body["rows"]] == [A, B]
    a = body["rows"][0]
    assert a["game_name"] == "Alpha" and a["profile_icon_id"] == 7
    assert a["games"] == 3 and a["wins"] == 2
    assert a["win_rate"] == pytest.approx(0.6667, abs=1e-4)
    assert a["avg_ai_score"] == pytest.approx(0.6)  # v1 only: (0.8 + 0.4) / 2
    assert a["main_position"] == "MIDDLE"
    assert a["last_match_id"] == "NA1_3"
    assert a["last_played"].startswith("2026-03-01T23:00")
    b = body["rows"][1]
    assert b["games"] == 1 and b["avg_ai_score"] == 0.6

    solo = (await client.get(f"{URL}/103/squad", params={"queue": "solo"})).json()
    assert [(r["puuid"], r["games"]) for r in solo["rows"]] == [(A, 2), (B, 1)]
    assert solo["rows"][0]["last_match_id"] == "NA1_2"
    flex = (await client.get(f"{URL}/Ahri/squad", params={"queue": "flex"})).json()
    assert [(r["puuid"], r["main_position"]) for r in flex["rows"]] == [(A, "TOP")]


async def test_squad_without_roster(client, session) -> None:
    await add_stat(session, AHRI, "MIDDLE", "16.10", games=1, wins=1)
    await session.commit()
    body = (await client.get(f"{URL}/Ahri/squad")).json()
    assert body["rows"] == [] and body["model_version"] is None
