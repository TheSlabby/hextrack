"""Pure per-match contributions (stats/champions/rollup.py), no database."""

from __future__ import annotations

import json

import pytest

from hextrack.stats.champions import (
    KIND_BOOTS,
    KIND_CORE,
    KIND_ITEM,
    KIND_ITEM4,
    KIND_ITEM5,
    KIND_ITEM6,
    KIND_RUNE,
    KIND_RUNE_PAGE,
    KIND_SHARD,
    KIND_SHARDS,
    KIND_SKILL_AT,
    KIND_SKILL_MAX,
    KIND_SPELLS,
    KIND_START,
    TIMELINE_KINDS,
)
from hextrack.stats.champions.items import ItemCatalog
from hextrack.stats.champions.rollup import (
    Increments,
    MatchLine,
    PlayerLine,
    TimelineLine,
    completed_order,
    final_boots,
    final_items,
    lane_opponents,
    skill_max_order,
    starting_items,
    timeline_keys,
)
from tests.conftest import FIXTURES_DIR

PATCH, QUEUE = "16.17", 420
RUNES = [8010, 9111, 9104, 8299, 8444, 8451]


@pytest.fixture(scope="module")
def catalog() -> ItemCatalog:
    return ItemCatalog.from_item_json(json.loads((FIXTURES_DIR / "item_sample.json").read_text()))


def player(
    pid: int,
    champion_id: int,
    position: str,
    *,
    win: bool | None = None,
    gold: int = 10_000,
    items: tuple[int, ...] = (6692, 3047, 6333, 3071, 1053, 0, 3340),
    runes: list[int] | None = RUNES,
) -> PlayerLine:
    team = 100 if pid <= 5 else 200
    return PlayerLine(
        participant_id=pid,
        team_id=team,
        champion_id=champion_id,
        champion_name=f"Champ{champion_id}",
        position=position,
        win=(team == 100) if win is None else win,
        kills=5,
        deaths=3,
        assists=7,
        damage=20_000,
        cs=180,
        gold=gold,
        items=list(items),
        spells=(14, 4),
        primary_style_id=8000,
        secondary_style_id=8400,
        rune_ids=runes,
        stat_shards=[5005, 5008, 5011],
    )


ROLE_ORDER = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")


def lobby(**overrides: PlayerLine) -> list[PlayerLine]:
    players = [player(i + 1, 10 + i, ROLE_ORDER[i % 5]) for i in range(10)]
    for key, value in overrides.items():
        players[int(key[1:]) - 1] = value
    return players


def match(players: list[PlayerLine], bans: list[int] | None = None) -> MatchLine:
    return MatchLine("NA1_1", PATCH, QUEUE, 1800, bans, players)


# --- rules --------------------------------------------------------------------------------


def test_starting_items_are_the_first_90s_sorted_without_trinkets(catalog) -> None:
    tl = TimelineLine(
        purchases=[3340, 2003, 1055, 2003, 1001],
        purchase_s=[0, 3, 4, 90, 400],
        skill_order=[],
    )
    assert starting_items(tl, catalog) == [1055, 2003, 2003]


def test_core_order_after_undo_dedupes_and_folds(catalog) -> None:
    # What the timeline extraction leaves after an undone Infinity Edge at 590 s.
    tl = TimelineLine(
        purchases=[1055, 1037, 3071, 3047, 6692, 1036, 3071, 3004, 3042, 6333, 3031],
        purchase_s=[5, 300, 600, 700, 900, 1000, 1100, 1200, 1250, 1500, 1800],
        skill_order=[],
    )
    assert completed_order(tl, catalog) == [
        (3071, 600),
        (6692, 900),
        (3004, 1200),
        (6333, 1500),
        (3031, 1800),
    ]
    keys = timeline_keys(tl, catalog)
    assert (KIND_CORE, "3071-6692-3004", 1200) in keys
    assert (KIND_ITEM4, "6333", 0) in keys
    assert (KIND_ITEM5, "3031", 0) in keys
    assert not any(kind == KIND_ITEM6 for kind, _, _ in keys)


def test_no_core_with_fewer_than_three_items(catalog) -> None:
    tl = TimelineLine(purchases=[3071, 6692], purchase_s=[600, 900], skill_order=[])
    assert not any(kind == KIND_CORE for kind, _, _ in timeline_keys(tl, catalog))


