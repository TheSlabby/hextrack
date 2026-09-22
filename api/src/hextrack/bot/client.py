"""Discord bot entrypoint (discord.py 2.x), the Python replacement for the C++ LPBot.

The bot only reads the shared database; it never calls Riot. It runs three things:

* ``/lp <name>``: the latest solo/duo standing of a tracked player, with autocomplete over
  the roster;
* the outbox consumer (:class:`hextrack.bot.consumer.EventConsumer`) every 10 seconds;
* the daily season leaderboard at ``DISCORD_DAILY_POST_HOUR`` in ``DISCORD_TZ``
  (:class:`hextrack.bot.consumer.DailyLeaderboardPoster`), plus a catch-up post at startup
  when today's is still missing, which is how LPBot's ``tryDailyTrigger`` behaved.

Intents are minimal (``guilds`` only, nothing privileged): slash commands do not need
message content. A heartbeat is written to ``app_state["bot"]`` on every consumer tick.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import time as dtime
from typing import Any, Final, Protocol, cast

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.bot.consumer import (
    CONSUME_INTERVAL_SECONDS,
    ContextProvider,
    DailyLeaderboardPoster,
    DeliveryBlocked,
    EmbedSender,
    EventConsumer,
    is_delivery_blocked,
    static_context_provider,
)
from hextrack.bot.embeds import EmbedContext, PlayerRef, RankLine, player_info
from hextrack.bot.queries import latest_rank, put_state, resolve_tracked, search_roster
from hextrack.bot.state import BOT_STATE_KEY
from hextrack.config import Settings
from hextrack.db.engine import make_async_engine, make_session_factory, session_scope
from hextrack.riot.ddragon import DDragon
from hextrack.riotid import format_riot_id

logger = logging.getLogger(__name__)


LP_COMMAND: Final = "lp"
LP_DESCRIPTION: Final = "View LP for player"
LP_NAME_DESCRIPTION: Final = "Summoner Name & tagline (e.g. TheSlab#333)"
NOT_TRACKED: Final = "I'm not tracking that player :("
NO_PLAYER_DATA: Final = "I couldn't find their player data ;-;"
LP_FAILED: Final = "Something went wrong looking that up, try again in a bit."

#: Discord's limit for autocomplete choice names and values.
CHOICE_MAX_LENGTH: Final = 100
DDRAGON_TIMEOUT_SECONDS: Final = 10.0
#: /lp answers directly when the lookup finishes within this time, else defers.
LP_DEFER_AFTER_SECONDS: Final = 2.0
CONTEXT_REFRESH_SECONDS: Final = 30 * 60.0
DAILY_RETRIES: Final = 3
DAILY_RETRY_DELAY_SECONDS: Final = 60.0
#: How long the loops get to finish a post that is in flight when the bot stops.
SHUTDOWN_GRACE_SECONDS: Final = 15.0
#: Channel permissions the bot needs to broadcast, as ``discord.Permissions`` fields.
BROADCAST_PERMISSIONS: Final[tuple[tuple[str, str], ...]] = (
    ("view_channel", "View Channel"),
    ("send_messages", "Send Messages"),
    ("embed_links", "Embed Links"),
)


class BotNotConfigured(Exception):
    """DISCORD_TOKEN (or DISCORD_BROADCAST_CHANNEL_ID) is missing or was rejected."""


@dataclass(frozen=True, slots=True)
class BotConfig:
    token: str
    channel_id: int


def bot_config(settings: Settings) -> BotConfig:
    """The token and broadcast channel, or :class:`BotNotConfigured` naming what is missing."""
    token = settings.discord_token
    channel_id = settings.discord_broadcast_channel_id
    if not token or channel_id is None:
        missing = [
            name
            for name, absent in (
                ("DISCORD_TOKEN", not token),
                ("DISCORD_BROADCAST_CHANNEL_ID", channel_id is None),
            )
            if absent
        ]
        raise BotNotConfigured(
            f"cannot start the Discord bot: {' and '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} not set (environment or .env)"
        )
    return BotConfig(token=token, channel_id=channel_id)


def bot_intents() -> discord.Intents:
    """``guilds`` only: enough for slash commands and the channel cache, nothing privileged."""
    intents = discord.Intents.none()
    intents.guilds = True
    return intents


# --- collaborators --------------------------------------------------------------------------


class _ChannelSource(Protocol):
    def get_channel(self, id: int, /) -> Any: ...

    async def fetch_channel(self, channel_id: int, /) -> Any: ...


def missing_broadcast_permissions(channel: Any) -> list[str]:
    """Which of :data:`BROADCAST_PERMISSIONS` the bot lacks in ``channel``.

    Empty when the permissions cannot be resolved (a DM channel, or a guild whose member
    cache is not filled yet): the send itself then reports the truth.
    """
    guild = getattr(channel, "guild", None)
    me = getattr(guild, "me", None)
    resolve = getattr(channel, "permissions_for", None)
    if me is None or not callable(resolve):
        return []
    try:
        permissions = resolve(me)
    except Exception:  # pragma: no cover - defensive: an unexpected channel type
        return []
    return [
        label for field, label in BROADCAST_PERMISSIONS if not getattr(permissions, field, True)
    ]


class ChannelSender:
    """Sends embeds to the broadcast channel (resolved from the cache, else fetched)."""

    def __init__(self, client: _ChannelSource, channel_id: int) -> None:
        self._client = client
        self.channel_id = channel_id

    async def channel(self) -> discord.abc.Messageable:
        channel = self._client.get_channel(self.channel_id)
        if channel is None:
            channel = await self._client.fetch_channel(self.channel_id)
        if not callable(getattr(channel, "send", None)):
            raise DeliveryBlocked(
                f"DISCORD_BROADCAST_CHANNEL_ID {self.channel_id} is a "
                f"{type(channel).__name__}, which cannot receive messages"
            )
        return cast(discord.abc.Messageable, channel)

    async def send(self, embed: discord.Embed) -> None:
        channel = await self.channel()
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


class DDragonContextProvider:
    """Embed context with the current Data Dragon patch and champion keys.

    Calls return the last known context immediately (Discord gives interactions three
    seconds) and refresh it in the background every :data:`CONTEXT_REFRESH_SECONDS`.
    Until the first successful refresh, and whenever Data Dragon is unreachable, the
    context uses ``ddragon.FALLBACK_VERSION`` and the match-v5 champion names.
    """

    def __init__(self, settings: Settings, ddragon: DDragon) -> None:
        self._settings = settings
        self._ddragon = ddragon
        self._current = EmbedContext.from_settings(settings)
        self._refreshed_at: float | None = None
        self._task: asyncio.Task[EmbedContext] | None = None
        self._warned: set[str] = set()

    @property
    def current(self) -> EmbedContext:
        return self._current

    def _warn_once(self, what: str, exc: BaseException) -> None:
        level = logging.DEBUG if what in self._warned else logging.WARNING
        self._warned.add(what)
        logger.log(level, "Data Dragon %s unavailable (%r); using fallbacks", what, exc)

    async def refresh(self) -> EmbedContext:
        """Fetch the latest version and champion map now (never raises)."""
        version = self._current.ddragon_version
        champion_keys = dict(self._current.champion_keys)
        try:
            version = await asyncio.wait_for(
                self._ddragon.latest_version(), DDRAGON_TIMEOUT_SECONDS
            )
        except Exception as exc:
            self._warn_once("version", exc)
        try:
            champion_keys = await asyncio.wait_for(
                self._ddragon.champion_map(), DDRAGON_TIMEOUT_SECONDS
            )
        except Exception as exc:
            self._warn_once("champion map", exc)
        self._current = EmbedContext.from_settings(
            self._settings, ddragon_version=version, champion_keys=champion_keys
        )
        self._refreshed_at = time.monotonic()
        return self._current

    async def __call__(self) -> EmbedContext:
        stale = (
            self._refreshed_at is None
            or time.monotonic() - self._refreshed_at >= CONTEXT_REFRESH_SECONDS
        )
        if stale and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self.refresh(), name="hextrack-ddragon-refresh")
        return self._current

    async def aclose(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


# --- /lp --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LpReply:
    """What ``/lp`` answers: an embed, or a short (ephemeral) message."""

    content: str | None = None
    embed: discord.Embed | None = None
    ephemeral: bool = False

    def send_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"ephemeral": self.ephemeral}
        if self.content is not None:
            kwargs["content"] = self.content
        if self.embed is not None:
            kwargs["embed"] = self.embed
        return kwargs


async def lp_reply(
    session_factory: async_sessionmaker[AsyncSession],
    ctx: EmbedContext,
    name: str,
    *,
    season_start: datetime | None = None,
) -> LpReply:
    """Answer for ``/lp name`` (database only).

    ``season_start`` makes the reply use the website's rule for "this is their rank now":
    a snapshot from before the season, or one league-v4 has since stopped returning, reads
    as unranked instead of as a stale tier.
    """
    async with session_factory() as session:
        summoner = await resolve_tracked(session, name)
        if summoner is None:
            return LpReply(content=NOT_TRACKED, ephemeral=True)
        snapshot = await latest_rank(session, summoner.puuid, season_start=season_start)
    if snapshot is None and summoner.last_refreshed_at is None:
        return LpReply(content=NO_PLAYER_DATA, ephemeral=True)
    rank = (
        RankLine(
            queue_type=snapshot.queue_type,
            tier=snapshot.tier,
            rank=snapshot.rank,
            lp=snapshot.lp,
            wins=snapshot.wins,
            losses=snapshot.losses,
            taken_at=snapshot.taken_at,
        )
        if snapshot is not None
        else None
    )
    player = PlayerRef(
        puuid=summoner.puuid,
        game_name=summoner.game_name,
        tag_line=summoner.tag_line,
        profile_icon_id=summoner.profile_icon_id,
    )
    return LpReply(embed=player_info(player, rank, ctx))


async def lp_choices(
    session_factory: async_sessionmaker[AsyncSession], current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete choices for ``/lp``: tracked ``Name#TAG`` values matching ``current``."""
    async with session_factory() as session:
        rows = await search_roster(session, current)
    choices: list[app_commands.Choice[str]] = []
    for row in rows:
        riot_id = format_riot_id(row.game_name, row.tag_line)
        value = riot_id if len(riot_id) <= CHOICE_MAX_LENGTH else row.puuid
        choices.append(app_commands.Choice(name=riot_id[:CHOICE_MAX_LENGTH], value=value))
    return choices


