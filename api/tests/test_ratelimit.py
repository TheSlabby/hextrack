"""Unit tests for hextrack.riot.ratelimit (fake clock; one short real-time test)."""

from __future__ import annotations

import asyncio
import time

import pytest

from hextrack.riot.ratelimit import (
    RateLimit,
    RateLimiter,
    parse_rate_limit_header,
)


class FakeClock:
    """Monotonic fake time; ``sleep`` advances it instantly and yields to the loop."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(seconds, 0.0)
        await asyncio.sleep(0)


def make_limiter(
    limits: list[tuple[int, float]], *, margin: float = 0.0
) -> tuple[RateLimiter, FakeClock]:
    clock = FakeClock()
    return RateLimiter(limits, clock=clock, sleep=clock.sleep, margin=margin), clock


def assert_sliding_window(times: list[float], limit: int, window: float, tol: float = 0.0) -> None:
    """No ``window``-long interval contains more than ``limit`` of ``times``."""
    ordered = sorted(times)
    for i in range(len(ordered) - limit):
        assert ordered[i + limit] - ordered[i] >= window - tol, (i, ordered)


# --- parsing -------------------------------------------------------------------------------


def test_parse_rate_limit_header() -> None:
    assert parse_rate_limit_header("20:1,100:120") == [(20, 1.0), (100, 120.0)]
    assert parse_rate_limit_header(" 20:1 , 100:120 ") == [(20, 1.0), (100, 120.0)]
    # Count headers can carry zero counts; malformed / non-positive windows are dropped.
    assert parse_rate_limit_header("0:10,bad,5:x,:3,3:0,7:-1,-1:5,2:inf") == [(0, 10.0)]
    assert parse_rate_limit_header(None) == []
    assert parse_rate_limit_header("") == []


def test_rate_limit_validation_and_str() -> None:
    assert str(RateLimit(20, 1.0)) == "20:1"
    assert str(RateLimit(100, 120.0)) == "100:120"
    with pytest.raises(ValueError):
        RateLimit(0, 1.0)
    with pytest.raises(ValueError):
        RateLimit(5, 0.0)
    with pytest.raises(ValueError):
        RateLimiter([(1, 1.0)], margin=-1)


def test_limits_are_sorted_and_deduplicated() -> None:
    limiter, _ = make_limiter([(100, 120.0), (20, 1.0), (20, 1.0)])
    assert limiter.app_limits == (RateLimit(20, 1.0), RateLimit(100, 120.0))


# --- pacing --------------------------------------------------------------------------------


async def test_under_limit_does_not_wait() -> None:
    limiter, clock = make_limiter([(3, 1.0)])
    for _ in range(3):
        assert await limiter.acquire("m") == 0.0
    assert clock.sleeps == []


async def test_waits_for_the_window_to_slide() -> None:
    limiter, clock = make_limiter([(2, 1.0)])
    start = clock.now
    await limiter.acquire("m")
    await limiter.acquire("m")
    waited = await limiter.acquire("m")
    assert waited == pytest.approx(1.0)
    assert clock.now == pytest.approx(start + 1.0)


async def test_every_window_is_enforced() -> None:
    limiter, clock = make_limiter([(2, 1.0), (3, 10.0)])
    start = clock.now
    grants = []
    for _ in range(4):
        await limiter.acquire("m")
        grants.append(clock.now - start)
    # Third call waits for the 1 s window, fourth for the 10 s window.
    assert grants == pytest.approx([0.0, 0.0, 1.0, 10.0])


async def test_margin_widens_the_window() -> None:
    limiter, _ = make_limiter([(1, 1.0)], margin=0.25)
    await limiter.acquire("m")
    assert await limiter.acquire("m") == pytest.approx(1.25)


async def test_concurrent_waiters_never_over_admit_and_stay_fifo() -> None:
    limiter, clock = make_limiter([(3, 1.0), (5, 4.0)])
    order: list[int] = []
    times: list[float] = []

    async def worker(i: int) -> None:
        await limiter.acquire("m")
        order.append(i)
        times.append(clock.now)

    await asyncio.gather(*(worker(i) for i in range(12)))
    assert order == list(range(12))
    assert_sliding_window(times, 3, 1.0)
    assert_sliding_window(times, 5, 4.0)
    assert limiter.pending == 0


async def test_concurrent_methods_share_the_app_window_in_real_time() -> None:
    """Real clock, tiny windows: two methods hammer one 4-per-100 ms application limit."""
    limiter = RateLimiter([(4, 0.1)], margin=0.0)
    times: list[float] = []

    async def worker(method: str) -> None:
        await limiter.acquire(method)
        times.append(time.monotonic())

    started = time.monotonic()
    await asyncio.gather(*(worker("a" if i % 2 else "b") for i in range(12)))
    elapsed = time.monotonic() - started
    assert len(times) == 12
    # 12 requests at 4 per 100 ms need at least two full windows.
    assert elapsed >= 0.2 - 0.01
    assert elapsed < 2.0
    assert_sliding_window(times, 4, 0.1, tol=0.005)


# --- headers -------------------------------------------------------------------------------


async def test_headers_replace_app_limits_and_create_method_limits() -> None:
    limiter, clock = make_limiter([(20, 1.0), (100, 120.0)])
    await limiter.acquire("match")
    limiter.update_from_headers(
        "match",
        {
            "X-App-Rate-Limit": "500:10,30000:600",
            "X-App-Rate-Limit-Count": "1:10,1:600",
            "X-Method-Rate-Limit": "2:10",
            "X-Method-Rate-Limit-Count": "1:10",
        },
    )
    assert limiter.app_limits == (RateLimit(500, 10.0), RateLimit(30000, 600.0))
    assert limiter.method_limits("match") == (RateLimit(2, 10.0),)
    assert limiter.method_limits("summoner") == ()

    start = clock.now
    assert await limiter.acquire("match") == 0.0
    assert await limiter.acquire("match") == pytest.approx(10.0)
    # Another method is only bound by the (now generous) application limits.
    assert await limiter.acquire("summoner") == 0.0
    assert clock.now == pytest.approx(start + 10.0)


async def test_header_names_are_case_insensitive() -> None:
    limiter, _ = make_limiter([(20, 1.0)])
    limiter.update_from_headers("m", {"x-method-rate-limit": "7:3"})
    assert limiter.method_limits("m") == (RateLimit(7, 3.0),)


async def test_count_headers_pad_usage_we_did_not_see() -> None:
    limiter, _ = make_limiter([(5, 10.0)])
    await limiter.acquire("m")
    # Riot counts 4 requests in this window (another process shares the key).
    limiter.update_from_headers("m", {"X-App-Rate-Limit-Count": "4:10"})
    assert await limiter.acquire("m") == 0.0  # 5th
    assert await limiter.acquire("m") == pytest.approx(10.0)


async def test_count_headers_never_remove_local_hits() -> None:
    limiter, _ = make_limiter([(2, 10.0)])
    await limiter.acquire("m")
    await limiter.acquire("m")
    limiter.update_from_headers("m", {"X-App-Rate-Limit-Count": "0:10"})
    assert await limiter.acquire("m") == pytest.approx(10.0)


async def test_requests_sent_before_method_limits_are_known_still_count() -> None:
    limiter, clock = make_limiter([(100, 1.0)])
    await limiter.acquire("m")
    clock.now += 3.0
    await limiter.acquire("m")  # both sent before any response announced the method limit
    limiter.update_from_headers("m", {"X-Method-Rate-Limit": "2:10"})
    assert limiter.wait_estimate("m") == pytest.approx(7.0)


def test_malformed_headers_leave_limits_alone() -> None:
    limiter, _ = make_limiter([(20, 1.0), (100, 120.0)])
    limiter.update_from_headers(
        "m",
        {"X-App-Rate-Limit": "garbage", "X-Method-Rate-Limit": "0:10,:", "Other": "1:1"},
    )
    assert limiter.app_limits == (RateLimit(20, 1.0), RateLimit(100, 120.0))
    assert limiter.method_limits("m") == ()


# --- 429 penalties -------------------------------------------------------------------------


async def test_application_penalty_blocks_every_method() -> None:
    limiter, _ = make_limiter([(100, 1.0)])
    limiter.penalize("match", 5.0, "application")
    assert limiter.wait_estimate() == pytest.approx(5.0)
    assert limiter.wait_estimate("summoner") == pytest.approx(5.0)
    assert await limiter.acquire("summoner") == pytest.approx(5.0)


async def test_method_penalty_blocks_only_that_method() -> None:
    limiter, _ = make_limiter([(100, 1.0)])
    limiter.penalize("match", 5.0, "method")
    limiter.penalize("league", 2.0, None)  # service / unknown type -> that method only
    assert limiter.wait_estimate() == 0.0
    assert limiter.wait_estimate("summoner") == 0.0
    assert limiter.wait_estimate("match") == pytest.approx(5.0)
    assert limiter.wait_estimate("league") == pytest.approx(2.0)
    assert await limiter.acquire("summoner") == 0.0
    assert await limiter.acquire("match") == pytest.approx(5.0)


# --- estimates and cancellation ------------------------------------------------------------


async def test_wait_estimate_reflects_window_state() -> None:
    limiter, clock = make_limiter([(1, 1.0)])
    assert limiter.wait_estimate() == 0.0
    await limiter.acquire("m")
    assert limiter.wait_estimate() == pytest.approx(1.0)
    assert limiter.wait_estimate("m") == pytest.approx(1.0)
    clock.now += 0.4
    assert limiter.wait_estimate() == pytest.approx(0.6)
    clock.now += 0.6
    assert limiter.wait_estimate() == 0.0


async def test_wait_estimate_counts_queued_requests_and_cancel_is_clean() -> None:
    clock = FakeClock()
    release = asyncio.Event()

    async def parked_sleep(seconds: float) -> None:
        await release.wait()

    limiter = RateLimiter([(1, 1.0)], clock=clock, sleep=parked_sleep, margin=0.0)
    await limiter.acquire("m")
    waiters = [asyncio.create_task(limiter.acquire("m")) for _ in range(3)]
    await asyncio.sleep(0)
    assert limiter.pending == 3
    # Three queued requests take the slots at +1 s, +2 s and +3 s; a new one gets +4 s.
    assert limiter.wait_estimate("m") == pytest.approx(4.0)
    assert limiter.wait_estimate() == pytest.approx(4.0)

    for task in waiters:
        task.cancel()
    results = await asyncio.gather(*waiters, return_exceptions=True)
    assert all(isinstance(r, asyncio.CancelledError) for r in results)
    assert limiter.pending == 0
    # Cancelled waiters recorded nothing.
    assert limiter.wait_estimate("m") == pytest.approx(1.0)


async def test_counts_are_compared_at_send_time_not_response_time() -> None:
    """Riot counts a request when it arrives; comparing its count with the local window at
    response time makes the requests sent during the round trip look like usage we missed,
    and every phantom hit padded in costs a real request out of the window."""
    limiter, clock = make_limiter([(2, 1.0), (2, 120.0)])
    _start, sent_at = await limiter.reserve("m")
    clock.now += 1.2  # the round trip outlived Riot's one-second window

    limiter.update_from_headers("m", {"X-App-Rate-Limit-Count": "1:1,1:120"}, sent_at=sent_at)

    # Riot's "1 in this window" is the request we already recorded, so nothing is padded and
    # the second slot of the two-minute window is still free.
    assert limiter.wait_estimate("m") == 0.0


async def test_counts_from_another_process_are_still_padded() -> None:
    limiter, clock = make_limiter([(5, 10.0)])
    _start, sent_at = await limiter.reserve("m")
    clock.now += 0.2
    limiter.update_from_headers("m", {"X-App-Rate-Limit-Count": "4:10"}, sent_at=sent_at)
    assert await limiter.acquire("m") == 0.0  # the fifth
    assert await limiter.acquire("m") > 0.0


async def test_429_counts_are_ignored_because_penalize_models_the_block() -> None:
    """A 429 reports a full window; padding it would block for the whole window even when
    Riot's Retry-After says the block is over much sooner."""
    limiter, clock = make_limiter([(100, 120.0)])
    _start, sent_at = await limiter.reserve("m")
    limiter.update_from_headers(
        "m", {"X-App-Rate-Limit-Count": "100:120"}, sent_at=sent_at, sync_counts=False
    )
    limiter.penalize("m", 30.0, "application")
    assert limiter.wait_estimate("m") == pytest.approx(30.0)
    clock.now += 30.0
    assert limiter.wait_estimate("m") == 0.0


def test_configured_limits_are_a_ceiling_for_the_announced_ones() -> None:
    """Configuring less than the key allows is how a deployment reserves part of it for
    another process; Riot's headers must not raise it back."""
    limiter, _ = make_limiter([(20, 1.0), (70, 120.0)])
    limiter.update_from_headers("m", {"X-App-Rate-Limit": "20:1,100:120"})
    assert limiter.app_limits == (RateLimit(20, 1.0), RateLimit(70, 120.0))


def test_announced_windows_that_are_not_configured_are_adopted_as_is() -> None:
    """A production key announces different windows; the dev-key defaults must not throttle
    it to 100 per two minutes."""
    limiter, _ = make_limiter([(20, 1.0), (100, 120.0)])
    limiter.update_from_headers("m", {"X-App-Rate-Limit": "500:10,30000:600"})
    assert limiter.app_limits == (RateLimit(500, 10.0), RateLimit(30000, 600.0))