@pytest.mark.parametrize(
    ("items", "boots"),
    [
        ((6692, 3047, 6333, 0, 0, 0, 3340), "3047"),
        ((3172, 3031, 0, 0, 0, 0, 3363), "3006"),  # Gunmetal Greaves -> Berserker's
        ((1001, 3031, 0, 0, 0, 0, 3363), "0"),  # plain Boots are not tier 2
        ((3031, 3036, 0, 0, 0, 0, 3363), "0"),
        ((3031, 0, 0, 0, 0, 0, 3047), "0"),  # item6 is the trinket slot
    ],
)
def test_final_boots(catalog, items, boots) -> None:
    assert final_boots(items, catalog) == boots


def test_final_boots_reads_the_role_quest_slot(catalog) -> None:
    # Bot lane keeps its boots in roleBoundItem since the 2026 season.
    assert final_boots((3031, 3036, 0, 0, 0, 0, 3363), catalog, 3006) == "3006"
    assert final_boots((3031, 0, 0, 0, 0, 0, 3363), catalog, 0) == "0"
    assert final_boots((3031, 0, 0, 0, 0, 0, 3363), catalog, None) == "0"


def test_final_items_are_distinct_completed_non_boots(catalog) -> None:
    items = (3042, 3047, 3004, 1037, 3877, 6333, 3071)  # slot 6 (trinket) ignored
    assert final_items(items, catalog) == [3004, 6333]


@pytest.mark.parametrize(
    ("order", "maxed"),
    [
        ([1, 3, 2, 1, 1, 4, 1, 1, 3, 3, 4, 3, 3, 2, 2, 4, 2, 2], [1, 3, 2]),
        ([1, 2, 3, 1], [1, 2, 3]),
        ([2, 3, 3], [3, 2, 1]),
        ([3, 3, 3, 3, 4, 3, 2], [3, 2, 1]),
    ],
)
def test_skill_max_order(order, maxed) -> None:
    assert skill_max_order(order) == maxed


def test_skill_at_levels(catalog) -> None:
    order = [1, 2, 3, 1, 1, 4] + [1] * 20
    keys = [key for kind, key, _ in timeline_keys(TimelineLine([], [], order), catalog)]
    at = [k for k in keys if ":" in k]
    assert at[:6] == ["1:1", "2:2", "3:3", "4:1", "5:1", "6:4"]
    assert len(at) == 18


def test_lane_opponents_need_exactly_one_per_team() -> None:
    players = lobby(p2=player(2, 11, "TOP"))  # blue has two TOPs, no JUNGLE
    opponents = lane_opponents(players)
    assert 1 not in opponents and 2 not in opponents and 6 not in opponents
    assert opponents[3].participant_id == 8
    assert opponents[8].participant_id == 3
    assert 7 not in opponents  # red jungle has no blue jungler


# --- accumulator --------------------------------------------------------------------------


def test_full_match_increments(catalog) -> None:
    inc = Increments()
    players = lobby(p1=player(1, 10, "TOP", gold=12_000), p6=player(6, 15, "TOP", gold=9_500))
    used = inc.add_match(match(players, bans=[157, 157, 238, -1]), {}, catalog)
    assert used is False
    assert inc.totals == {(PATCH, QUEUE): [1, 0]}
    assert dict(inc.bans) == {(PATCH, QUEUE, 157): 1, (PATCH, QUEUE, 238): 1}

    top = inc.stats[(10, "TOP", PATCH, QUEUE)]
    assert (top.champion_key, top.games, top.wins, top.kills, top.cs, top.gold) == (
        "Champ10",
        1,
        1,
        5,
        180,
        12_000,
    )
    assert (top.duration_s, top.timeline_games, top.timeline_wins) == (1800, 0, 0)
    assert inc.matchups[(10, "TOP", PATCH, QUEUE, 15)] == [1, 1, 2_500]
    assert inc.matchups[(15, "TOP", PATCH, QUEUE, 10)] == [1, 0, -2_500]

    def kinds(champion_id: int, position: str) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for (cid, pos, _, _, kind, key), _value in inc.rollups.items():
            if (cid, pos) == (champion_id, position):
                out.setdefault(kind, set()).add(key)
        return out

    top_kinds = kinds(10, "TOP")
    assert top_kinds[KIND_BOOTS] == {"3047"}
    assert top_kinds[KIND_ITEM] == {"6692", "6333", "3071"}
    assert top_kinds[KIND_RUNE_PAGE] == {"8000-8400-8010-9111-9104-8299-8444-8451"}
    assert top_kinds[KIND_RUNE] == {str(r) for r in RUNES}
    assert top_kinds[KIND_SHARDS] == {"5005-5008-5011"}
    assert top_kinds[KIND_SHARD] == {"0:5005", "1:5008", "2:5011"}
    assert top_kinds[KIND_SPELLS] == {"4-14"}
    assert not TIMELINE_KINDS & top_kinds.keys()
    assert inc.rollups[(10, "TOP", PATCH, QUEUE, KIND_ITEM, "6692")] == [1, 1, 0]