# --- cog --------------------------------------------------------------------------------------


class HexTrackCog(commands.Cog, name="HexTrack"):
    """``/lp`` plus the consumer and daily-post loops."""

    def __init__(self, bot: HexTrackBot) -> None:
        self.bot = bot
        settings = bot.settings
        post_time = dtime(hour=settings.discord_daily_post_hour, tzinfo=settings.discord_zoneinfo)
        self.consume_loop: tasks.Loop[Any] = tasks.loop(seconds=CONSUME_INTERVAL_SECONDS)(
            self.consume_tick
        )
        self.consume_loop.before_loop(self._before_consume)
        self.daily_loop: tasks.Loop[Any] = tasks.loop(time=post_time)(self.daily_tick)
        self.daily_loop.before_loop(self._before_daily)

    async def cog_load(self) -> None:
        self.consume_loop.start()
        self.daily_loop.start()

    async def cog_unload(self) -> None:
        loops = (self.consume_loop, self.daily_loop)
        for loop in loops:
            loop.cancel()
        # A cancelled loop still finishes the embed it is posting and records that it went
        # out (see consumer.run_to_completion). Wait for that here, because ``Bot.close()``
        # unloads the cogs before it closes the HTTP session under them.
        running = [
            task for loop in loops if (task := loop.get_task()) is not None and not task.done()
        ]
        if running:
            _, pending = await asyncio.wait(running, timeout=SHUTDOWN_GRACE_SECONDS)
            if pending:
                logger.warning(
                    "%d bot loop(s) did not finish within %.0fs of the stop request",
                    len(pending),
                    SHUTDOWN_GRACE_SECONDS,
                )

    # --- consumer -----------------------------------------------------------------------
    async def _before_consume(self) -> None:
        await self.bot.wait_until_ready()
        try:
            await self.bot.consumer.skip_stale()
        except Exception:
            logger.exception("could not skip stale bot events")

    async def consume_tick(self) -> None:
        """One outbox batch plus the heartbeat. Never raises (that would stop the loop)."""
        error: str | None = None
        try:
            result = await self.bot.consumer.process_batch()
            if result.sent or result.gave_up or result.failed or result.stale:
                logger.info(
                    "bot events: %d sent, %d silent, %d failed, %d dropped, %d too old",
                    result.sent,
                    result.silent,
                    result.failed,
                    result.gave_up,
                    result.stale,
                )
        except Exception as exc:
            logger.exception("processing bot events failed")
            error = f"{type(exc).__name__}: {exc}"
        # A channel that refuses every post is not an exception here, but it does mean the
        # bot is not delivering: say so instead of reporting a healthy bot.
        await self.bot.write_heartbeat(last_error=error or self.bot.consumer.blocked_reason)

    # --- daily leaderboard --------------------------------------------------------------
    async def _before_daily(self) -> None:
        await self.bot.wait_until_ready()
        await self.post_daily(scheduled=False)

    async def daily_tick(self) -> None:
        await self.post_daily(scheduled=True)

    async def post_daily(self, *, scheduled: bool) -> bool:
        """Post today's leaderboard if it is due, retrying transient failures."""
        poster = self.bot.daily_poster
        for attempt in range(1, DAILY_RETRIES + 1):
            try:
                now = poster.scheduled_now() if scheduled else None
                return await poster.post_if_due(now=now)
            except Exception as exc:
                if is_delivery_blocked(exc):
                    # Retrying in a minute cannot help; publish why nothing is arriving.
                    self.bot.consumer.report_blocked(f"{type(exc).__name__}: {exc}")
                    logger.error(
                        "cannot post the daily leaderboard: %s. Check "
                        "DISCORD_BROADCAST_CHANNEL_ID and the bot's permissions there",
                        exc,
                    )
                    return False
                logger.exception(
                    "daily leaderboard post failed (attempt %d/%d)", attempt, DAILY_RETRIES
                )
                if attempt < DAILY_RETRIES:
                    await asyncio.sleep(DAILY_RETRY_DELAY_SECONDS)
        return False

    # --- /lp ------------------------------------------------------------------------------
    async def _lp_answer(self, name: str) -> LpReply:
        try:
            ctx = await self.bot.context_provider()
            return await lp_reply(
                self.bot.session_factory, ctx, name, season_start=self.bot.settings.season_start
            )
        except Exception:
            logger.exception("/lp failed for %r", name)
            return LpReply(content=LP_FAILED, ephemeral=True)

    @app_commands.command(name=LP_COMMAND, description=LP_DESCRIPTION)
    @app_commands.describe(name=LP_NAME_DESCRIPTION)
    async def lp(self, interaction: discord.Interaction, name: str) -> None:
        # Discord drops interactions that are not answered within 3 seconds: answer directly
        # when the database is quick, otherwise acknowledge first and follow up.
        answer = asyncio.ensure_future(self._lp_answer(name))
        try:
            reply = await asyncio.wait_for(asyncio.shield(answer), LP_DEFER_AFTER_SECONDS)
        except TimeoutError:
            await interaction.response.defer(thinking=True)
            reply = await answer
            await interaction.followup.send(**reply.send_kwargs())
            return
        await interaction.response.send_message(**reply.send_kwargs())

    @lp.autocomplete("name")
    async def lp_name_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            return await lp_choices(self.bot.session_factory, current)
        except Exception:
            logger.exception("/lp autocomplete failed for %r", current)
            return []


