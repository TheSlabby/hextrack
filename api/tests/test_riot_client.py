"""RiotClient against httpx.MockTransport / respx. Never touches the network."""

from __future__ import annotations

import asyncio
import copy
import logging
import random
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from hextrack.config import Settings
from hextrack.riot.client import MAX_ATTEMPTS, MAX_RATE_LIMIT_RETRIES, RiotClient
from hextrack.riot.errors import (
    RiotBadResponse,
    RiotError,
    RiotForbidden,
    RiotKeyMissing,
    RiotNotFound,
    RiotRateLimited,
    RiotUnavailable,
)
from hextrack.riot.schemas import AccountDto, LeagueEntryDto, SummonerDto

API_KEY = "RGAPI-00000000-test-key"
AMERICAS = "americas.api.riotgames.com"
NA1 = "na1.api.riotgames.com"

ACCOUNT = {"puuid": "puuid-1", "gameName": "Hex Walker", "tagLine": "NA1"}
SUMMONER = {"puuid": "puuid-1", "profileIconId": 4568, "summonerLevel": 312, "revisionDate": 1}
LEAGUE_ENTRY = {
    "leagueId": "abc",
    "queueType": "RANKED_SOLO_5x5",
    "tier": "GOLD",
    "rank": "II",
    "puuid": "puuid-1",
    "leaguePoints": 45,
    "wins": 30,
    "losses": 25,
    "veteran": False,
    "inactive": False,
    "freshBlood": True,
    "hotStreak": False,
}


