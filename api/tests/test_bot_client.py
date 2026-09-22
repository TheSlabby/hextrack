"""Bot wiring without Discord: configuration checks, intents, /lp, sender, heartbeat."""

from __future__ import annotations

import asyncio
import types
from datetime import UTC, datetime
from typing import Any

import discord
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.bot import __main__ as bot_main
from hextrack.bot import client
from hextrack.bot.client import (
    BOT_STATE_KEY,
    NO_PLAYER_DATA,
    NOT_TRACKED,
    SHUTDOWN_GRACE_SECONDS,
    BotNotConfigured,
    ChannelSender,
    DDragonContextProvider,
    HexTrackBot,
    HexTrackCog,
    LpReply,
    bot_config,
    bot_intents,
    lp_choices,
    lp_reply,
    missing_broadcast_permissions,
    run_bot,
)
from hextrack.bot.consumer import DeliveryBlocked, is_delivery_blocked, static_context_provider
from hextrack.bot.embeds import EmbedContext
from hextrack.bot.queries import get_state
from hextrack.config import Settings
from hextrack.db.models import BotEvent, RankSnapshot, Summoner
from hextrack.rank import rank_value
from hextrack.riot.ddragon import FALLBACK_VERSION

CTX = EmbedContext(public_url="https://hextrack.example", ddragon_version="16.18.1")


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[discord.Embed] = []

    async def send(self, embed: discord.Embed) -> None:
        self.sent.append(embed)


def configured(settings: Settings, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "discord_token": "test-token-not-real",
        "discord_broadcast_channel_id": 123456789,
    }
    values.update(overrides)
    return settings.model_copy(update=values)


# --- configuration ------------------------------------------------------------------------


def test_bot_config_requires_token_and_channel(settings: Settings) -> None:
    with pytest.raises(
        BotNotConfigured, match="DISCORD_TOKEN and DISCORD_BROADCAST_CHANNEL_ID are not set"
    ):
        bot_config(settings)
    with pytest.raises(BotNotConfigured, match="DISCORD_BROADCAST_CHANNEL_ID is not set"):
        bot_config(configured(settings, discord_broadcast_channel_id=None))
    with pytest.raises(BotNotConfigured, match="DISCORD_TOKEN is not set"):
        bot_config(configured(settings, discord_token=None))
    config = bot_config(configured(settings))
    assert (config.token, config.channel_id) == ("test-token-not-real", 123456789)


async def test_run_bot_refuses_to_start_without_configuration(settings: Settings) -> None:
    with pytest.raises(BotNotConfigured):
        await run_bot(settings)
    with pytest.raises(BotNotConfigured):
        await run_bot(configured(settings, discord_broadcast_channel_id=None))


def test_module_entrypoint_reports_missing_configuration(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bot_main, "get_settings", lambda: settings)
    monkeypatch.setattr(bot_main, "setup_logging", lambda: None)
    assert bot_main.main() == 2
    assert "DISCORD_TOKEN" in capsys.readouterr().err


def test_intents_are_minimal() -> None:
    intents = bot_intents()
    assert intents.guilds
    assert not intents.message_content
    assert not intents.members
    assert not intents.presences
    assert not intents.guild_messages
    assert intents.value == discord.Intents(guilds=True).value


