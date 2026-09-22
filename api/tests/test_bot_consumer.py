"""Outbox consumer (claim, send, silent kinds, stale skip, retries) and the daily poster,
against the test database with a fake sender (no Discord)."""

from __future__ import annotations

import asyncio
import types
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import discord
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.bot import consumer as consumer_mod
from hextrack.bot.consumer import (
    DAILY_STATE_KEY,
    MAX_ATTEMPTS,
    STALE_NOTE,
    STALE_SEND_NOTE,
    DailyLeaderboardPoster,
    DeliveryBlocked,
    EventConsumer,
    claim_events,
    daily_post_due,
    is_delivery_blocked,
    parse_event,
)
from hextrack.bot.embeds import BAD_GAME_TITLE, GREAT_GAME_TITLE, EmbedContext
from hextrack.bot.queries import get_state, put_state
from hextrack.config import Settings
from hextrack.db.models import BotEvent, Match, MatchParticipant, RankSnapshot, Summoner
from hextrack.ingest.mapping import map_match
from hextrack.rank import rank_value
from tests.factories import make_match_json, spec

CHICAGO = ZoneInfo("America/Chicago")


class FakeSender:
    """Records embeds; fails the next ``fail_times`` sends (None: every send)."""

    def __init__(self, fail_times: int | None = 0, error: Exception | None = None) -> None:
        self.sent: list[discord.Embed] = []
        self.attempts = 0
        self.fail_times = fail_times
        self.error = error or ConnectionError("discord is down")

    async def send(self, embed: discord.Embed) -> None:
        self.attempts += 1
        if self.fail_times is None or self.fail_times > 0:
            if self.fail_times is not None:
                self.fail_times -= 1
            raise self.error
        self.sent.append(embed)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class BlockingSender:
    """Like :class:`FakeSender`, but the ``block_at``-th send waits for ``release``."""

    def __init__(self, block_at: int) -> None:
        self.sent: list[discord.Embed] = []
        self.attempts = 0
        self.block_at = block_at
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()

    async def send(self, embed: discord.Embed) -> None:
        self.attempts += 1
        if self.attempts == self.block_at:
            self.blocked.set()
            await self.release.wait()
        self.sent.append(embed)


def http_error(status: int) -> discord.HTTPException:
    response = types.SimpleNamespace(status=status, reason="Bad Request")
    return discord.HTTPException(response, {"code": 50035, "message": "Invalid Form Body"})  # type: ignore[arg-type]


def forbidden() -> discord.Forbidden:
    response = types.SimpleNamespace(status=403, reason="Forbidden")
    return discord.Forbidden(response, {"code": 50013, "message": "Missing Permissions"})  # type: ignore[arg-type]


def not_found() -> discord.NotFound:
    response = types.SimpleNamespace(status=404, reason="Not Found")
    return discord.NotFound(response, {"code": 10003, "message": "Unknown Channel"})  # type: ignore[arg-type]


def game_payload(puuid: str = "p1", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "puuid": puuid,
        "game_name": "Old Name",
        "tag_line": "NA1",
        "match_id": "NA1_7001",
        "queue_id": 420,
        "champion_id": 103,
        "champion_name": "Ahri",
        "win": True,
        "kills": 12,
        "deaths": 1,
        "assists": 9,
        "kda": 21.0,
        "ai_score": 0.9,
        "game_start": "2026-03-01T20:00:00+00:00",
        "game_duration": 1800,
    }
    payload.update(overrides)
    return payload


def tier_payload(puuid: str = "p1", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "puuid": puuid,
        "game_name": "Old Name",
        "tag_line": "NA1",
        "queue_type": "RANKED_SOLO_5x5",
        "old_tier": "SILVER",
        "old_rank": "I",
        "new_tier": "GOLD",
        "new_rank": "IV",
        "lp": 0,
        "rank_value": 1200,
    }
    payload.update(overrides)
    return payload


async def add_events(
    factory: async_sessionmaker[AsyncSession],
    *events: tuple[str, dict[str, Any]],
    created_at: datetime | None = None,
) -> list[int]:
    base = created_at or datetime.now(UTC) - timedelta(minutes=5)
    async with factory() as session, session.begin():
        rows = [
            BotEvent(kind=kind, payload=payload, created_at=base + timedelta(seconds=i))
            for i, (kind, payload) in enumerate(events)
        ]
        session.add_all(rows)
        await session.flush()
        return [row.id for row in rows]


