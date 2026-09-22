"""DDragon caching and offline fallback against httpx.MockTransport (no network)."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from hextrack.riot.ddragon import (
    CDN,
    FAILURE_RETRY_SECONDS,
    FALLBACK_VERSION,
    VERSION_TTL_SECONDS,
    VERSIONS_URL,
    DDragon,
    champion_data_url,
    champion_icon_url,
    champion_splash_url,
    item_icon_url,
    parse_champion_map,
    pick_latest_version,
    profile_icon_url,
)

VERSIONS = ["16.19.1", "16.18.1", "16.17.1", "lolpatch_3.7", "0.151.101"]


def champions_payload(version: str, champions: dict[str, int]) -> dict[str, Any]:
    return {
        "type": "champion",
        "format": "standAloneComplex",
        "version": version,
        "data": {
            name: {"version": version, "id": name, "key": str(key), "name": name}
            for name, key in champions.items()
        },
    }


class Clock:
    def __init__(self) -> None:
        self.now = 10_000.0

    def __call__(self) -> float:
        return self.now


Reply = Callable[[httpx.Request], httpx.Response]


def offline(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("offline", request=request)


class CDNFake:
    """Serves versions.json and champion.json; each URL has a queue of replies."""

    def __init__(self) -> None:
        self.routes: dict[str, deque[Reply]] = {}
        self.requests: list[str] = []

    def on(self, url: str, *replies: Reply) -> None:
        self.routes[url] = deque(replies)

    def json(self, payload: Any, status: int = 200) -> Reply:
        return lambda request: httpx.Response(status, json=payload)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        queue = self.routes.get(url)
        if not queue:
            return httpx.Response(404, text="not found")
        reply = queue.popleft() if len(queue) > 1 else queue[0]
        return reply(request)

    def count(self, url: str) -> int:
        return self.requests.count(url)


@pytest.fixture
def cdn() -> CDNFake:
    return CDNFake()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def ddragon(cdn: CDNFake, clock: Clock) -> AsyncIterator[DDragon]:
    dd = DDragon(transport=httpx.MockTransport(cdn), clock=clock)
    try:
        yield dd
    finally:
        await dd.aclose()


# --- pure helpers --------------------------------------------------------------------------


def test_url_helpers() -> None:
    assert champion_icon_url("16.18.1", "MonkeyKing") == (
        f"{CDN}/16.18.1/img/champion/MonkeyKing.png"
    )
    assert champion_splash_url("Ahri", 3) == f"{CDN}/img/champion/splash/Ahri_3.jpg"
    assert profile_icon_url("16.18.1", 29) == f"{CDN}/16.18.1/img/profileicon/29.png"
    assert item_icon_url("16.18.1", 3340) == f"{CDN}/16.18.1/img/item/3340.png"
    assert champion_data_url("16.18.1") == f"{CDN}/16.18.1/data/en_US/champion.json"
    assert DDragon.champion_icon_url("1.2.3", "Ahri") == champion_icon_url("1.2.3", "Ahri")
    assert DDragon.CDN == CDN


def test_pick_latest_version_skips_legacy_entries() -> None:
    assert pick_latest_version(VERSIONS) == "16.19.1"
    assert pick_latest_version(["lolpatch_7.20", "7.20.1"]) == "7.20.1"
    for bad in ([], ["lolpatch_3.7"], {"v": "1.2.3"}, [1, 2], None):
        with pytest.raises(ValueError):
            pick_latest_version(bad)


def test_parse_champion_map() -> None:
    payload = champions_payload("16.18.1", {"Aatrox": 266, "MonkeyKing": 62})
    assert parse_champion_map(payload) == {266: "Aatrox", 62: "MonkeyKing"}
    bad: Any
    for bad in (
        {},
        {"data": {}},
        {"data": []},
        {"data": {"Aatrox": {"id": "Aatrox"}}},
        {"data": {"Aatrox": {"id": "Aatrox", "key": "abc"}}},
        {"data": {"Aatrox": "nope"}},
        [],
    ):
        with pytest.raises(ValueError):
            parse_champion_map(bad)


# --- latest_version ------------------------------------------------------------------------


async def test_latest_version_is_fetched_lazily_and_cached(
    ddragon: DDragon, cdn: CDNFake, clock: Clock
) -> None:
    cdn.on(VERSIONS_URL, cdn.json(VERSIONS), cdn.json(["16.20.1", *VERSIONS]))
    assert cdn.requests == []  # nothing fetched at construction
    assert ddragon.current_version == FALLBACK_VERSION

    assert await ddragon.latest_version() == "16.19.1"
    assert await ddragon.latest_version() == "16.19.1"
    clock.now += VERSION_TTL_SECONDS - 1
    assert await ddragon.latest_version() == "16.19.1"
    assert cdn.count(VERSIONS_URL) == 1

    clock.now += 2  # TTL (6 h) expired
    assert await ddragon.latest_version() == "16.20.1"
    assert cdn.count(VERSIONS_URL) == 2
    assert ddragon.current_version == "16.20.1"


async def test_concurrent_callers_share_one_fetch(ddragon: DDragon, cdn: CDNFake) -> None:
    cdn.on(VERSIONS_URL, cdn.json(VERSIONS))
    versions = await asyncio.gather(*(ddragon.latest_version() for _ in range(10)))
    assert set(versions) == {"16.19.1"}
    assert cdn.count(VERSIONS_URL) == 1


async def test_offline_without_cache_uses_fallback_version(
    ddragon: DDragon, cdn: CDNFake, clock: Clock
) -> None:
    cdn.on(VERSIONS_URL, offline, cdn.json(VERSIONS))
    assert await ddragon.latest_version() == FALLBACK_VERSION
    # No retry storm: within the failure backoff the network is not touched again.
    clock.now += FAILURE_RETRY_SECONDS - 1
    assert await ddragon.latest_version() == FALLBACK_VERSION
    assert cdn.count(VERSIONS_URL) == 1
    # After the backoff it recovers.
    clock.now += 2
    assert await ddragon.latest_version() == "16.19.1"
    assert cdn.count(VERSIONS_URL) == 2


@pytest.mark.parametrize(
    "failure",
    [
        offline,
        lambda request: httpx.Response(503, text="unavailable"),
        lambda request: httpx.Response(200, content=b"<html>"),
        lambda request: httpx.Response(200, json={"not": "a list"}),
        # An exception returned here is raised by the wrapper below.
        lambda request: httpx.ReadTimeout("slow", request=request),
    ],
    ids=["offline", "503", "not-json", "wrong-shape", "timeout"],
)
async def test_failed_refresh_keeps_last_known_version(
    ddragon: DDragon, cdn: CDNFake, clock: Clock, failure: Reply
) -> None:
    def raising(request: httpx.Request) -> httpx.Response:
        result: Any = failure(request)
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, httpx.Response)
        return result

    cdn.on(VERSIONS_URL, cdn.json(VERSIONS), raising)
    assert await ddragon.latest_version() == "16.19.1"
    clock.now += VERSION_TTL_SECONDS + 1
    assert await ddragon.latest_version() == "16.19.1"
    assert cdn.count(VERSIONS_URL) == 2


# --- champion_map --------------------------------------------------------------------------


async def test_champion_map_is_cached_per_version(
    ddragon: DDragon, cdn: CDNFake, clock: Clock
) -> None:
    cdn.on(VERSIONS_URL, cdn.json(VERSIONS), cdn.json(["16.20.1", *VERSIONS]))
    old_url = champion_data_url("16.19.1")
    new_url = champion_data_url("16.20.1")
    cdn.on(old_url, cdn.json(champions_payload("16.19.1", {"Aatrox": 266, "MonkeyKing": 62})))
    cdn.on(new_url, cdn.json(champions_payload("16.20.1", {"Aatrox": 266, "Zaahen": 904})))

    first = await ddragon.champion_map()
    assert first == {266: "Aatrox", 62: "MonkeyKing"}
    first[1] = "Mutated"  # callers get a copy
    assert await ddragon.champion_map() == {266: "Aatrox", 62: "MonkeyKing"}
    assert await ddragon.champion_key(62) == "MonkeyKing"
    assert await ddragon.champion_key(99999) is None
    assert cdn.count(old_url) == 1

    clock.now += VERSION_TTL_SECONDS + 1  # a new patch appears
    assert await ddragon.champion_map() == {266: "Aatrox", 904: "Zaahen"}
    assert await ddragon.champion_map() == {266: "Aatrox", 904: "Zaahen"}
    assert cdn.count(new_url) == 1
    assert cdn.count(old_url) == 1


async def test_champion_map_offline_falls_back_to_newest_cached_map(
    ddragon: DDragon, cdn: CDNFake, clock: Clock
) -> None:
    cdn.on(VERSIONS_URL, cdn.json(VERSIONS), cdn.json(["16.20.1", *VERSIONS]))
    cdn.on(champion_data_url("16.19.1"), cdn.json(champions_payload("16.19.1", {"Ahri": 103})))
    cdn.on(champion_data_url("16.20.1"), offline)

    assert await ddragon.champion_map() == {103: "Ahri"}
    clock.now += VERSION_TTL_SECONDS + 1
    assert await ddragon.champion_map() == {103: "Ahri"}
    assert await ddragon.champion_map() == {103: "Ahri"}
    # The failed version is not retried inside the backoff window.
    assert cdn.count(champion_data_url("16.20.1")) == 1


async def test_champion_map_fully_offline_is_empty_and_recovers(
    ddragon: DDragon, cdn: CDNFake, clock: Clock
) -> None:
    fallback_url = champion_data_url(FALLBACK_VERSION)
    cdn.on(VERSIONS_URL, offline)
    cdn.on(
        fallback_url,
        offline,
        cdn.json(champions_payload(FALLBACK_VERSION, {"Jinx": 222})),
    )
    assert await ddragon.champion_map() == {}
    assert await ddragon.champion_map() == {}
    assert cdn.count(fallback_url) == 1
    clock.now += FAILURE_RETRY_SECONDS + 1
    assert await ddragon.champion_map() == {222: "Jinx"}


# --- lifecycle -----------------------------------------------------------------------------


async def test_owned_client_is_closed_and_recreated(cdn: CDNFake, clock: Clock) -> None:
    cdn.on(VERSIONS_URL, cdn.json(VERSIONS))
    dd = DDragon(transport=httpx.MockTransport(cdn), clock=clock, version_ttl_seconds=0)
    assert await dd.latest_version() == "16.19.1"
    await dd.aclose()
    await dd.aclose()
    # A closed instance lazily opens a fresh client on next use.
    assert await dd.latest_version() == "16.19.1"
    await dd.aclose()


async def test_shared_client_is_not_closed(cdn: CDNFake, clock: Clock) -> None:
    cdn.on(VERSIONS_URL, cdn.json(VERSIONS))
    async with httpx.AsyncClient(transport=httpx.MockTransport(cdn)) as http:
        dd = DDragon(http, clock=clock)
        assert await dd.latest_version() == "16.19.1"
        await dd.aclose()
        assert not http.is_closed
        assert (await http.get(VERSIONS_URL)).status_code == 200