# --- bot --------------------------------------------------------------------------------------


class HexTrackBot(commands.Bot):
    """``commands.Bot`` wired to the database, the broadcast channel and Data Dragon."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        sender: EmbedSender | None = None,
        context_provider: ContextProvider | None = None,
        sync_commands: bool = True,
    ) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=bot_intents(),
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.settings = settings
        self.session_factory = session_factory
        if sender is None:
            sender = ChannelSender(self, bot_config(settings).channel_id)
        self.sender: EmbedSender = sender
        self.context_provider: ContextProvider = context_provider or static_context_provider(
            settings
        )
        self.consumer = EventConsumer(session_factory, settings, sender, self.context_provider)
        self.daily_poster = DailyLeaderboardPoster(session_factory, settings, sender)
        self._sync_commands = sync_commands

    async def setup_hook(self) -> None:
        await self.add_cog(HexTrackCog(self))
        if self._sync_commands:
            try:
                synced = await self.tree.sync()
                logger.info("synced %d application command(s)", len(synced))
            except discord.HTTPException as exc:
                logger.warning("could not sync application commands: %s", exc)

    async def on_ready(self) -> None:
        logger.info(
            "Discord bot connected as %s; broadcasting to channel %s",
            self.user,
            self.settings.discord_broadcast_channel_id,
        )
        problem = await self.check_broadcast_channel()
        self.consumer.report_blocked(problem)
        if problem is not None:
            logger.error(
                "the broadcast channel is not usable: %s. Events stay queued (and are "
                "dropped once they are six hours old) until this is fixed",
                problem,
            )
        await self.write_heartbeat(last_error=problem)

    async def check_broadcast_channel(self) -> str | None:
        """Why the broadcast channel cannot be posted to, or None when it looks fine.

        Runs when the bot connects, so a wrong ``DISCORD_BROADCAST_CHANNEL_ID`` or a missing
        Send Messages / Embed Links permission is reported at once (in the log and in the
        heartbeat ``/health`` reads) instead of after every event has quietly burnt its
        retries. Transient Discord errors are not treated as configuration problems.
        """
        channel_id = self.settings.discord_broadcast_channel_id
        if channel_id is None:
            return "DISCORD_BROADCAST_CHANNEL_ID is not set"
        try:
            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        except discord.NotFound:
            return f"there is no channel {channel_id} (check DISCORD_BROADCAST_CHANNEL_ID)"
        except discord.Forbidden:
            return (
                f"channel {channel_id} is not visible to the bot (invite it to that server "
                "and give it View Channel)"
            )
        except discord.HTTPException as exc:  # Discord itself is having a moment
            logger.warning("could not check the broadcast channel %s: %s", channel_id, exc)
            return None
        if not callable(getattr(channel, "send", None)):
            return (
                f"channel {channel_id} is a {type(channel).__name__}, which cannot receive messages"
            )
        missing = missing_broadcast_permissions(channel)
        if missing:
            return f"the bot is missing {', '.join(missing)} in channel {channel_id}"
        return None

    def heartbeat(self, *, running: bool = True, last_error: str | None = None) -> dict[str, Any]:
        return {
            "running": running,
            "heartbeat_at": datetime.now(UTC).isoformat(),
            "connected": running and self.is_ready() and not self.is_closed(),
            "user": str(self.user) if self.user is not None else None,
            "last_error": last_error,
        }

    async def write_heartbeat(self, *, running: bool = True, last_error: str | None = None) -> None:
        """Best effort: a database hiccup must not take the bot down."""
        try:
            async with session_scope(self.session_factory) as session:
                await put_state(
                    session, BOT_STATE_KEY, self.heartbeat(running=running, last_error=last_error)
                )
        except Exception as exc:
            logger.warning("could not write the bot heartbeat: %s", exc)


# --- entrypoint -------------------------------------------------------------------------------


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop, stop: asyncio.Event
) -> list[signal.Signals]:
    installed: list[signal.Signals] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            continue
        installed.append(sig)
    return installed


async def run_bot(settings: Settings) -> None:
    """Connect to Discord, consume ``bot_events``, post the daily leaderboard at
    ``discord_daily_post_hour`` in ``discord_tz`` and serve ``/lp``. Runs until cancelled
    or SIGINT/SIGTERM. Raises :class:`BotNotConfigured` without a token."""
    config = bot_config(settings)
    engine = make_async_engine(settings, pool_size=5, max_overflow=5)
    session_factory = make_session_factory(engine)
    ddragon = DDragon()
    assets = DDragonContextProvider(settings, ddragon)
    bot = HexTrackBot(settings, session_factory, context_provider=assets)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    installed = _install_signal_handlers(loop, stop)
    try:
        await assets.refresh()
        async with bot:
            runner = asyncio.create_task(bot.start(config.token), name="hextrack-discord-bot")
            stopper = asyncio.create_task(stop.wait(), name="hextrack-bot-stop")
            try:
                await asyncio.wait({runner, stopper}, return_when=asyncio.FIRST_COMPLETED)
                if not runner.done():
                    logger.info("stopping the Discord bot")
                    await bot.close()
                await runner
            except discord.LoginFailure as exc:
                raise BotNotConfigured(
                    "Discord rejected DISCORD_TOKEN; check the bot token in the developer portal"
                ) from exc
            finally:
                stopper.cancel()
                if not runner.done():
                    runner.cancel()
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)
        await bot.write_heartbeat(running=False)
        await assets.aclose()
        await ddragon.aclose()
        await engine.dispose()