async def events_by_id(factory: async_sessionmaker[AsyncSession]) -> dict[int, BotEvent]:
    async with factory() as session:
        rows = await session.scalars(select(BotEvent).order_by(BotEvent.id))
        return {row.id: row for row in rows}


def make_consumer(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    sender: FakeSender,
    **kwargs: Any,
) -> EventConsumer:
    kwargs.setdefault("retry_backoff_seconds", 0)
    return EventConsumer(factory, settings, sender, **kwargs)


# --- parsing ------------------------------------------------------------------------------


def test_parse_event_rejects_bad_payloads() -> None:
    assert parse_event("tier_up", tier_payload()).new_tier == "GOLD"
    assert parse_event("great_game", game_payload()).match_id == "NA1_7001"
    with pytest.raises(consumer_mod.InvalidEvent, match="unknown event kind"):
        parse_event("party_time", {})
    with pytest.raises(consumer_mod.InvalidEvent, match="invalid great_game payload: match_id"):
        parse_event("great_game", {k: v for k, v in game_payload().items() if k != "match_id"})


# --- consumer -----------------------------------------------------------------------------


async def test_sends_great_game_and_marks_processed(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            Summoner(
                puuid="p1",
                game_name="Hex Walker",
                tag_line="NA1",
                platform="na1",
                profile_icon_id=4568,
                is_tracked=True,
            )
        )
    (event_id,) = await add_events(session_factory, ("great_game", game_payload()))
    sender = FakeSender()
    result = await make_consumer(session_factory, settings, sender).process_batch()

    assert (result.claimed, result.sent, result.silent, result.failed, result.gave_up) == (
        1,
        1,
        0,
        0,
        0,
    )
    (embed,) = sender.sent
    assert embed.title == GREAT_GAME_TITLE
    # current name and icon from summoners, not the payload snapshot
    assert embed.author.name == "Hex Walker#NA1"
    assert embed.author.url == "http://localhost:5173/summoner/na/Hex%20Walker-NA1"
    assert embed.author.icon_url is not None and embed.author.icon_url.endswith("/4568.png")
    assert embed.footer.text == "AI Score: 90%"
    row = (await events_by_id(session_factory))[event_id]
    assert row.processed_at is not None
    assert row.attempts == 0
    assert row.last_error is None


