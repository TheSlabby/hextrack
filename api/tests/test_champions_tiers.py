"""Champion tiers: the pure rules (:mod:`hextrack.stats.champions.tiers`) and the ``tier`` on
the champion list and detail."""

from __future__ import annotations

import math
import random

import pytest

from hextrack.stats.champions.cache import CHAMPION_CACHE
from hextrack.stats.champions.tiers import (
    PRIOR_GAMES,
    RoleLine,
    role_tiers,
    score_roles,
    tier_counts,
)
from tests.test_champions_api import URL, add_ban, add_stat, add_total


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    CHAMPION_CACHE.clear()


def mid(cid: int, games: int, wins: int, position: str = "MIDDLE") -> RoleLine:
    return RoleLine(champion_id=cid, position=position, games=games, wins=wins)


# --- tier counts --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "counts"),
    [
        (0, [0, 0, 0, 0, 0]),
        (4, [0, 0, 0, 0, 0]),
        (5, [1, 1, 1, 1, 1]),
        (6, [1, 1, 2, 1, 1]),
        (10, [1, 2, 4, 2, 1]),
        (20, [2, 4, 7, 4, 3]),
        (40, [4, 8, 14, 8, 6]),
        (100, [10, 20, 35, 20, 15]),
    ],
)
def test_tier_counts(n: int, counts: list[int]) -> None:
    assert tier_counts(n) == counts


def test_tier_counts_every_tier_used_and_sum() -> None:
    for n in range(5, 200):
        counts = tier_counts(n)
        assert sum(counts) == n
        assert all(c >= 1 for c in counts), n


# --- eligibility --------------------------------------------------------------------------


def test_min_games_and_role_share() -> None:
    # 5 solid mid champions (so the role is ranked) plus the edge cases.
    lines = [mid(cid, 100 + cid, 50 + cid) for cid in range(1, 6)]
    lines.append(mid(10, 29, 20))  # under 30 games
    lines.append(mid(11, 30, 10))  # exactly 30: eligible
    tiers = role_tiers(lines, {}, total_matches=1000)
    assert (10, "MIDDLE") not in tiers
    assert (11, "MIDDLE") in tiers
    assert len(tiers) == 6

    # A big role: 0.5% of 20_000 role games = 100, so 60 games is not enough.
    big = [mid(cid, 3000 + cid, 1500) for cid in range(1, 7)]
    big.append(mid(20, 60, 40))
    big.append(mid(21, 100, 40))
    tiers = role_tiers(big, {}, total_matches=10_000)
    assert (20, "MIDDLE") not in tiers
    assert (21, "MIDDLE") in tiers


def test_champion_share_or_main_role() -> None:
    lines = [mid(cid, 200, 100) for cid in range(1, 6)]
    # Champion 7: 1000 top games, 80 mid (7.4% of its games): not ranked mid.
    lines += [mid(7, 1000, 500, "TOP"), mid(7, 80, 60)]
    # Champion 8: 400 top, 60 mid (13%): ranked in both.
    lines += [mid(8, 400, 200, "TOP"), mid(8, 60, 30)]
    # Top has only 2 eligible champions: nobody gets a top tier.
    tiers = role_tiers(lines, {}, total_matches=2000)
    assert (7, "MIDDLE") not in tiers
    assert (8, "MIDDLE") in tiers
    assert not any(pos == "TOP" for _cid, pos in tiers)


def test_fewer_than_five_eligible_gives_none() -> None:
    lines = [mid(cid, 200, 100 + cid) for cid in range(1, 5)]
    lines.append(mid(9, 10, 10))  # a fifth champion, but ineligible
    assert role_tiers(lines, {1: 50}, total_matches=1000) == {}
    scored = score_roles(lines, {}, 1000)["MIDDLE"]
    assert len(scored) == 4 and all(s.tier is None for s in scored)


# --- score and tiers ----------------------------------------------------------------------


def test_score_formula() -> None:
    lines = [
        mid(1, 300, 180),
        mid(2, 200, 100),
        mid(3, 100, 45),
        mid(4, 400, 190),
        mid(5, 50, 20),
    ]
    bans = {1: 100, 3: 20}
    total = 1000
    by_id = {s.champion_id: s for s in score_roles(lines, bans, total)["MIDDLE"]}

    p = sum(line.wins for line in lines) / sum(line.games for line in lines)

    def z(values: list[float]) -> list[float]:
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        return [(v - mean) / std for v in values]

    adj = [(line.wins + PRIOR_GAMES * p) / (line.games + PRIOR_GAMES) for line in lines]
    pick = [math.log(line.games / total) for line in lines]
    ban = [bans.get(line.champion_id, 0) / total for line in lines]
    expected = [a + 0.5 * b + 0.25 * c for a, b, c in zip(z(adj), z(pick), z(ban), strict=True)]
    for line, score in zip(lines, expected, strict=True):
        assert by_id[line.champion_id].score == pytest.approx(score)
        assert by_id[line.champion_id].adjusted_win_rate == pytest.approx(
            (line.wins + PRIOR_GAMES * p) / (line.games + PRIOR_GAMES)
        )
    ranked = sorted(by_id.values(), key=lambda s: -s.score)
    assert [s.tier for s in ranked] == ["S", "A", "B", "C", "D"]


def test_win_rate_orders_equal_champions() -> None:
    # Same games, no bans: only the win rate differs, so the tiers follow it.
    lines = [mid(cid, 200, 80 + 10 * cid) for cid in range(1, 11)]
    tiers = role_tiers(lines, {}, total_matches=2000)
    assert [tiers[(cid, "MIDDLE")] for cid in range(10, 0, -1)] == [
        "S",
        "A",
        "A",
        "B",
        "B",
        "B",
        "B",
        "C",
        "C",
        "D",
    ]