async def test_bot_registers_lp_and_loops(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tuned = configured(settings, discord_daily_post_hour=7, discord_tz="Europe/Berlin")
    bot = HexTrackBot(tuned, session_factory, sender=FakeSender(), sync_commands=False)
    try:
        assert bot.intents.value == bot_intents().value
        cog = HexTrackCog(bot)
        (command,) = cog.get_app_commands()
        assert command.name == "lp"
        assert command.description == "View LP for player"
        assert isinstance(command, discord.app_commands.Command)
        (param,) = command.parameters
        assert param.name == "name" and param.required and param.autocomplete
        assert cog.consume_loop.seconds == 10
        (post_time,) = cog.daily_loop.time
        assert (post_time.hour, post_time.minute) == (7, 0)
        assert post_time.tzinfo is not None and str(post_time.tzinfo) == "Europe/Berlin"
        assert not cog.consume_loop.is_running() and not cog.daily_loop.is_running()
    finally:
        await bot.close()


async def test_cog_registers_lp_on_the_command_tree(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot = HexTrackBot(
        configured(settings), session_factory, sender=FakeSender(), sync_commands=False
    )
    async with bot:  # sets up the client without logging in
        await bot.add_cog(HexTrackCog(bot))
        assert bot.tree.get_command("lp") is not None
        cog = bot.get_cog("HexTrack")
        assert isinstance(cog, HexTrackCog)
        assert cog.consume_loop.is_running() and cog.daily_loop.is_running()
        await bot.remove_cog("HexTrack")
        assert bot.tree.get_command("lp") is None
        await asyncio.sleep(0)
        assert not cog.consume_loop.is_running() and not cog.daily_loop.is_running()


def test_bot_needs_a_channel_when_no_sender_is_given(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    with pytest.raises(BotNotConfigured):
        HexTrackBot(settings, session_factory)


# --- /lp ----------------------------------------------------------------------------------


async def seed(session: AsyncSession) -> None:
    session.add_all(
        [
            Summoner(
                puuid="p1",
                game_name="Hex Walker",
                tag_line="NA1",
                platform="na1",
                profile_icon_id=4568,
                is_tracked=True,
                last_refreshed_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
            Summoner(
                puuid="p2",
                game_name="Unranked Guy",
                tag_line="NA1",
                platform="na1",
                is_tracked=True,
                last_refreshed_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
            Summoner(
                puuid="p3", game_name="Brand New", tag_line="NA1", platform="na1", is_tracked=True
            ),
            Summoner(puuid="p4", game_name="Hex Rando", tag_line="NA1", platform="na1"),
        ]
    )
    await session.flush()
    for lp, when in (
        (20, datetime(2026, 3, 1, tzinfo=UTC)),
        (45, datetime(2026, 3, 2, tzinfo=UTC)),
    ):
        session.add(
            RankSnapshot(
                puuid="p1",
                queue_type="RANKED_SOLO_5x5",
                tier="GOLD",
                rank="II",
                lp=lp,
                wins=30,
                losses=25,
                rank_value=rank_value("GOLD", "II", lp),
                taken_at=when,
            )
        )
    await session.flush()


async def test_lp_reply(clean_db: None, session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session, session.begin():
        await seed(session)

    ranked = await lp_reply(session_factory, CTX, "hex walker#na1")
    assert ranked.content is None and not ranked.ephemeral
    assert ranked.embed is not None
    assert ranked.embed.title == "Solo/Duo Ranked Info"
    assert ranked.embed.description == "**Current Rank:** Gold II"
    assert [(f.name, f.value) for f in ranked.embed.fields] == [
        ("LP", "45 LP"),
        ("W/L Record", "30/25"),
        ("Winrate", "55%"),
    ]
    assert ranked.embed.author.url == "https://hextrack.example/summoner/na/Hex%20Walker-NA1"

    unranked = await lp_reply(session_factory, CTX, "Unranked Guy#NA1")
    assert unranked.embed is not None
    assert unranked.embed.description == "**Current Rank:** Unranked"

    assert await lp_reply(session_factory, CTX, "Brand New#NA1") == LpReply(
        content=NO_PLAYER_DATA, ephemeral=True
    )
    assert await lp_reply(session_factory, CTX, "Hex Rando#NA1") == LpReply(
        content=NOT_TRACKED, ephemeral=True
    )
    assert await lp_reply(session_factory, CTX, "not a riot id") == LpReply(
        content=NOT_TRACKED, ephemeral=True
    )


def test_lp_reply_send_kwargs() -> None:
    embed = discord.Embed(title="x")
    assert LpReply(embed=embed).send_kwargs() == {"ephemeral": False, "embed": embed}
    assert LpReply(content="nope", ephemeral=True).send_kwargs() == {
        "ephemeral": True,
        "content": "nope",
    }


async def test_lp_autocomplete_lists_tracked_players(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session, session.begin():
        await seed(session)
    choices = await lp_choices(session_factory, "hex")
    assert [(c.name, c.value) for c in choices] == [("Hex Walker#NA1", "Hex Walker#NA1")]
    everyone = await lp_choices(session_factory, "")
    assert [c.name for c in everyone] == ["Brand New#NA1", "Hex Walker#NA1", "Unranked Guy#NA1"]


# --- cog behaviour ------------------------------------------------------------------------


class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.deferred: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)

    async def defer(self, **kwargs: Any) -> None:
        self.deferred.append(kwargs)


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)


class FakeInteraction:
    def __init__(self) -> None:
        self.response = FakeResponse()
        self.followup = FakeFollowup()


async def test_lp_command_and_autocomplete_callbacks(
    clean_db: None, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session, session.begin():
        await seed(session)
    bot = HexTrackBot(
        configured(settings), session_factory, sender=FakeSender(), sync_commands=False
    )
    try:
        cog = HexTrackCog(bot)
        interaction = FakeInteraction()
        await cog.lp.callback(cog, interaction, "Hex Walker#NA1")  # type: ignore[arg-type]
        (message,) = interaction.response.messages
        assert message["ephemeral"] is False
        assert message["embed"].description == "**Current Rank:** Gold II"

        missing = FakeInteraction()
        await cog.lp.callback(cog, missing, "Nobody#NA1")  # type: ignore[arg-type]
        assert missing.response.messages == [{"ephemeral": True, "content": NOT_TRACKED}]

        choices = await cog.lp_name_autocomplete(FakeInteraction(), "walk")  # type: ignore[arg-type]
        assert [c.value for c in choices] == ["Hex Walker#NA1"]
    finally:
        await bot.close()


async def test_slow_lp_lookup_is_deferred(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow_reply(*args: Any, **kwargs: Any) -> LpReply:
        await asyncio.sleep(0.05)
        return LpReply(content=NOT_TRACKED, ephemeral=True)

    monkeypatch.setattr(client, "LP_DEFER_AFTER_SECONDS", 0.01)
    monkeypatch.setattr(client, "lp_reply", slow_reply)
    bot = HexTrackBot(
        configured(settings), session_factory, sender=FakeSender(), sync_commands=False
    )
    try:
        cog = HexTrackCog(bot)
        interaction = FakeInteraction()
        await cog.lp.callback(cog, interaction, "Anyone#NA1")  # type: ignore[arg-type]
    finally:
        await bot.close()
    assert interaction.response.deferred == [{"thinking": True}]
    assert interaction.response.messages == []
    assert interaction.followup.messages == [{"ephemeral": True, "content": NOT_TRACKED}]


async def test_lp_lookup_errors_become_a_friendly_message(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_reply(*args: Any, **kwargs: Any) -> LpReply:
        raise RuntimeError("database exploded")

    monkeypatch.setattr(client, "lp_reply", broken_reply)
    bot = HexTrackBot(
        configured(settings), session_factory, sender=FakeSender(), sync_commands=False
    )
    try:
        cog = HexTrackCog(bot)
        interaction = FakeInteraction()
        await cog.lp.callback(cog, interaction, "Anyone#NA1")  # type: ignore[arg-type]
    finally:
        await bot.close()
    assert interaction.response.messages == [{"ephemeral": True, "content": client.LP_FAILED}]


async def test_consume_tick_sends_and_writes_heartbeat(
    clean_db: None, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            BotEvent(
                kind="tier_up",
                payload={
                    "puuid": "p9",
                    "game_name": "Riser",
                    "tag_line": "NA1",
                    "queue_type": "RANKED_SOLO_5x5",
                    "old_tier": "SILVER",
                    "old_rank": "I",
                    "new_tier": "GOLD",
                    "new_rank": "IV",
                    "lp": 0,
                    "rank_value": 1200,
                },
            )
        )
    sender = FakeSender()
    bot = HexTrackBot(configured(settings), session_factory, sender=sender, sync_commands=False)
    try:
        await HexTrackCog(bot).consume_tick()
    finally:
        await bot.close()
    assert [e.title for e in sender.sent] == ["Ranked up to GOLD!"]
    async with session_factory() as session:
        state = await get_state(session, BOT_STATE_KEY)
    assert state is not None
    assert state["running"] is True
    assert state["connected"] is False  # never logged in
    assert state["last_error"] is None
    assert datetime.fromisoformat(state["heartbeat_at"]).tzinfo is not None


async def test_post_daily_catch_up_is_idempotent(
    clean_db: None, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    sender = FakeSender()
    tuned = configured(settings, discord_daily_post_hour=0)  # always due
    bot = HexTrackBot(tuned, session_factory, sender=sender, sync_commands=False)
    try:
        cog = HexTrackCog(bot)
        assert await cog.post_daily(scheduled=False)
        assert not await cog.post_daily(scheduled=True)
    finally:
        await bot.close()
    assert len(sender.sent) == 1


# --- broadcast channel ----------------------------------------------------------------------


class FakePermissions:
    def __init__(self, **flags: bool) -> None:
        self.view_channel = True
        self.send_messages = True
        self.embed_links = True
        self.__dict__.update(flags)


class FakeGuildChannel:
    """A text channel the bot can resolve permissions for."""

    def __init__(self, permissions: FakePermissions | None = None) -> None:
        self.guild = types.SimpleNamespace(me=object())
        self._permissions = permissions or FakePermissions()

    def permissions_for(self, member: Any) -> FakePermissions:
        return self._permissions

    async def send(self, **kwargs: Any) -> None: ...


def discord_error(cls: type[discord.HTTPException], status: int, message: str) -> Exception:
    response = types.SimpleNamespace(status=status, reason=message)
    return cls(response, {"code": status, "message": message})  # type: ignore[arg-type]


def bot_with_channel(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    cached: Any = None,
    fetch_error: Exception | None = None,
    channel_id: int | None = 123456789,
) -> HexTrackBot:
    bot = HexTrackBot(
        configured(settings, discord_broadcast_channel_id=channel_id),
        session_factory,
        sender=FakeSender(),
        sync_commands=False,
    )

    async def fetch_channel(cid: int, /) -> Any:
        if fetch_error is not None:
            raise fetch_error
        return cached

    bot.get_channel = lambda cid, /: cached  # type: ignore[method-assign, assignment]
    bot.fetch_channel = fetch_channel  # type: ignore[method-assign, assignment]
    return bot


def test_missing_broadcast_permissions() -> None:
    assert missing_broadcast_permissions(FakeGuildChannel()) == []
    channel = FakeGuildChannel(FakePermissions(embed_links=False, send_messages=False))
    assert missing_broadcast_permissions(channel) == ["Send Messages", "Embed Links"]
    assert missing_broadcast_permissions(FakeChannel()) == []  # a DM: nothing to check


async def test_broadcast_channel_check_names_the_problem(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cases: list[tuple[dict[str, Any], str | None]] = [
        ({"cached": FakeGuildChannel()}, None),
        (
            {"cached": FakeGuildChannel(FakePermissions(embed_links=False))},
            "missing Embed Links in channel 123456789",
        ),
        ({"cached": object()}, "cannot receive messages"),
        (
            {"fetch_error": discord_error(discord.NotFound, 404, "Unknown Channel")},
            "there is no channel 123456789",
        ),
        (
            {"fetch_error": discord_error(discord.Forbidden, 403, "Missing Access")},
            "not visible to the bot",
        ),
        # Discord being unreachable is not a configuration problem
        ({"fetch_error": discord_error(discord.HTTPException, 503, "Service Unavailable")}, None),
        ({"channel_id": None}, "DISCORD_BROADCAST_CHANNEL_ID is not set"),
    ]
    for kwargs, expected in cases:
        bot = bot_with_channel(settings, session_factory, **kwargs)
        try:
            problem = await bot.check_broadcast_channel()
        finally:
            await bot.close()
        if expected is None:
            assert problem is None, kwargs
        else:
            assert problem is not None and expected in problem, kwargs


async def test_a_broken_channel_is_reported_at_startup_and_in_the_heartbeat(
    clean_db: None, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot = bot_with_channel(
        settings,
        session_factory,
        cached=FakeGuildChannel(FakePermissions(send_messages=False)),
    )
    try:
        await bot.on_ready()
        assert bot.consumer.blocked_reason is not None
        assert "Send Messages" in bot.consumer.blocked_reason
        await HexTrackCog(bot).consume_tick()  # no events pending, but the problem stands
    finally:
        await bot.close()
    async with session_factory() as session:
        state = await get_state(session, BOT_STATE_KEY)
    assert state is not None and "Send Messages" in (state["last_error"] or "")

    # a channel that works clears the report
    healthy = bot_with_channel(settings, session_factory, cached=FakeGuildChannel())
    try:
        await healthy.on_ready()
        assert healthy.consumer.blocked_reason is None
    finally:
        await healthy.close()
    async with session_factory() as session:
        state = await get_state(session, BOT_STATE_KEY)
    assert state is not None and state["last_error"] is None


class StubLoop:
    """Enough of ``tasks.Loop`` for cog_unload: cancel() and get_task()."""

    def __init__(self, task: asyncio.Task[None] | None) -> None:
        self._task = task
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        if self._task is not None:
            self._task.cancel()

    def get_task(self) -> asyncio.Task[None] | None:
        return self._task


async def test_cog_unload_waits_for_a_post_in_flight(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Bot.close() unloads the cogs before closing the HTTP session, so cog_unload has to
    wait for the send-and-commit the consumer protects from the cancellation."""
    finished = False

    async def delivering() -> None:
        nonlocal finished
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)  # what run_to_completion keeps alive
            finished = True
            raise

    bot = HexTrackBot(
        configured(settings), session_factory, sender=FakeSender(), sync_commands=False
    )
    try:
        cog = HexTrackCog(bot)
        task = asyncio.create_task(delivering())
        await asyncio.sleep(0)
        consume, daily = StubLoop(task), StubLoop(None)
        cog.consume_loop = consume  # type: ignore[assignment]
        cog.daily_loop = daily  # type: ignore[assignment]
        await cog.cog_unload()
    finally:
        await bot.close()

    assert consume.cancelled and daily.cancelled
    assert finished and task.done()
    assert SHUTDOWN_GRACE_SECONDS >= 5


# --- collaborators ------------------------------------------------------------------------


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


class FakeClient:
    def __init__(self, cached: Any = None, fetched: Any = None) -> None:
        self.cached = cached
        self.fetched = fetched
        self.fetches = 0

    def get_channel(self, id: int, /) -> Any:
        return self.cached

    async def fetch_channel(self, channel_id: int, /) -> Any:
        self.fetches += 1
        return self.fetched


async def test_channel_sender_uses_cache_then_fetch() -> None:
    embed = discord.Embed(title="hi")
    cached = FakeChannel()
    await ChannelSender(FakeClient(cached=cached), 1).send(embed)
    assert cached.sent[0]["embed"] is embed
    mentions = cached.sent[0]["allowed_mentions"]
    assert isinstance(mentions, discord.AllowedMentions)
    assert not mentions.everyone and not mentions.users and not mentions.roles

    fetched = FakeChannel()
    source = FakeClient(fetched=fetched)
    await ChannelSender(source, 1).send(embed)
    assert source.fetches == 1 and len(fetched.sent) == 1


async def test_channel_sender_rejects_channels_without_send() -> None:
    # a configuration problem, so the consumer keeps the event instead of retrying it away
    with pytest.raises(DeliveryBlocked, match="cannot receive messages") as excinfo:
        await ChannelSender(FakeClient(cached=object()), 42).send(discord.Embed())
    assert is_delivery_blocked(excinfo.value)


class StubDDragon:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail

    async def latest_version(self) -> str:
        if self.fail:
            raise NotImplementedError("offline")
        return "16.19.1"

    async def champion_map(self) -> dict[int, str]:
        if self.fail:
            raise RuntimeError("offline")
        return {9: "Fiddlesticks"}


async def test_ddragon_context_provider(settings: Settings) -> None:
    offline = DDragonContextProvider(settings, StubDDragon(fail=True))  # type: ignore[arg-type]
    ctx = await offline.refresh()
    assert ctx.ddragon_version == FALLBACK_VERSION
    assert dict(ctx.champion_keys) == {}

    online = DDragonContextProvider(settings, StubDDragon(fail=False))  # type: ignore[arg-type]
    assert (await online()).ddragon_version == FALLBACK_VERSION  # returns at once
    await online.aclose()
    ctx = await online.refresh()
    assert ctx.ddragon_version == "16.19.1"
    assert dict(ctx.champion_keys) == {9: "Fiddlesticks"}
    assert (await online()) is ctx  # fresh: no new refresh
    assert ctx.public_url == settings.public_url


async def test_static_context_provider(settings: Settings) -> None:
    ctx = await static_context_provider(settings)()
    assert ctx.ddragon_version == FALLBACK_VERSION
    assert ctx.rank_icon_base is None


def test_constants_match_lpbot() -> None:
    assert client.LP_NAME_DESCRIPTION == "Summoner Name & tagline (e.g. TheSlab#333)"
    assert NOT_TRACKED == "I'm not tracking that player :("
    assert NO_PLAYER_DATA == "I couldn't find their player data ;-;"