async def test_unknown_player_falls_back_to_payload_name(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_events(session_factory, ("tier_down", tier_payload("ghost", new_tier="IRON")))
    sender = FakeSender()
    await make_consumer(session_factory, settings, sender).process_batch()
    (embed,) = sender.sent
    assert embed.title == "Old Name#NA1 is a LOSER!"
    assert embed.description == "They just deranked to IRON! LOL"


async def test_new_match_and_disabled_bad_game_are_consumed_silently(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    ids = await add_events(
        session_factory,
        ("new_match", game_payload()),
        ("bad_game", game_payload(kills=0, deaths=10, assists=1)),
        ("new_match", {"not": "validated"}),
    )
    sender = FakeSender()
    result = await make_consumer(session_factory, settings, sender).process_batch()
    assert sender.attempts == 0
    assert (result.claimed, result.silent, result.sent) == (3, 3, 0)
    rows = await events_by_id(session_factory)
    assert all(rows[i].processed_at is not None and rows[i].last_error is None for i in ids)


async def test_bad_game_is_sent_when_enabled(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_events(session_factory, ("bad_game", game_payload(kills=0, deaths=10, assists=1)))
    sender = FakeSender()
    enabled = settings.model_copy(update={"bad_game_embeds": True})
    result = await make_consumer(session_factory, enabled, sender).process_batch()
    assert result.sent == 1
    assert sender.sent[0].title == BAD_GAME_TITLE


async def test_claims_oldest_first_in_batches_of_twenty(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_events(
        session_factory,
        *[("tier_up", tier_payload(f"p{i:02d}", game_name=f"P{i:02d}")) for i in range(25)],
    )
    sender = FakeSender()
    worker = make_consumer(session_factory, settings, sender)

    first = await worker.process_batch()
    assert (first.claimed, first.sent) == (20, 20)
    second = await worker.process_batch()
    assert (second.claimed, second.sent) == (5, 5)
    third = await worker.process_batch()
    assert third.claimed == 0
    assert [e.author.name for e in sender.sent] == [f"P{i:02d}#NA1" for i in range(25)]


async def test_skip_locked_rows_held_by_another_consumer(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    ids = await add_events(session_factory, *[("tier_up", tier_payload(f"p{i}")) for i in range(4)])
    sender = FakeSender()
    async with session_factory() as other, other.begin():
        held = await claim_events(other, limit=2)
        assert [r.id for r in held] == ids[:2]
        result = await make_consumer(session_factory, settings, sender).process_batch()
        assert (result.claimed, result.sent) == (2, 2)
    rows = await events_by_id(session_factory)
    assert [rows[i].processed_at is not None for i in ids] == [False, False, True, True]


async def test_skip_stale_marks_old_events_without_sending(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    now = datetime.now(UTC)
    (old,) = await add_events(
        session_factory, ("great_game", game_payload()), created_at=now - timedelta(hours=7)
    )
    (fresh,) = await add_events(
        session_factory, ("great_game", game_payload()), created_at=now - timedelta(hours=1)
    )
    sender = FakeSender()
    worker = make_consumer(session_factory, settings, sender)

    assert await worker.skip_stale(now=now) == 1
    rows = await events_by_id(session_factory)
    assert rows[old].processed_at is not None
    assert rows[old].last_error == STALE_NOTE
    assert rows[fresh].processed_at is None
    assert sender.attempts == 0

    result = await worker.process_batch()
    assert (result.claimed, result.sent) == (1, 1)
    assert await worker.skip_stale(now=now) == 0


async def test_failed_send_is_retried_then_succeeds(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    (event_id,) = await add_events(session_factory, ("tier_up", tier_payload()))
    sender = FakeSender(fail_times=1)
    worker = make_consumer(session_factory, settings, sender)

    first = await worker.process_batch()
    assert (first.failed, first.sent) == (1, 0)
    row = (await events_by_id(session_factory))[event_id]
    assert row.attempts == 1
    assert row.processed_at is None
    assert row.last_error == "ConnectionError: discord is down"

    second = await worker.process_batch()
    assert second.sent == 1
    row = (await events_by_id(session_factory))[event_id]
    assert row.attempts == 1
    assert row.processed_at is not None
    assert row.last_error is None


async def test_gives_up_after_five_attempts(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    (event_id,) = await add_events(session_factory, ("tier_up", tier_payload()))
    sender = FakeSender(fail_times=None)
    worker = make_consumer(session_factory, settings, sender)

    results = [await worker.process_batch() for _ in range(5)]
    assert [r.failed for r in results] == [1, 1, 1, 1, 0]
    assert results[-1].gave_up == 1
    row = (await events_by_id(session_factory))[event_id]
    assert row.attempts == 5
    assert row.processed_at is not None
    assert row.last_error == "ConnectionError: discord is down"

    assert (await worker.process_batch()).claimed == 0
    assert sender.attempts == 5


async def test_failure_holds_back_the_rest_of_the_batch(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    ids = await add_events(session_factory, *[("tier_up", tier_payload(f"p{i}")) for i in range(3)])
    sender = FakeSender(fail_times=1)
    worker = make_consumer(session_factory, settings, sender)

    first = await worker.process_batch()
    # the batch stops at the failure, so the events behind it are not even claimed
    assert (first.claimed, first.failed, first.sent) == (1, 1, 0)
    rows = await events_by_id(session_factory)
    assert [rows[i].attempts for i in ids] == [1, 0, 0]
    assert all(rows[i].processed_at is None for i in ids)

    second = await worker.process_batch()
    assert second.sent == 3
    assert [e.author.name for e in sender.sent] == ["Old Name#NA1"] * 3


async def test_backoff_between_failed_sends(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_events(session_factory, ("tier_up", tier_payload()))
    sender = FakeSender(fail_times=2)
    clock = FakeClock()
    worker = make_consumer(session_factory, settings, sender, retry_backoff_seconds=10, clock=clock)

    assert (await worker.process_batch()).failed == 1
    waiting = await worker.process_batch()
    assert waiting.backing_off and waiting.claimed == 0
    clock.now += 10
    assert (await worker.process_batch()).failed == 1
    clock.now += 10  # second failure doubles the delay to 20 s
    assert (await worker.process_batch()).backing_off
    clock.now += 10
    assert (await worker.process_batch()).sent == 1
    assert not worker.backing_off
    assert sender.attempts == 3


async def test_invalid_payloads_are_dropped_and_the_batch_continues(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    broken = {k: v for k, v in game_payload().items() if k != "kills"}
    ids = await add_events(
        session_factory,
        ("great_game", broken),
        ("mystery", {"x": 1}),
        ("tier_up", tier_payload(new_tier="WOOD")),
        ("tier_up", tier_payload()),
    )
    sender = FakeSender()
    result = await make_consumer(session_factory, settings, sender).process_batch()
    assert (result.claimed, result.gave_up, result.sent) == (4, 3, 1)
    rows = await events_by_id(session_factory)
    for event_id in ids[:3]:
        assert rows[event_id].processed_at is not None
        assert rows[event_id].attempts == 1
        assert rows[event_id].last_error
    assert "kills" in (rows[ids[0]].last_error or "")
    assert "unknown event kind 'mystery'" in (rows[ids[1]].last_error or "")
    assert rows[ids[3]].last_error is None


async def test_discord_bad_request_is_permanent(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    ids = await add_events(
        session_factory, ("tier_up", tier_payload("p1")), ("tier_up", tier_payload("p2"))
    )
    sender = FakeSender(fail_times=1, error=http_error(400))
    worker = make_consumer(session_factory, settings, sender, retry_backoff_seconds=10)
    result = await worker.process_batch()
    assert (result.gave_up, result.sent) == (1, 1)
    assert not worker.backing_off
    rows = await events_by_id(session_factory)
    assert rows[ids[0]].processed_at is not None
    assert "400" in (rows[ids[0]].last_error or "")


async def test_missing_ai_score_is_read_from_the_participant_row(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    mapped = map_match(make_match_json("NA1_7001", [spec("p1", "Hex Walker", "NA1")]))
    async with session_factory() as session, session.begin():
        session.add(Match(**mapped.match))
        await session.flush()
        for row in mapped.participants:
            participant = MatchParticipant(**row)
            if row["puuid"] == "p1":
                participant.ai_score = 0.674
            session.add(participant)
    await add_events(
        session_factory,
        ("great_game", game_payload(ai_score=None)),
        ("great_game", game_payload(ai_score=None, match_id="NA1_404")),
    )
    sender = FakeSender()
    await make_consumer(session_factory, settings, sender).process_batch()
    assert [e.footer.text for e in sender.sent] == ["AI Score: 67%", None]


async def test_shutdown_mid_batch_does_not_repost_delivered_embeds(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Stopping the bot (SIGTERM -> cog_unload -> loop.cancel()) while a batch is running
    must not leave delivered embeds pending, or the next start posts them again."""
    ids = await add_events(session_factory, *[("tier_up", tier_payload(f"p{i}")) for i in range(3)])
    sender = BlockingSender(block_at=2)
    worker = make_consumer(session_factory, settings, sender)

    batch = asyncio.create_task(worker.process_batch())
    await asyncio.wait_for(sender.blocked.wait(), 5)
    batch.cancel()
    sender.release.set()  # the send that was in flight still completes
    with pytest.raises(asyncio.CancelledError):
        await batch

    assert len(sender.sent) == 2
    rows = await events_by_id(session_factory)
    assert [rows[i].processed_at is not None for i in ids] == [True, True, False]

    # the consumer that starts after the restart posts only what is left
    restarted = FakeSender()
    result = await make_consumer(session_factory, settings, restarted).process_batch()
    assert (result.claimed, result.sent) == (1, 1)
    assert len(sender.sent) + len(restarted.sent) == 3


async def test_channel_errors_keep_the_events_and_surface_the_reason(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """A wrong channel id or missing permissions is not the event's fault: it must not burn
    attempts, and it must be visible instead of being dropped silently."""
    ids = await add_events(session_factory, *[("tier_up", tier_payload(f"p{i}")) for i in range(2)])
    sender = FakeSender(fail_times=None, error=forbidden())
    clock = FakeClock()
    worker = make_consumer(session_factory, settings, sender, retry_backoff_seconds=10, clock=clock)

    result = await worker.process_batch()
    assert (result.claimed, result.sent, result.failed, result.gave_up) == (1, 0, 0, 0)
    assert result.blocked is not None and "Missing Permissions" in result.blocked
    assert worker.blocked_reason == result.blocked
    assert worker.backing_off  # the batch stops instead of hammering Discord

    # every retry over the back-off leaves the events untouched (before, five attempts each
    # gave up on them while /health still reported a healthy bot)
    for _ in range(MAX_ATTEMPTS + 1):
        clock.now += 600
        assert (await worker.process_batch()).blocked is not None
    rows = await events_by_id(session_factory)
    assert all(rows[i].processed_at is None and rows[i].attempts == 0 for i in ids)
    assert "Missing Permissions" in (rows[ids[0]].last_error or "")

    # once the channel works the queue drains and the heartbeat clears
    sender.fail_times = 0
    clock.now += 600
    result = await worker.process_batch()
    assert (result.claimed, result.sent) == (2, 2)
    assert worker.blocked_reason is None and result.blocked is None


@pytest.mark.parametrize("error", [not_found(), DeliveryBlocked("not a text channel")])
async def test_other_channel_errors_are_treated_the_same(
    clean_db: None,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    error: Exception,
) -> None:
    assert is_delivery_blocked(error)
    (event_id,) = await add_events(session_factory, ("tier_up", tier_payload()))
    worker = make_consumer(session_factory, settings, FakeSender(fail_times=None, error=error))
    result = await worker.process_batch()
    assert result.blocked is not None and result.sent == 0
    row = (await events_by_id(session_factory))[event_id]
    assert row.attempts == 0 and row.processed_at is None


async def test_events_that_age_out_while_pending_are_not_posted(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Old news is dropped when it is claimed too, not only by the startup sweep."""
    now = datetime.now(UTC)
    (old,) = await add_events(
        session_factory, ("great_game", game_payload()), created_at=now - timedelta(hours=7)
    )
    (fresh,) = await add_events(session_factory, ("tier_up", tier_payload()))
    sender = FakeSender()
    result = await make_consumer(session_factory, settings, sender).process_batch()

    assert (result.claimed, result.stale, result.sent) == (2, 1, 1)
    assert len(sender.sent) == 1
    rows = await events_by_id(session_factory)
    assert rows[old].processed_at is not None and rows[old].last_error == STALE_SEND_NOTE
    assert rows[old].attempts == 0
    assert rows[fresh].processed_at is not None and rows[fresh].last_error is None


async def test_context_provider_is_used_for_assets(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_events(
        session_factory, ("great_game", game_payload(champion_id=9, champion_name="FiddleSticks"))
    )
    calls = 0

    async def provider() -> EmbedContext:
        nonlocal calls
        calls += 1
        return EmbedContext(
            public_url="https://hextrack.example",
            ddragon_version="99.1.1",
            champion_keys={9: "Fiddlesticks"},
        )

    sender = FakeSender()
    worker = EventConsumer(session_factory, settings, sender, provider, retry_backoff_seconds=0)
    await worker.process_batch()
    assert sender.sent[0].thumbnail.url == (
        "https://ddragon.leagueoflegends.com/cdn/99.1.1/img/champion/Fiddlesticks.png"
    )
    await worker.process_batch()  # nothing pending: no asset lookup
    assert calls == 1


# --- daily leaderboard --------------------------------------------------------------------


def local(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=CHICAGO)


@pytest.mark.parametrize(
    ("now", "last", "due"),
    [
        (local(2026, 3, 10, 5, 59), None, False),
        (local(2026, 3, 10, 6, 0), None, True),
        (local(2026, 3, 10, 23, 0), date(2026, 3, 9), True),
        (local(2026, 3, 10, 7, 0), date(2026, 3, 10), False),
        (local(2026, 3, 10, 7, 0), date(2026, 3, 11), False),
    ],
)
def test_daily_post_due(now: datetime, last: date | None, due: bool) -> None:
    assert daily_post_due(now, last, 6) is due


async def seed_leaderboard(session: AsyncSession, season: datetime) -> None:
    players: list[tuple[str, str, list[tuple[str, str | None, int]]]] = [
        ("p-climb", "Climber", [("DIAMOND", "I", 75), ("MASTER", None, 50)]),
        ("p-fall", "Faller", [("GOLD", "II", 50), ("GOLD", "III", 30)]),
        ("p-flat", "Flat", [("SILVER", "I", 10)]),
    ]
    for puuid, name, ladder in players:
        session.add(
            Summoner(puuid=puuid, game_name=name, tag_line="NA1", platform="na1", is_tracked=True)
        )
        await session.flush()
        for i, (tier, rank, lp) in enumerate(ladder):
            session.add(
                RankSnapshot(
                    puuid=puuid,
                    queue_type="RANKED_SOLO_5x5",
                    tier=tier,
                    rank=rank,
                    lp=lp,
                    wins=10,
                    losses=10,
                    rank_value=rank_value(tier, rank, lp),
                    taken_at=season + timedelta(days=1 + i),
                )
            )
    await session.flush()


async def test_daily_leaderboard_posts_once_per_day(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with session_factory() as session, session.begin():
        await seed_leaderboard(session, settings.season_start)
    sender = FakeSender()
    poster = DailyLeaderboardPoster(session_factory, settings, sender)

    assert not await poster.post_if_due(now=local(2026, 3, 10, 5, 30))  # before 6 AM
    assert await poster.post_if_due(now=local(2026, 3, 10, 6, 0, 1))
    assert not await poster.post_if_due(now=local(2026, 3, 10, 18, 0))  # restart same day
    assert len(sender.sent) == 1

    embed = sender.sent[0]
    assert embed.title == "\N{TROPHY} Season 2026 Leaderboard"
    assert embed.description is not None
    body = embed.description.split("\n")[1:-1]
    assert len(body) == 2  # "Flat" has a single snapshot: +0 is skipped
    assert body[0].endswith("Climber#NA1") and "+75 LP" in body[0]  # Master+ math
    assert body[1].endswith("Faller#NA1") and "-120 LP" in body[1]

    async with session_factory() as session:
        state = await get_state(session, DAILY_STATE_KEY)
    assert state is not None and state["last_post_date"] == "2026-03-10"

    assert await poster.post_if_due(now=local(2026, 3, 10, 18, 0), force=True)
    assert await poster.post_if_due(now=local(2026, 3, 11, 6, 0))
    assert len(sender.sent) == 3


async def test_daily_post_uses_the_local_date(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with session_factory() as session, session.begin():
        await put_state(session, DAILY_STATE_KEY, {"last_post_date": "2026-03-10"})
    sender = FakeSender()
    poster = DailyLeaderboardPoster(session_factory, settings, sender)
    # 03:30 UTC on the 11th is still the evening of the 10th in Chicago.
    assert not await poster.post_if_due(now=datetime(2026, 3, 11, 3, 30, tzinfo=UTC))
    assert await poster.post_if_due(now=datetime(2026, 3, 11, 12, 0, tzinfo=UTC))
    assert sender.sent[0].description == "No ranked games played yet this season!"


async def test_failed_daily_post_is_not_recorded(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    sender = FakeSender(fail_times=1)
    poster = DailyLeaderboardPoster(session_factory, settings, sender)
    with pytest.raises(ConnectionError):
        await poster.post_if_due(now=local(2026, 3, 10, 6, 0))
    async with session_factory() as session:
        state = await get_state(session, DAILY_STATE_KEY)
    assert not (state or {}).get("last_post_date")
    assert await poster.post_if_due(now=local(2026, 3, 10, 6, 1))


async def test_daily_post_survives_a_shutdown_between_send_and_commit(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """If the date were committed after the send, a stop in between would make the catch-up
    post at the next start repeat today's leaderboard."""
    sender = BlockingSender(block_at=1)
    poster = DailyLeaderboardPoster(session_factory, settings, sender)

    post = asyncio.create_task(poster.post_if_due(now=local(2026, 3, 10, 6, 0, 1)))
    await asyncio.wait_for(sender.blocked.wait(), 5)
    post.cancel()
    sender.release.set()
    with pytest.raises(asyncio.CancelledError):
        await post

    assert len(sender.sent) == 1
    async with session_factory() as session:
        state = await get_state(session, DAILY_STATE_KEY)
    assert state is not None and state["last_post_date"] == "2026-03-10"

    restarted = FakeSender()
    catch_up = DailyLeaderboardPoster(session_factory, settings, restarted)
    assert not await catch_up.post_if_due(now=local(2026, 3, 10, 6, 5))
    assert restarted.sent == []


def test_scheduled_now_tolerates_early_timers(settings: Settings) -> None:
    poster = DailyLeaderboardPoster(None, settings, FakeSender())  # type: ignore[arg-type]
    early = local(2026, 3, 10, 5, 59, 30)
    assert poster.scheduled_now(early) == local(2026, 3, 10, 6, 0)
    too_early = local(2026, 3, 10, 5, 58)
    assert poster.scheduled_now(too_early) == too_early
    late = local(2026, 3, 10, 6, 0, 5)
    assert poster.scheduled_now(late) == late
    assert poster.season_year == 2026

    midnight = DailyLeaderboardPoster(
        None,  # type: ignore[arg-type]
        settings.model_copy(update={"discord_daily_post_hour": 0}),
        FakeSender(),
    )
    assert midnight.scheduled_now(local(2026, 3, 10, 23, 59, 59)) == local(2026, 3, 11, 0, 0)