def test_ban_rate_breaks_otherwise_equal() -> None:
    lines = [mid(cid, 200, 100) for cid in range(1, 6)]
    tiers = role_tiers(lines, {3: 150}, total_matches=1000)
    assert tiers[(3, "MIDDLE")] == "S"


def test_roles_are_ranked_separately() -> None:
    lines = [mid(cid, 200, 100 + cid) for cid in range(1, 6)]
    lines += [mid(cid, 200, 100 - cid, "UTILITY") for cid in range(11, 16)]
    tiers = role_tiers(lines, {}, total_matches=2000)
    assert tiers[(5, "MIDDLE")] == "S" and tiers[(11, "UTILITY")] == "S"
    assert tiers[(1, "MIDDLE")] == "D" and tiers[(15, "UTILITY")] == "D"


def test_deterministic_and_ties() -> None:
    rng = random.Random(7)
    lines = [
        mid(cid, rng.randint(30, 900), 0, pos) for cid in range(1, 60) for pos in ("MIDDLE", "TOP")
    ]
    lines = [
        RoleLine(ln.champion_id, ln.position, ln.games, ln.games // 2 + ln.champion_id % 7)
        for ln in lines
    ]
    bans = {cid: rng.randint(0, 300) for cid in range(1, 60)}
    first = role_tiers(lines, bans, 20_000)
    for _ in range(5):
        shuffled = lines[:]
        rng.shuffle(shuffled)
        assert role_tiers(shuffled, dict(reversed(list(bans.items()))), 20_000) == first
    # Identical champions: the tie goes to more games, then the lower id.
    same = [mid(cid, 200, 100) for cid in (9, 3, 5, 1, 7)]
    tiers = role_tiers(same, {}, 1000)
    assert [tiers[(cid, "MIDDLE")] for cid in (1, 3, 5, 7, 9)] == ["S", "A", "B", "C", "D"]


# --- list and detail ----------------------------------------------------------------------

MID_CHAMPS = [
    # (id, key, games, wins)
    (103, "Ahri", 400, 220),
    (238, "Zed", 300, 140),
    (134, "Syndra", 250, 130),
    (61, "Orianna", 200, 96),
    (7, "Leblanc", 150, 70),
    (99, "Lux", 120, 66),
]


async def seed_tiers(session) -> None:
    await add_total(session, "16.10", 420, 1000)
    await add_total(session, "16.10", 440, 200)
    await add_total(session, "16.9", 420, 800)
    for cid, key, games, wins in MID_CHAMPS:
        await add_stat(session, (cid, key), "MIDDLE", "16.10", games=games, wins=wins)
    # Lux also plays support a lot (its main role) and a little top (under 10%: no tier).
    await add_stat(session, (99, "Lux"), "UTILITY", "16.10", games=300, wins=150)
    await add_stat(session, (99, "Lux"), "TOP", "16.10", games=40, wins=20)
    # Flex and the older patch change the numbers for those windows.
    await add_stat(session, (238, "Zed"), "MIDDLE", "16.10", queue_id=440, games=100, wins=90)
    await add_stat(session, (103, "Ahri"), "MIDDLE", "16.9", games=300, wins=120)
    await add_ban(session, 238, "16.10", 300)
    await session.commit()


def list_tiers(body: dict) -> dict[tuple[str, str], str | None]:
    return {
        (row["champion_name"], role["position"]): role["tier"]
        for row in body["rows"]
        for role in row["roles"]
    }


async def test_list_and_detail_tiers_agree(client, session) -> None:
    await seed_tiers(session)
    for params in (
        {"patch": "16.10"},
        {"patch": "16.10", "queue": "solo"},
        {"patch": "season"},
        {},
    ):
        CHAMPION_CACHE.clear()
        listing = (await client.get(URL, params=params)).json()
        tiers = list_tiers(listing)
        mids = {name: tier for (name, pos), tier in tiers.items() if pos == "MIDDLE"}
        assert all(t is not None for t in mids.values()), (params, mids)
        assert sorted(mids.values()) == ["A", "B", "B", "C", "D", "S"]
        assert tiers[("Lux", "TOP")] is None
        assert tiers[("Lux", "UTILITY")] is None  # only one eligible support
        for _cid, key, *_ in MID_CHAMPS:
            detail = (await client.get(f"{URL}/{key}", params=params)).json()
            for role in detail["roles"]:
                assert role["tier"] == tiers[(key, role["position"])], (params, key, role)


async def test_tiers_follow_window(client, session) -> None:
    await seed_tiers(session)
    solo = list_tiers((await client.get(URL, params={"patch": "16.10", "queue": "solo"})).json())
    both = list_tiers((await client.get(URL, params={"patch": "16.10"})).json())
    season = list_tiers((await client.get(URL, params={"patch": "season"})).json())
    # Zed's 90% flex games lift it once flex counts; Ahri's bad 16.9 drops it for the season.
    order = "SABCD"
    assert order.index(both[("Zed", "MIDDLE")]) <= order.index(solo[("Zed", "MIDDLE")])
    assert order.index(season[("Ahri", "MIDDLE")]) >= order.index(both[("Ahri", "MIDDLE")])


async def test_no_tiers_without_enough_champions(client, session) -> None:
    await add_total(session, "16.10", 420, 500)
    await add_stat(session, (103, "Ahri"), "MIDDLE", "16.10", games=200, wins=100)
    await add_stat(session, (238, "Zed"), "MIDDLE", "16.10", games=200, wins=100)
    await session.commit()
    listing = (await client.get(URL)).json()
    assert all(role["tier"] is None for row in listing["rows"] for role in row["roles"])
    detail = (await client.get(f"{URL}/Ahri")).json()
    assert detail["roles"][0]["tier"] is None