def test_unknown_position_is_skipped_but_the_match_counts(catalog) -> None:
    inc = Increments()
    players = lobby(p3=player(3, 12, "UNKNOWN"))
    inc.add_match(match(players), {}, catalog)
    assert inc.totals[(PATCH, QUEUE)] == [1, 0]
    assert not any(key[0] == 12 for key in inc.stats)
    assert not any(key[0] == 12 for key in inc.rollups)
    assert not any(key[0] == 12 or key[4] == 12 for key in inc.matchups)
    # Blue MIDDLE is empty, so red MIDDLE has no lane opponent either.
    assert not any(key[0] == 17 for key in inc.matchups)


def test_missing_rune_page_skips_rune_kinds_only(catalog) -> None:
    inc = Increments()
    inc.add_match(match(lobby(p1=player(1, 10, "TOP", runes=None))), {}, catalog)
    kinds = {key[4] for key in inc.rollups if key[0] == 10}
    assert KIND_RUNE_PAGE not in kinds and KIND_RUNE not in kinds
    assert {KIND_SHARDS, KIND_BOOTS, KIND_SPELLS} <= kinds


TIMELINE = TimelineLine(
    purchases=[1055, 2003, 3071, 3047, 6692, 6333],
    purchase_s=[2, 3, 600, 700, 900, 1300],
    skill_order=[1, 2, 3, 1, 1, 4, 1, 1],
)


def test_timeline_adds_timeline_kinds(catalog) -> None:
    inc = Increments()
    used = inc.add_match(match(lobby()), {1: TIMELINE}, catalog)
    assert used is True
    assert inc.totals[(PATCH, QUEUE)] == [1, 1]
    top = inc.stats[(10, "TOP", PATCH, QUEUE)]
    assert (top.games, top.timeline_games, top.timeline_wins) == (1, 1, 1)
    other = inc.stats[(11, "JUNGLE", PATCH, QUEUE)]
    assert other.timeline_games == 0
    assert inc.rollups[(10, "TOP", PATCH, QUEUE, KIND_START, "1055-2003")] == [1, 1, 0]
    assert inc.rollups[(10, "TOP", PATCH, QUEUE, KIND_CORE, "3071-6692-6333")] == [1, 1, 1300]
    assert inc.rollups[(10, "TOP", PATCH, QUEUE, KIND_SKILL_MAX, "1-2-3")] == [1, 1, 0]
    assert inc.rollups[(10, "TOP", PATCH, QUEUE, KIND_SKILL_AT, "6:4")] == [1, 1, 0]


def test_timeline_only_adds_just_the_timeline_parts(catalog) -> None:
    inc = Increments()
    used = inc.add_match(match(lobby(), bans=[157]), {1: TIMELINE}, catalog, timeline_only=True)
    assert used is True
    assert inc.totals == {(PATCH, QUEUE): [0, 1]}
    assert not inc.bans
    assert not inc.matchups
    assert list(inc.stats) == [(10, "TOP", PATCH, QUEUE)]
    top = inc.stats[(10, "TOP", PATCH, QUEUE)]
    assert (top.games, top.wins, top.kills, top.duration_s) == (0, 0, 0, 0)
    assert (top.timeline_games, top.timeline_wins) == (1, 1)
    assert {key[4] for key in inc.rollups} <= TIMELINE_KINDS


def test_timeline_only_without_rows_adds_nothing(catalog) -> None:
    inc = Increments()
    assert inc.add_match(match(lobby()), {}, catalog, timeline_only=True) is False
    assert inc.row_count() == 0


def test_increments_sum_across_matches(catalog) -> None:
    inc = Increments()
    inc.add_match(match(lobby()), {}, catalog)
    inc.add_match(match(lobby(), bans=[157]), {}, catalog)
    assert inc.totals[(PATCH, QUEUE)] == [2, 0]
    assert inc.stats[(10, "TOP", PATCH, QUEUE)].games == 2
    assert inc.rollups[(10, "TOP", PATCH, QUEUE, KIND_BOOTS, "3047")] == [2, 2, 0]
