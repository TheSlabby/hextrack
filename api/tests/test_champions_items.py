"""Item classification (stats/champions/items.py) on a trimmed real item.json, and
DDragon.item_catalog (patch -> version, caching, offline fallback) over MockTransport."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hextrack.riot.ddragon import (
    VERSIONS_URL,
    DDragon,
    item_data_url,
    pick_versions,
    resolve_patch_version,
)
from hextrack.stats.champions.items import ItemCatalog
from tests.conftest import FIXTURES_DIR


def item_json() -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / "item_sample.json").read_text())


@pytest.fixture(scope="module")
def catalog() -> ItemCatalog:
    return ItemCatalog.from_item_json(item_json())


def test_version_comes_from_the_payload(catalog: ItemCatalog) -> None:
    assert catalog.version == item_json()["version"]
    assert ItemCatalog.from_item_json(item_json(), "16.18.1").version == "16.18.1"


@pytest.mark.parametrize(
    ("transform", "base"),
    [
        (3042, 3004),  # Muramana -> Manamune
        (3040, 3003),  # Seraph's Embrace -> Archangel's Staff
        (3121, 3119),  # Fimbulwinter -> Winter's Approach
        (2530, 2526),  # Diadem of Songs -> Whispering Circlet
    ],
)
def test_transforms_fold_into_their_base_item(catalog, transform, base) -> None:
    assert catalog.canonical(transform) == base
    assert catalog.is_completed(transform)
    assert catalog.is_legendary(transform)
    assert catalog.canonical(base) == base


@pytest.mark.parametrize(
    ("boots", "tier2"),
    [
        (3006, 3006),
        (3172, 3006),  # Gunmetal Greaves has no "Boots" tag but is built from Berserker's
        (3174, 3047),  # Armored Advance -> Plated Steelcaps
        (3170, 3009),
        (3013, 3010),  # Synchronized Souls -> Symbiotic Soles
        (3176, 3010),  # Forever Forward -> Synchronized Souls -> Symbiotic Soles
        (3117, 3117),  # Mobility Boots
    ],
)
def test_boots_upgrades_fold_to_tier_two(catalog, boots, tier2) -> None:
    assert catalog.canonical(boots) == tier2
    assert catalog.is_boots(boots)
    assert catalog.is_completed(boots)
    assert not catalog.is_legendary(boots)


def test_plain_boots_are_boots_but_not_completed(catalog) -> None:
    assert catalog.is_boots(1001)
    assert not catalog.is_completed(1001)


@pytest.mark.parametrize("item", [3865, 3866, 3867, 3869, 3870, 3877])
def test_support_quest_items_fold_to_the_starter(catalog, item) -> None:
    assert catalog.canonical(item) == 3865
    assert not catalog.is_completed(item)


@pytest.mark.parametrize(
    "item",
    [
        1101,  # jungle pet
        1055,  # Doran's Blade
        2003,  # Health Potion
        2033,  # Corrupting Potion (consumable built from Refillable)
        1037,  # Pickaxe (component)
        3067,  # Kindlegem (component)
        2021,  # Tunneler (component)
        2420,  # Seeker's Armguard (into Zhonya's)
        2421,  # Shattered Armguard (cheap end of tree)
        1082,  # Dark Seal
        3340,  # trinket
        999_999,  # unknown id
    ],
)
def test_not_completed(catalog, item) -> None:
    assert not catalog.is_completed(item)
    assert not catalog.is_legendary(item)


@pytest.mark.parametrize(
    "item", [6672, 3071, 6333, 3078, 3031, 3089, 4645, 3152, 6692, 3190, 2065, 3157, 6693, 3041]
)
def test_finished_legendaries(catalog, item) -> None:
    assert catalog.is_completed(item)
    assert catalog.is_legendary(item)
    assert not catalog.is_boots(item)


def test_trinkets(catalog) -> None:
    assert catalog.is_trinket(3340)
    assert catalog.is_trinket(3364)
    assert not catalog.is_trinket(1055)


def test_bad_payload_is_rejected() -> None:
    with pytest.raises(ValueError):
        ItemCatalog.from_item_json({"data": {}})
    with pytest.raises(ValueError):
        ItemCatalog.from_item_json([])


# --- DDragon.item_catalog -------------------------------------------------------------------

VERSIONS = ["16.19.1", "16.18.2", "16.18.1", "16.17.1", "lolpatch_3.7"]


def test_pick_versions_sorts_release_versions() -> None:
    assert pick_versions(["16.9.1", "16.10.1", "lolpatch_3.7"]) == ["16.10.1", "16.9.1"]


@pytest.mark.parametrize(
    ("patch", "version"),
    [
        ("16.18", "16.18.2"),
        ("16.17", "16.17.1"),
        ("16.25", "16.19.1"),  # newer than Data Dragon: newest before it
        ("16.10", "16.17.1"),  # older than every known version: the oldest one
        ("15.24", "16.17.1"),
        ("bogus", None),
    ],
)
def test_resolve_patch_version(patch, version) -> None:
    assert resolve_patch_version(patch, pick_versions(VERSIONS)) == version


def test_resolve_prefers_the_newest_older_patch() -> None:
    assert resolve_patch_version("16.18", ["16.19.1", "16.16.1", "16.10.1"]) == "16.16.1"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_item_catalog_resolves_caches_and_falls_back() -> None:
    requests: list[str] = []
    online = {"on": True}
    payload = item_json()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requests.append(url)
        if not online["on"]:
            raise httpx.ConnectError("offline", request=request)
        if url == VERSIONS_URL:
            return httpx.Response(200, json=VERSIONS)
        if url in (item_data_url("16.18.2"), item_data_url("16.17.1")):
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    clock = Clock()
    dd = DDragon(transport=httpx.MockTransport(handler), clock=clock)
    try:
        first = await dd.item_catalog("16.18")
        assert first is not None and first.version == "16.18.2"
        again = await dd.item_catalog("16.18")
        assert again is first
        assert requests.count(item_data_url("16.18.2")) == 1

        # 16.19.1 has no item.json here (404): the nearest cached catalog stands in.
        stand_in = await dd.item_catalog("16.19")
        assert stand_in is first
        online["on"] = False
        assert await dd.item_catalog("16.18") is first
    finally:
        await dd.aclose()


async def test_item_catalog_offline_with_nothing_cached_is_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    dd = DDragon(transport=httpx.MockTransport(handler), clock=Clock())
    try:
        assert await dd.item_catalog("16.18") is None
    finally:
        await dd.aclose()