class FakeClock:
    """Monotonic fake time; ``sleep`` advances it instantly and yields to the loop."""

    def __init__(self, start: float = 5_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(seconds, 0.0)
        await asyncio.sleep(0)


Reply = Callable[[httpx.Request], httpx.Response]


def reply(
    status: int = 200,
    json: Any = None,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
) -> Reply:
    def make(request: httpx.Request) -> httpx.Response:
        if content is not None:
            return httpx.Response(status, content=content, headers=headers)
        return httpx.Response(status, json={} if json is None else json, headers=headers)

    return make


def connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def riot_error(status: int, message: str) -> Reply:
    return reply(status, {"status": {"message": message, "status_code": status}})


class Script:
    """MockTransport handler: replays ``replies`` in order, repeating the last one."""

    def __init__(self, *replies: Reply, clock: FakeClock | None = None) -> None:
        self._replies: deque[Reply] = deque(replies or (reply(),))
        self.requests: list[httpx.Request] = []
        self.times: list[float] = []
        self._clock = clock

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._clock is not None:
            self.times.append(self._clock())
        item = self._replies.popleft() if len(self._replies) > 1 else self._replies[0]
        return item(request)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "riot_api_key": API_KEY,
        "riot_platform": "na1",
        "riot_region": "americas",
        "riot_app_rate_limits": "1000:1",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def make_client(
    script: Script, clock: FakeClock | None = None, **settings_overrides: Any
) -> tuple[RiotClient, FakeClock]:
    clock = clock or FakeClock()
    client = RiotClient(
        make_settings(**settings_overrides),
        httpx.MockTransport(script),
        clock=clock,
        sleep=clock.sleep,
        rng=random.Random(7),
        rate_limit_margin=0.0,
    )
    return client, clock


# --- request shape -------------------------------------------------------------------------


async def test_uses_riot_token_header_never_query_string() -> None:
    script = Script(reply(json=ACCOUNT))
    client, _ = make_client(script)
    async with client:
        await client.account_by_puuid("puuid-1")
    request = script.requests[0]
    assert request.headers["X-Riot-Token"] == API_KEY
    assert request.headers["User-Agent"].startswith("HexTrack/")
    assert "api_key" not in str(request.url)
    assert API_KEY not in str(request.url)
    assert request.method == "GET"


@pytest.mark.parametrize(
    ("call", "host", "path"),
    [
        (
            lambda c: c.account_by_riot_id("Hex", "NA1"),
            AMERICAS,
            "/riot/account/v1/accounts/by-riot-id/Hex/NA1",
        ),
        (lambda c: c.account_by_puuid("p1"), AMERICAS, "/riot/account/v1/accounts/by-puuid/p1"),
        (lambda c: c.summoner_by_puuid("p1"), NA1, "/lol/summoner/v4/summoners/by-puuid/p1"),
        (lambda c: c.league_entries_by_puuid("p1"), NA1, "/lol/league/v4/entries/by-puuid/p1"),
        (lambda c: c.match_ids_by_puuid("p1"), AMERICAS, "/lol/match/v5/matches/by-puuid/p1/ids"),
        (lambda c: c.match("NA1_1"), AMERICAS, "/lol/match/v5/matches/NA1_1"),
    ],
    ids=["account_by_riot_id", "account_by_puuid", "summoner", "league", "match_ids", "match"],
)
async def test_regional_and_platform_hosts(
    call: Callable[[RiotClient], Any], host: str, path: str
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        url = request.url.path
        if url.startswith("/riot/account"):
            return httpx.Response(200, json=ACCOUNT)
        if url.startswith("/lol/summoner"):
            return httpx.Response(200, json=SUMMONER)
        if url.startswith("/lol/league"):
            return httpx.Response(200, json=[])
        if url.endswith("/ids"):
            return httpx.Response(200, json=["NA1_1"])
        return httpx.Response(200, json=_minimal_match("NA1_1"))

    script = Script(respond)
    client, _ = make_client(script)
    async with client:
        await call(client)
    (request,) = script.requests
    assert request.url.scheme == "https"
    assert request.url.host == host
    assert request.url.path == path


async def test_hosts_follow_settings() -> None:
    script = Script(reply(json=SUMMONER), reply(json=ACCOUNT))
    client, _ = make_client(script, riot_platform="euw1", riot_region="europe")
    async with client:
        await client.summoner_by_puuid("p1")
        await client.account_by_puuid("p1")
    assert [r.url.host for r in script.requests] == [
        "euw1.api.riotgames.com",
        "europe.api.riotgames.com",
    ]


@pytest.mark.parametrize(
    ("game_name", "tag_line", "raw_path"),
    [
        ("Hex Walker", "NA1", "/riot/account/v1/accounts/by-riot-id/Hex%20Walker/NA1"),
        ("Ñandú", "LAS", "/riot/account/v1/accounts/by-riot-id/%C3%91and%C3%BA/LAS"),
        ("페이커", "KR1", "/riot/account/v1/accounts/by-riot-id/%ED%8E%98%EC%9D%B4%EC%BB%A4/KR1"),
        ("a/b#c?d%", "x y", "/riot/account/v1/accounts/by-riot-id/a%2Fb%23c%3Fd%25/x%20y"),
    ],
)
async def test_path_segments_are_quoted(game_name: str, tag_line: str, raw_path: str) -> None:
    script = Script(reply(json={**ACCOUNT, "gameName": game_name, "tagLine": tag_line}))
    client, _ = make_client(script)
    async with client:
        account = await client.account_by_riot_id(game_name, tag_line)
    assert script.requests[0].url.raw_path == raw_path.encode("ascii")
    assert account.game_name == game_name


async def test_empty_path_segment_is_rejected_before_any_request() -> None:
    script = Script()
    client, _ = make_client(script)
    async with client:
        with pytest.raises(ValueError):
            await client.account_by_riot_id("", "NA1")
        with pytest.raises(ValueError):
            await client.match("")
    assert script.requests == []


async def test_match_ids_query_parameters() -> None:
    script = Script(reply(json=["NA1_3", "NA1_2"]))
    client, _ = make_client(script)
    season = datetime(2026, 1, 8, 20, 0, tzinfo=UTC)
    async with client:
        ids = await client.match_ids_by_puuid(
            "p1", start=5, count=250, queue=420, type_="ranked", start_time=season
        )
        await client.match_ids_by_puuid("p1", count=0, start=-3, type_=None)
        # Naive datetimes are UTC.
        await client.match_ids_by_puuid(
            "p1", start_time=datetime(2026, 1, 8, 20, 0), end_time=datetime(2026, 1, 9)
        )
    assert ids == ["NA1_3", "NA1_2"]
    first, second, third = (dict(r.url.params) for r in script.requests)
    assert first == {
        "start": "5",
        "count": "100",
        "queue": "420",
        "type": "ranked",
        "startTime": "1767902400",
    }
    assert second == {"start": "0", "count": "1"}
    assert third == {
        "start": "0",
        "count": "20",
        "type": "ranked",
        "startTime": "1767902400",
        "endTime": "1767916800",
    }


async def test_match_ids_rejects_unknown_type() -> None:
    script = Script()
    client, _ = make_client(script)
    async with client:
        with pytest.raises(ValueError):
            await client.match_ids_by_puuid("p1", type_="ranked_solo")
    assert script.requests == []


# --- payload validation --------------------------------------------------------------------


async def test_typed_endpoints_parse_dtos() -> None:
    script = Script(
        reply(json=ACCOUNT),
        reply(json=SUMMONER),
        reply(json=[LEAGUE_ENTRY]),
        reply(json=[]),
    )
    client, _ = make_client(script)
    async with client:
        account = await client.account_by_riot_id("Hex Walker", "NA1")
        summoner = await client.summoner_by_puuid("puuid-1")
        entries = await client.league_entries_by_puuid("puuid-1")
        unranked = await client.league_entries_by_puuid("puuid-2")
    assert isinstance(account, AccountDto)
    assert (account.puuid, account.game_name, account.tag_line) == ("puuid-1", "Hex Walker", "NA1")
    assert isinstance(summoner, SummonerDto)
    assert (summoner.profile_icon_id, summoner.summoner_level) == (4568, 312)
    assert len(entries) == 1 and isinstance(entries[0], LeagueEntryDto)
    assert (entries[0].tier, entries[0].rank, entries[0].league_points) == ("GOLD", "II", 45)
    assert entries[0].fresh_blood is True
    assert unranked == []


async def test_match_returns_the_raw_dict_after_validation(
    match_sample: dict[str, Any],
) -> None:
    pristine = copy.deepcopy(match_sample)
    script = Script(reply(json=match_sample))
    client, _ = make_client(script)
    async with client:
        raw = await client.match(match_sample["metadata"]["matchId"])
    assert raw == pristine
    assert client.status.key_ok is True


@pytest.mark.parametrize(
    "body",
    [
        {"status": {"message": "Data not found", "status_code": 404}},
        {"metadata": {"matchId": "NA1_1"}, "info": {"gameMode": "CLASSIC"}},
        ["NA1_1"],
        "a string",
    ],
    ids=["error-body", "missing-fields", "list", "string"],
)
async def test_match_rejects_invalid_2xx_bodies(body: Any) -> None:
    script = Script(reply(json=body))
    client, _ = make_client(script)
    async with client:
        with pytest.raises(RiotBadResponse):
            await client.match("NA1_1")
    assert client.status.last_error is not None
    assert client.status.last_error_at is not None


async def test_match_rejects_a_different_match_id() -> None:
    script = Script(reply(json=_minimal_match("NA1_999")))
    client, _ = make_client(script)
    async with client:
        with pytest.raises(RiotBadResponse, match="NA1_999"):
            await client.match("NA1_1")


async def test_non_json_2xx_is_a_bad_response() -> None:
    script = Script(reply(content=b"<html>oops</html>", headers={"Content-Type": "text/html"}))
    client, _ = make_client(script)
    async with client:
        with pytest.raises(RiotBadResponse):
            await client.summoner_by_puuid("p1")


@pytest.mark.parametrize(
    ("call", "body"),
    [
        (lambda c: c.account_by_puuid("p1"), {"gameName": "x"}),
        (lambda c: c.summoner_by_puuid("p1"), {"puuid": "p1"}),
        (lambda c: c.league_entries_by_puuid("p1"), {"queueType": "RANKED_SOLO_5x5"}),
        (lambda c: c.league_entries_by_puuid("p1"), [{"tier": "GOLD"}]),
        (lambda c: c.match_ids_by_puuid("p1"), {"ids": []}),
        (lambda c: c.match_ids_by_puuid("p1"), [1, 2]),
    ],
)
async def test_typed_endpoints_reject_invalid_bodies(
    call: Callable[[RiotClient], Any], body: Any
) -> None:
    script = Script(reply(json=body))
    client, _ = make_client(script)
    async with client:
        with pytest.raises(RiotBadResponse):
            await call(client)


# --- status codes --------------------------------------------------------------------------


async def test_missing_key_raises_before_any_network_call() -> None:
    script = Script()
    client, _ = make_client(script, riot_api_key=None)
    assert client.status.key_configured is False
    async with client:
        for call in (
            client.account_by_riot_id("Hex", "NA1"),
            client.account_by_puuid("p1"),
            client.summoner_by_puuid("p1"),
            client.league_entries_by_puuid("p1"),
            client.match_ids_by_puuid("p1"),
            client.match("NA1_1"),
        ):
            with pytest.raises(RiotKeyMissing):
                await call
    assert script.requests == []
    assert client.status.key_ok is None
    assert client.limiter_wait_estimate() == 0.0


@pytest.mark.parametrize("status", [401, 403])
async def test_forbidden_flips_key_status(status: int) -> None:
    script = Script(reply(json=SUMMONER), riot_error(status, "Forbidden"))
    client, _ = make_client(script)
    async with client:
        await client.summoner_by_puuid("p1")
        assert client.status.key_ok is True
        assert client.status.last_error is None
        with pytest.raises(RiotForbidden) as info:
            await client.summoner_by_puuid("p1")
    assert info.value.status == status
    assert len(script.requests) == 2  # never retried
    assert client.status.key_ok is False
    assert client.status.last_error is not None and str(status) in client.status.last_error
    assert client.status.last_error_at is not None


async def test_success_after_forbidden_restores_key_ok() -> None:
    script = Script(riot_error(403, "Forbidden"), reply(json=SUMMONER))
    client, _ = make_client(script)
    async with client:
        with pytest.raises(RiotForbidden):
            await client.summoner_by_puuid("p1")
        assert client.status.key_ok is False
        await client.summoner_by_puuid("p1")
    assert client.status.key_ok is True


async def test_not_found_maps_to_riot_not_found() -> None:
    script = Script(riot_error(404, "Data not found - No results found for player"))
    client, _ = make_client(script)
    async with client:
        with pytest.raises(RiotNotFound) as info:
            await client.account_by_riot_id("Nobody", "NA1")
    assert info.value.status == 404
    assert "No results found" in str(info.value)
    assert len(script.requests) == 1
    assert client.status.key_ok is True  # an authenticated answer
    assert client.status.last_error is None


async def test_other_client_errors_raise_plain_riot_error() -> None:
    script = Script(riot_error(400, "Bad request - Exception decrypting puuid"))
    client, _ = make_client(script)
    async with client:
        with pytest.raises(RiotError) as info:
            await client.summoner_by_puuid("garbage")
    assert type(info.value) is RiotError
    assert info.value.status == 400
    assert len(script.requests) == 1


# --- 429 -----------------------------------------------------------------------------------


async def test_429_honours_retry_after_then_succeeds(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock()
    script = Script(
        reply(429, headers={"Retry-After": "3", "X-Rate-Limit-Type": "application"}),
        reply(json=ACCOUNT),
        clock=clock,
    )
    client, _ = make_client(script, clock)
    with caplog.at_level(logging.WARNING, logger="hextrack.riot.client"):
        async with client:
            account = await client.account_by_puuid("puuid-1")
    assert account.puuid == "puuid-1"
    assert len(script.requests) == 2
    gap = script.times[1] - script.times[0]
    assert 3.0 < gap <= 3.5  # Retry-After plus jitter
    assert "application" in caplog.text


async def test_application_429_blocks_every_method_on_that_routing_value() -> None:
    clock = FakeClock()
    release = asyncio.Event()
    parked: list[float] = []

    async def parked_sleep(seconds: float) -> None:
        parked.append(seconds)
        await release.wait()
        clock.now += seconds

    script = Script(
        reply(429, headers={"Retry-After": "2", "X-Rate-Limit-Type": "application"}),
        reply(json=ACCOUNT),
        clock=clock,
    )
    client = RiotClient(
        make_settings(),
        httpx.MockTransport(script),
        clock=clock,
        sleep=parked_sleep,
        rng=random.Random(7),
        rate_limit_margin=0.0,
    )
    async with client:
        first = asyncio.create_task(client.account_by_puuid("p1"))
        for _ in range(100):
            if parked:
                break
            await asyncio.sleep(0)
        assert parked and parked[0] > 2.0
        # The regional limiter is blocked, so any other regional method must wait too...
        assert client.limiter_wait_estimate("match") > 2.0
        assert client.limiter_wait_estimate("account_by_riot_id") > 2.0
        # ...while the platform routing value is unaffected.
        assert client.limiter_wait_estimate("summoner_by_puuid") == 0.0
        release.set()
        account = await first
    assert account.puuid == "puuid-1"
    assert len(script.requests) == 2


async def test_429_gives_up_after_two_retries() -> None:
    clock = FakeClock()
    script = Script(
        reply(429, headers={"Retry-After": "1", "X-Rate-Limit-Type": "method"}), clock=clock
    )
    client, _ = make_client(script, clock)
    async with client:
        with pytest.raises(RiotRateLimited) as info:
            await client.match("NA1_1")
    assert len(script.requests) == 1 + MAX_RATE_LIMIT_RETRIES
    assert info.value.retry_after >= 1.0
    assert info.value.status == 429
    assert client.status.last_error is not None
    # The method stays blocked for the caller that comes next.
    assert client.limiter_wait_estimate("match") > 0.0


async def test_429_without_retry_after_backs_off() -> None:
    clock = FakeClock()
    script = Script(reply(429), reply(429), reply(json=SUMMONER), clock=clock)
    client, _ = make_client(script, clock)
    async with client:
        await client.summoner_by_puuid("p1")
    gaps = [b - a for a, b in zip(script.times, script.times[1:], strict=False)]
    assert 1.0 < gaps[0] <= 1.5
    assert 2.0 < gaps[1] <= 2.5


async def test_429_with_huge_retry_after_raises_immediately() -> None:
    clock = FakeClock()
    script = Script(reply(429, headers={"Retry-After": "3600"}), clock=clock)
    client, _ = make_client(script, clock)
    async with client:
        with pytest.raises(RiotRateLimited) as info:
            await client.match("NA1_1")
    assert len(script.requests) == 1
    assert info.value.retry_after >= 3600
    assert clock.sleeps == []
    assert client.limiter_wait_estimate("match") >= 3600


# --- 5xx and network errors ----------------------------------------------------------------


async def test_5xx_is_retried_with_backoff() -> None:
    clock = FakeClock()
    script = Script(
        riot_error(503, "Service unavailable"),
        riot_error(500, "Internal server error"),
        reply(json=SUMMONER),
        clock=clock,
    )
    client, _ = make_client(script, clock)
    async with client:
        summoner = await client.summoner_by_puuid("p1")
    assert summoner.summoner_level == 312
    assert len(script.requests) == 3
    first_gap, second_gap = (b - a for a, b in zip(script.times, script.times[1:], strict=False))
    assert 0.5 <= first_gap <= 0.75
    assert 1.0 <= second_gap <= 1.25


async def test_5xx_exhausted_raises_unavailable() -> None:
    script = Script(riot_error(503, "Service unavailable"))
    client, _ = make_client(script)
    async with client:
        with pytest.raises(RiotUnavailable) as info:
            await client.match("NA1_1")
    assert len(script.requests) == MAX_ATTEMPTS
    assert info.value.status == 503
    assert client.status.last_error is not None and "503" in client.status.last_error
    assert client.status.key_ok is None


async def test_network_errors_are_retried() -> None:
    script = Script(connect_error, reply(json=ACCOUNT))
    client, _ = make_client(script)
    async with client:
        account = await client.account_by_puuid("p1")
    assert account.puuid == "puuid-1"
    assert len(script.requests) == 2


async def test_network_errors_exhausted_raise_unavailable() -> None:
    script = Script(connect_error)
    client, _ = make_client(script)
    async with client:
        with pytest.raises(RiotUnavailable, match="ConnectError"):
            await client.account_by_puuid("p1")
    assert len(script.requests) == MAX_ATTEMPTS


async def test_timeouts_are_retried() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    script = Script(timeout, timeout, reply(json=[]))
    client, _ = make_client(script)
    async with client:
        assert await client.league_entries_by_puuid("p1") == []
    assert len(script.requests) == 3


# --- rate limiting through the client ------------------------------------------------------


async def test_app_limits_from_settings_pace_requests() -> None:
    clock = FakeClock()
    script = Script(reply(json=ACCOUNT), clock=clock)
    client, _ = make_client(script, clock, riot_app_rate_limits="2:1,3:10")
    async with client:
        for _ in range(4):
            await client.account_by_puuid("p1")
    start = script.times[0]
    assert [t - start for t in script.times] == pytest.approx([0.0, 0.0, 1.0, 10.0])


async def test_concurrent_calls_respect_the_app_limit() -> None:
    clock = FakeClock()
    script = Script(reply(json=ACCOUNT), clock=clock)
    client, _ = make_client(script, clock, riot_app_rate_limits="3:1")
    async with client:
        results = await asyncio.gather(*(client.account_by_puuid(f"p{i}") for i in range(10)))
    assert len(results) == 10
    times = sorted(script.times)
    for i in range(len(times) - 3):
        assert times[i + 3] - times[i] >= 1.0


async def test_routing_values_have_independent_app_limits() -> None:
    clock = FakeClock()
    script = Script(reply(json=ACCOUNT), reply(json=SUMMONER), clock=clock)
    client, _ = make_client(script, clock, riot_app_rate_limits="1:1")
    async with client:
        await client.account_by_puuid("p1")  # americas
        await client.summoner_by_puuid("p1")  # na1
    assert clock.sleeps == []
    assert client.limiter_wait_estimate("account_by_puuid") == pytest.approx(1.0)
    assert client.limiter_wait_estimate("summoner_by_puuid") == pytest.approx(1.0)


async def test_method_and_app_limits_are_learned_from_headers() -> None:
    clock = FakeClock()
    headers = {
        "X-App-Rate-Limit": "20:1,100:120",
        "X-App-Rate-Limit-Count": "1:1,1:120",
        "X-Method-Rate-Limit": "1:10",
        "X-Method-Rate-Limit-Count": "1:10",
    }
    script = Script(
        reply(json=_minimal_match("NA1_1"), headers=headers),
        reply(json=ACCOUNT),
        reply(json=_minimal_match("NA1_1"), headers=headers),
        clock=clock,
    )
    client, _ = make_client(script, clock, riot_app_rate_limits="500:1")
    async with client:
        await client.match("NA1_1")
        regional = client.rate_limiter("regional")
        assert [str(limit) for limit in regional.app_limits] == ["20:1", "100:120"]
        assert [str(limit) for limit in regional.method_limits("match")] == ["1:10"]
        assert client.limiter_wait_estimate("match") == pytest.approx(10.0)
        assert client.limiter_wait_estimate("account_by_puuid") == 0.0
        await client.account_by_puuid("p1")  # another method is not held back
        await client.match("NA1_1")  # waits for the learned 1-per-10 s method limit
    start = script.times[0]
    assert [t - start for t in script.times] == pytest.approx([0.0, 0.0, 10.0])


def test_limiter_wait_estimate_rejects_unknown_methods() -> None:
    client = RiotClient(make_settings())
    with pytest.raises(ValueError):
        client.limiter_wait_estimate("champion_rotation")
    assert client.limiter_wait_estimate() == 0.0
    assert client.limiter_wait_estimate("match") == 0.0


# --- lifecycle and respx -------------------------------------------------------------------


async def test_aclose_is_idempotent_and_closed_client_refuses_requests() -> None:
    script = Script(reply(json=ACCOUNT))
    client, _ = make_client(script)
    await client.account_by_puuid("p1")
    await client.aclose()
    await client.aclose()
    assert client.closed
    with pytest.raises(RuntimeError):
        await client.account_by_puuid("p1")
    assert len(script.requests) == 1


async def test_respx_routes_default_transport() -> None:
    settings = make_settings()
    with respx.mock(assert_all_called=True, assert_all_mocked=True) as router:
        account_route = router.get(
            f"https://{AMERICAS}/riot/account/v1/accounts/by-riot-id/Hex%20Walker/NA1"
        ).respond(200, json=ACCOUNT)
        league_route = router.get(f"https://{NA1}/lol/league/v4/entries/by-puuid/puuid-1").respond(
            200, json=[LEAGUE_ENTRY]
        )
        async with RiotClient(settings) as client:
            account = await client.account_by_riot_id("Hex Walker", "NA1")
            entries = await client.league_entries_by_puuid(account.puuid)
    assert entries[0].queue_type == "RANKED_SOLO_5x5"
    assert account_route.calls.last.request.headers["X-Riot-Token"] == API_KEY
    assert league_route.call_count == 1


def _minimal_match(match_id: str) -> dict[str, Any]:
    participants = [
        {
            "puuid": f"p{i}",
            "participantId": i + 1,
            "teamId": 100 if i < 5 else 200,
            "championId": 1 + i,
            "championName": "Annie",
            "win": i < 5,
            "kills": 1,
            "deaths": 1,
            "assists": 1,
        }
        for i in range(10)
    ]
    return {
        "metadata": {
            "matchId": match_id,
            "dataVersion": "2",
            "participants": [p["puuid"] for p in participants],
        },
        "info": {
            "gameMode": "CLASSIC",
            "gameVersion": "16.18.712.3456",
            "gameDuration": 1800,
            "gameStartTimestamp": 1_767_902_400_000,
            "queueId": 420,
            "participants": participants,
            "teams": [{"teamId": 100, "win": True}, {"teamId": 200, "win": False}],
        },
    }


# --- fail fast (the API process) ------------------------------------------------------------


async def test_max_wait_fails_fast_instead_of_queuing() -> None:
    """An HTTP request must never park for minutes behind the worker's backfill: once the
    limiter would make it wait longer than ``max_wait``, it is answered with a 429."""
    clock = FakeClock()
    script = Script(reply(json=SUMMONER), clock=clock)
    client = RiotClient(
        make_settings(riot_app_rate_limits="1:120"),
        httpx.MockTransport(script),
        clock=clock,
        sleep=clock.sleep,
        rng=random.Random(7),
        rate_limit_margin=0.0,
        max_wait=5.0,
    )
    async with client:
        await client.summoner_by_puuid("p1")  # uses the only slot in the window
        with pytest.raises(RiotRateLimited) as info:
            await client.summoner_by_puuid("p1")
    assert len(script.requests) == 1
    assert clock.sleeps == []  # nothing waited
    assert info.value.retry_after == pytest.approx(120.0, abs=1.0)


async def test_max_wait_does_not_retry_429s_inside_the_request() -> None:
    clock = FakeClock()
    script = Script(reply(429, headers={"Retry-After": "30"}), clock=clock)
    client = RiotClient(
        make_settings(),
        httpx.MockTransport(script),
        clock=clock,
        sleep=clock.sleep,
        rng=random.Random(7),
        rate_limit_margin=0.0,
        max_wait=5.0,
    )
    async with client:
        with pytest.raises(RiotRateLimited):
            await client.match("NA1_1")
    assert len(script.requests) == 1
    assert clock.sleeps == []


async def test_budget_caps_this_process_share_of_the_key() -> None:
    """The public endpoints get their own small allowance out of the shared key, so a burst
    of lookups cannot spend the whole budget the worker needs."""
    clock = FakeClock()

    def route(request: httpx.Request) -> httpx.Response:
        body = SUMMONER if "summoner" in request.url.path else ACCOUNT
        return httpx.Response(200, json=body)

    script = Script(route, clock=clock)
    client = RiotClient(
        make_settings(),
        httpx.MockTransport(script),
        clock=clock,
        sleep=clock.sleep,
        rng=random.Random(7),
        rate_limit_margin=0.0,
        budget=[(2, 120.0)],
    )
    async with client:
        await client.account_by_puuid("p1")
        await client.account_by_puuid("p2")
        with pytest.raises(RiotRateLimited) as info:
            await client.account_by_puuid("p3")
        # A different routing value has its own allowance.
        await client.summoner_by_puuid("p1")
    assert len(script.requests) == 3
    assert clock.sleeps == []
    assert "budget" in str(info.value)


async def test_worker_limits_leave_room_for_on_demand_requests() -> None:
    settings = make_settings(
        riot_app_rate_limits="20:1,100:120", riot_ondemand_rate_limits="5:1,20:120"
    )
    assert settings.worker_app_rate_limits == [(15, 1.0), (80, 120.0)]
    assert settings.ondemand_rate_limits == [(5, 1.0), (20, 120.0)]


async def test_successful_call_records_when_riot_last_accepted_the_key() -> None:
    script = Script(reply(json=SUMMONER))
    client, _ = make_client(script)
    async with client:
        assert client.status.last_ok_at is None
        await client.summoner_by_puuid("p1")
    assert client.status.last_ok_at is not None
    assert datetime.now(UTC) - client.status.last_ok_at < timedelta(minutes=1)
