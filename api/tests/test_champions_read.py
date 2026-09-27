"""Pure parts of the champion read side: patch order, option thresholds, core_best
shrinkage, the legal skill path and the TTL cache."""

from __future__ import annotations

import math

import pytest

from hextrack.stats.champions.cache import TTLCache
from hextrack.stats.champions.read import (
    Agg,
    best_core,
    patch_sort_key,
    pick_options,
    skill_path,
)


def assert_legal(path: list[int]) -> None:
    """Standard LoL rules: R only at 6/11/16 (3 points), a basic ability at most 5 points
    and at most ceil(level / 2) points by that level."""
    points = {1: 0, 2: 0, 3: 0, 4: 0}
    for level, slot in enumerate(path, start=1):
        points[slot] += 1
        if slot == 4:
            assert level in (6, 11, 16), (level, path)
            assert points[4] <= 3
        else:
            assert points[slot] <= 5, (level, path)
            assert points[slot] <= math.ceil(level / 2), (level, path)


def test_patch_sort_key_is_numeric() -> None:
    patches = ["16.9", "16.10", "15.24", "16.1"]
    assert sorted(patches, key=patch_sort_key, reverse=True) == ["16.10", "16.9", "16.1", "15.24"]


def test_pick_options_one_percent_cut_and_top_five() -> None:
    aggs = [Agg(str(i), games, 0) for i, games in enumerate([500, 300, 100, 50, 20, 12, 10, 9])]
    kept = pick_options(aggs, 1000)  # threshold max(8, 10) = 10
    assert [a.games for a in kept] == [500, 300, 100, 50, 20]
    everything = pick_options(aggs, 1000, limit=10)
    assert [a.games for a in everything][-1] == 10  # 9 < 1% of 1000


def test_pick_options_eight_game_floor() -> None:
    aggs = [Agg("a", 8, 4), Agg("b", 7, 7)]
    assert [a.key for a in pick_options(aggs, 100)] == ["a"]


def test_pick_options_ties_more_wins_then_key() -> None:
    aggs = [Agg("b", 10, 3), Agg("a", 10, 3), Agg("c", 10, 5)]
    assert [a.key for a in pick_options(aggs, 10)] == ["c", "a", "b"]


def test_best_core_uses_shrunk_win_rate() -> None:
    core = [
        Agg("A", 300, 150),  # 0.50 -> 0.500
        Agg("B", 100, 65),  # 0.65 -> (65 + 15) / 130 = 0.615
        Agg("C", 19, 19),  # 100% but under 20 games
        Agg("D", 40, 28),  # 0.70 -> (28 + 15) / 70 = 0.614
    ]
    best = best_core(core, 600, 0.5)
    assert best is not None and best.key == "B"


def test_best_core_three_percent_threshold() -> None:
    # 3% of 2000 timeline games = 60: the 50-game build is out.
    core = [Agg("A", 1000, 500), Agg("B", 50, 50)]
    best = best_core(core, 2000, 0.5)
    assert best is not None and best.key == "A"
    assert best_core([Agg("A", 10, 10)], 100, 0.5) is None


def test_skill_path_skips_illegal_choices() -> None:
    counts = {1: {1: 10}, 2: {1: 9, 3: 5}, 3: {1: 8, 2: 3}}
    # Level 2: a second Q point is illegal (1 point max by level 2), so E.
    assert skill_path(counts) == [1, 3, 1]


def test_skill_path_length_is_highest_level_with_data() -> None:
    counts = {1: {1: 5}, 4: {2: 3}}
    path = skill_path(counts, (1, 3, 2))
    assert len(path) == 4
    assert_legal(path)
    # Levels without data fall back to the max order: Q, E, then W.
    assert path == [1, 3, 1, 2]


def test_skill_path_empty_without_data() -> None:
    assert skill_path({}) == []
    assert skill_path({3: {1: 0}}) == []


def test_skill_path_repairs_to_a_full_legal_path() -> None:
    # The data never takes R and always prefers Q > W > E: taking a basic at 6, 11 and 16
    # would leave no legal choice at level 18, so the search puts R there.
    counts = {level: {1: 10, 2: 9, 3: 8} for level in range(1, 19)}
    path = skill_path(counts)
    assert len(path) == 18
    assert_legal(path)
    assert [i + 1 for i, s in enumerate(path) if s == 4] == [6, 11, 16]
    assert path[:5] == [1, 2, 1, 2, 1]


def test_skill_path_follows_a_normal_path() -> None:
    usual = [1, 3, 2, 1, 1, 4, 1, 3, 1, 3, 4, 3, 3, 2, 2, 4, 2, 2]
    counts = {level: {slot: 50, (slot % 3) + 1: 10} for level, slot in enumerate(usual, 1)}
    assert skill_path(counts) == usual


def test_skill_path_never_more_than_eighteen() -> None:
    counts = {level: {1: 1} for level in range(1, 25)}
    path = skill_path(counts)
    assert len(path) == 18
    assert_legal(path)


async def test_ttl_cache_expires_and_caps() -> None:
    now = [0.0]
    cache = TTLCache(ttl_seconds=10, max_entries=2, clock=lambda: now[0])
    engine = object.__new__(type("E", (), {}))
    calls: list[str] = []

    def loader(value: str):
        async def load() -> str:
            calls.append(value)
            return value

        return load

    assert await cache.get_or_load(engine, "a", loader("a1")) == "a1"
    assert await cache.get_or_load(engine, "a", loader("a2")) == "a1"
    now[0] = 11
    assert await cache.get_or_load(engine, "a", loader("a3")) == "a3"
    await cache.get_or_load(engine, "b", loader("b"))
    await cache.get_or_load(engine, "c", loader("c"))
    assert len(cache) == 2
    # Another engine starts from an empty cache.
    other = object.__new__(type("E2", (), {}))
    assert await cache.get_or_load(other, "c", loader("c2")) == "c2"
    assert calls == ["a1", "a3", "b", "c", "c2"]


async def test_ttl_cache_does_not_cache_errors() -> None:
    cache = TTLCache()
    engine = object.__new__(type("E", (), {}))

    async def boom() -> str:
        raise LookupError

    with pytest.raises(LookupError):
        await cache.get_or_load(engine, "k", boom)
    assert len(cache) == 0
