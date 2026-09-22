"""Outbox consumer and daily leaderboard poster.

:class:`EventConsumer` drains ``bot_events`` (written by ingestion) into the broadcast
channel:

* a batch handles up to 20 pending rows, **one transaction per event**: the row is claimed
  with ``FOR UPDATE SKIP LOCKED`` (oldest first), so a second consumer never sends the same
  event, and the outcome is committed before the next one is claimed. Sending and recording
  the send run under :func:`run_to_completion`, so a shutdown between the two cannot happen:
  a stopped bot never re-posts embeds it already delivered;
* ``new_match`` rows, and ``bad_game`` rows while ``HEXTRACK_BAD_GAME_EMBEDS`` is off, are
  marked processed without a post;
* a failed send increments ``attempts`` and records ``last_error``; after
  :data:`MAX_ATTEMPTS` the event is given up (``processed_at`` set, error kept). The rest of
  the batch waits for the next tick behind an exponential back-off, which keeps order and
  avoids burning every event's attempts during a short Discord outage;
* an error that says the *channel* cannot be posted to at all (wrong id, no access, missing
  Send Messages / Embed Links; see :func:`is_delivery_blocked`) is not the event's fault: it
  keeps its attempts, the batch stops behind the back-off, and the reason is published as
  :attr:`EventConsumer.blocked_reason` so the bot heartbeat and ``/health`` show it instead
  of reporting a healthy bot that silently drops everything;
* payloads that can never render (unknown kind, missing keys) are given up immediately;
* events older than six hours are marked processed without being sent, so a bot that was
  down (or a channel that was misconfigured) does not flood the channel with old news:
  :meth:`EventConsumer.skip_stale` does that in bulk at startup, and every claimed event is
  checked again before it is rendered.

Invariant: ``processed_at IS NOT NULL AND last_error IS NULL`` means "delivered" (or
consumed silently); a non-null ``last_error`` on a processed row says why it was dropped.

:class:`DailyLeaderboardPoster` posts the season leaderboard once per local day. The date
of the last post lives in ``app_state["bot_daily"]`` and is checked under a row lock, so
restarts and duplicate processes never double-post; the post and that date are written
under :func:`run_to_completion` for the same reason the consumer is.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Final, Protocol

import discord
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.bot import embeds
from hextrack.bot.embeds import (
    EmbedContext,
    GameEvent,
    LeaderboardEntry,
    PlayerRef,
    TierChangeEvent,
)
from hextrack.bot.queries import (
    ai_scores,
    get_summoners,
    lock_state,
    put_state,
    season_lp_deltas,
)
from hextrack.config import Settings
from hextrack.db.engine import session_scope
from hextrack.db.models import BotEvent, Summoner

logger = logging.getLogger(__name__)

#: How often the bot polls the outbox.
CONSUME_INTERVAL_SECONDS: Final = 10.0
BATCH_SIZE: Final = 20
MAX_ATTEMPTS: Final = 5
#: Events older than this when the bot starts are dropped unsent.
STALE_AFTER: Final = timedelta(hours=6)
#: Back-off after a failed send: 10 s, 20 s, 40 s, ... capped at 5 minutes.
RETRY_BACKOFF_SECONDS: Final = 10.0
MAX_BACKOFF_SECONDS: Final = 300.0
#: app_state key: {"last_post_date": "YYYY-MM-DD" (local), "posted_at": ISO, "season_year"}.
DAILY_STATE_KEY: Final = "bot_daily"
#: A scheduled daily tick that fires this close before the post hour counts as on time.
DAILY_EARLY_TOLERANCE: Final = timedelta(seconds=60)

STALE_NOTE: Final = "skipped: older than 6h when the bot started"
#: Note on an event that aged out while it was waiting to be posted.
STALE_SEND_NOTE: Final = "skipped: older than 6h before it could be posted"
MAX_ERROR_LENGTH: Final = 1000

SILENT_KINDS: Final = frozenset({"new_match"})
TIER_KINDS: Final = frozenset({"tier_up", "tier_down"})
GAME_KINDS: Final = frozenset({"great_game", "bad_game", "new_match"})


class EmbedSender(Protocol):
    """Where embeds go: the broadcast channel in production, a list in tests."""

    async def send(self, embed: discord.Embed) -> None: ...


ContextProvider = Callable[[], Awaitable[EmbedContext]]


class InvalidEvent(ValueError):
    """The event can never be rendered (unknown kind or malformed payload)."""


class DeliveryBlocked(Exception):
    """The broadcast channel itself cannot take posts (not a text channel, not visible).

    Raised by the sender; :func:`is_delivery_blocked` also covers what Discord returns.
    """


async def run_to_completion[T](awaitable: Awaitable[T]) -> T:
    """Await ``awaitable`` even if the calling task is cancelled meanwhile.

    A cancellation arriving while it runs is re-raised once it has finished, so a section
    that must not be cut in half (sending an embed and recording that it was sent) survives
    a SIGINT/SIGTERM or a ``tasks.Loop.cancel()`` mid-batch.
    """
    task = asyncio.ensure_future(awaitable)
    interrupted = False
    while not task.done():
        try:
            await asyncio.wait({task})  # never cancels the task it waits for
        except asyncio.CancelledError:
            interrupted = True
    if interrupted:
        if not task.cancelled() and task.exception() is not None:
            logger.warning("interrupted while finishing %r", task, exc_info=task.exception())
        raise asyncio.CancelledError
    return task.result()


def static_context_provider(settings: Settings) -> ContextProvider:
    """Provider without Data Dragon lookups (fallback patch, match-v5 champion names)."""
    ctx = EmbedContext.from_settings(settings)

    async def provide() -> EmbedContext:
        return ctx

    return provide


def _error_text(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".strip()
    return text[:MAX_ERROR_LENGTH]


def _is_permanent_send_error(exc: Exception) -> bool:
    """Discord rejected the message itself (400 Bad Request): retrying cannot help."""
    return isinstance(exc, discord.HTTPException) and exc.status == 400


def is_delivery_blocked(exc: Exception) -> bool:
    """The broadcast channel, not this event, is the problem.

    ``DISCORD_BROADCAST_CHANNEL_ID`` names a channel that does not exist or that the bot
    cannot see (404), one it may not post embeds in (403), or something that cannot receive
    messages at all. Retrying the event cannot help until the configuration changes, and
    spending its attempts would throw away news that is still fine to post.
    """
    return isinstance(exc, DeliveryBlocked | discord.NotFound | discord.Forbidden)


# --- event parsing and rendering ----------------------------------------------------------

ParsedEvent = TierChangeEvent | GameEvent


def parse_event(kind: str, payload: dict[str, object]) -> ParsedEvent:
    """Validate a payload for its kind. Raises :class:`InvalidEvent`."""
    try:
        if kind in TIER_KINDS:
            return TierChangeEvent.model_validate(payload)
        if kind in GAME_KINDS:
            return GameEvent.model_validate(payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'payload'}: {err['msg']}"
            for err in exc.errors()
        )
        raise InvalidEvent(f"invalid {kind} payload: {details}") from exc
    raise InvalidEvent(f"unknown event kind {kind!r}")


def player_ref(event: ParsedEvent, summoner: Summoner | None) -> PlayerRef:
    """Current name and icon from ``summoners`` when known, else the payload snapshot."""
    if summoner is not None:
        return PlayerRef(
            puuid=summoner.puuid,
            game_name=summoner.game_name,
            tag_line=summoner.tag_line,
            profile_icon_id=summoner.profile_icon_id,
        )
    return PlayerRef(puuid=event.puuid, game_name=event.game_name, tag_line=event.tag_line)


def render_event(
    kind: str, event: ParsedEvent, player: PlayerRef, ctx: EmbedContext
) -> discord.Embed:
    """Embed for a postable event kind."""
    if kind == "tier_up" and isinstance(event, TierChangeEvent):
        return embeds.tier_up(event, player, ctx)
    if kind == "tier_down" and isinstance(event, TierChangeEvent):
        return embeds.tier_down(event, player, ctx)
    if kind == "great_game" and isinstance(event, GameEvent):
        return embeds.great_game(event, player, ctx)
    if kind == "bad_game" and isinstance(event, GameEvent):
        return embeds.bad_game(event, player, ctx)
    raise InvalidEvent(f"event kind {kind!r} has no embed")


# --- claiming -----------------------------------------------------------------------------


async def claim_events(
    session: AsyncSession, *, limit: int = BATCH_SIZE, max_attempts: int = MAX_ATTEMPTS
) -> list[BotEvent]:
    """Lock up to ``limit`` pending events, oldest first, skipping rows another
    transaction holds. The locks last until the caller's transaction ends."""
    rows = await session.scalars(
        select(BotEvent)
        .where(BotEvent.processed_at.is_(None), BotEvent.attempts < max_attempts)
        .order_by(BotEvent.created_at, BotEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(rows)


@dataclass(slots=True)
class BatchResult:
    """What one :meth:`EventConsumer.process_batch` call did."""

    claimed: int = 0
    sent: int = 0
    silent: int = 0
    #: Send failed; the event stays pending for a retry.
    failed: int = 0
    #: Dropped: attempts exhausted, or the payload can never render.
    gave_up: int = 0
    #: Too old to post (see :data:`STALE_AFTER`); marked processed without a send.
    stale: int = 0
    #: The call returned early because a previous failure is still backing off.
    backing_off: bool = False
    #: Why the broadcast channel refused the post (see :func:`is_delivery_blocked`).
    blocked: str | None = None


@dataclass(slots=True)
class _Work:
    row: BotEvent
    event: ParsedEvent | None = None
    error: InvalidEvent | None = None
    silent: bool = False


@dataclass(slots=True)
class _Batch:
    """Scratch shared by the events of one batch: the embed context is fetched once."""

    context: EmbedContext | None = None

    async def embed_context(self, provider: ContextProvider) -> EmbedContext:
        if self.context is None:
            self.context = await provider()
        return self.context


class EventConsumer:
    """Turns pending ``bot_events`` into channel posts (see the module docstring)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        sender: EmbedSender,
        context_provider: ContextProvider | None = None,
        *,
        batch_size: int = BATCH_SIZE,
        max_attempts: int = MAX_ATTEMPTS,
        stale_after: timedelta = STALE_AFTER,
        retry_backoff_seconds: float = RETRY_BACKOFF_SECONDS,
        max_backoff_seconds: float = MAX_BACKOFF_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if batch_size < 1 or max_attempts < 1:
            raise ValueError("batch_size and max_attempts must be positive")
        self._factory = session_factory
        self._settings = settings
        self._sender = sender
        self._context = context_provider or static_context_provider(settings)
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.stale_after = stale_after
        self._backoff = max(0.0, retry_backoff_seconds)
        self._max_backoff = max(self._backoff, max_backoff_seconds)
        self._clock = clock
        self._consecutive_failures = 0
        self._resume_at: float | None = None
        self._blocked_reason: str | None = None

    @property
    def backing_off(self) -> bool:
        return self._resume_at is not None and self._clock() < self._resume_at

    @property
    def blocked_reason(self) -> str | None:
        """Why nothing can be posted at the moment (channel id or permissions), or None.

        The bot publishes this in its heartbeat, so ``/health`` reports a bot that cannot
        deliver instead of a healthy one. Cleared by the next successful send.
        """
        return self._blocked_reason

    def report_blocked(self, reason: str | None) -> None:
        """Record (or clear, with None) a channel problem noticed outside a send, such as
        the broadcast-channel check the bot runs when it connects."""
        self._blocked_reason = reason

    def _silent(self, kind: str) -> bool:
        return kind in SILENT_KINDS or (kind == "bad_game" and not self._settings.bad_game_embeds)

    def _record_send_failure(self) -> None:
        self._consecutive_failures += 1
        delay = min(self._backoff * 2 ** (self._consecutive_failures - 1), self._max_backoff)
        self._resume_at = self._clock() + delay if delay > 0 else None

    def _record_send_success(self) -> None:
        self._consecutive_failures = 0
        self._resume_at = None
        self._blocked_reason = None

    def _record_blocked(self, exc: Exception) -> str:
        """A send failed because of the channel itself: back off and publish the reason."""
        reason = _error_text(exc)
        if reason != self._blocked_reason:
            logger.error(
                "cannot post to Discord channel %s: %s. Events stay queued until this is "
                "fixed: check DISCORD_BROADCAST_CHANNEL_ID and the bot's View Channel, "
                "Send Messages and Embed Links permissions there",
                self._settings.discord_broadcast_channel_id,
                exc,
            )
        else:
            logger.warning("the broadcast channel still refuses posts: %s", exc)
        self._blocked_reason = reason
        self._record_send_failure()
        return reason

    def _is_stale(self, row: BotEvent, now: datetime) -> bool:
        return row.created_at < now - self.stale_after

    async def skip_stale(self, *, now: datetime | None = None) -> int:
        """Mark pending events older than ``stale_after`` processed without sending them.
        Returns how many were skipped."""
        now = now or datetime.now(UTC)
        async with session_scope(self._factory) as session:
            result = await session.execute(
                update(BotEvent)
                .where(
                    BotEvent.processed_at.is_(None),
                    BotEvent.created_at < now - self.stale_after,
                )
                .values(processed_at=now, last_error=STALE_NOTE)
                .returning(BotEvent.id)
                .execution_options(synchronize_session=False)
            )
            skipped = len(result.scalars().all())
        if skipped:
            logger.info("skipped %d stale bot event(s) older than %s", skipped, self.stale_after)
        return skipped

    async def process_batch(self, *, now: datetime | None = None) -> BatchResult:
        """Deliver up to ``batch_size`` pending events, oldest first, one transaction per
        event, so a bot that stops mid-batch never re-posts what it already sent."""
        result = BatchResult()
        if self.backing_off:
            result.backing_off = True
            return result
        batch = _Batch()
        for _ in range(self.batch_size):
            if not await self._process_one(batch, result, now):
                break
        return result

    async def _process_one(self, batch: _Batch, result: BatchResult, now: datetime | None) -> bool:
        """Claim, handle and commit the oldest pending event.

        Returns False when the batch should end: nothing is pending, or the event's outcome
        holds the rest back (a failed send).
        """
        async with self._factory() as session:
            rows = await claim_events(session, limit=1, max_attempts=self.max_attempts)
            if not rows:
                return False
            result.claimed += 1
            item = self._prepare(rows[0])
            stamp = now or datetime.now(UTC)
            summoners: dict[str, Summoner] = {}
            ctx: EmbedContext | None = None
            if item.event is not None and not item.silent and not self._is_stale(item.row, stamp):
                summoners = await get_summoners(session, {item.event.puuid})
                await self._fill_ai_scores(session, item)
                ctx = await batch.embed_context(self._context)
            # A cancellation must not land between the send and the commit that records it.
            return await run_to_completion(
                self._deliver(session, item, summoners, ctx, stamp, result)
            )

    async def _deliver(
        self,
        session: AsyncSession,
        item: _Work,
        summoners: dict[str, Summoner],
        ctx: EmbedContext | None,
        now: datetime,
        result: BatchResult,
    ) -> bool:
        stop = await self._handle(item, summoners, ctx, now, result)
        await session.commit()
        return not stop

    def _prepare(self, row: BotEvent) -> _Work:
        item = _Work(row=row)
        if self._silent(row.kind):
            item.silent = True
        else:
            try:
                item.event = parse_event(row.kind, dict(row.payload or {}))
            except InvalidEvent as exc:
                item.error = exc
        return item

    async def _fill_ai_scores(self, session: AsyncSession, item: _Work) -> None:
        """An event enqueued before the match was scored carries ``ai_score: null``; use the
        stored score when the participant row has one by now."""
        event = item.event
        if not isinstance(event, GameEvent) or event.ai_score is not None:
            return
        scores = await ai_scores(session, [(event.match_id, event.puuid)])
        score = scores.get((event.match_id, event.puuid))
        if score is not None:
            item.event = event.model_copy(update={"ai_score": score})

    async def _handle(
        self,
        item: _Work,
        summoners: dict[str, Summoner],
        ctx: EmbedContext | None,
        now: datetime,
        result: BatchResult,
    ) -> bool:
        """Process one claimed event. Returns True when the rest of the batch should wait."""
        row = item.row
        if item.silent:
            row.processed_at = now
            row.last_error = None
            result.silent += 1
            return False
        if self._is_stale(row, now):
            # Waited out a Discord outage or a misconfigured channel: post no old news.
            row.processed_at = now
            row.last_error = STALE_SEND_NOTE
            result.stale += 1
            logger.info(
                "skipping bot event %s (%s): older than %s", row.id, row.kind, self.stale_after
            )
            return False
        if item.error is not None or item.event is None or ctx is None:
            self._give_up(row, item.error or InvalidEvent("event could not be parsed"), now)
            result.gave_up += 1
            return False
        player = player_ref(item.event, summoners.get(item.event.puuid))
        try:
            embed = render_event(row.kind, item.event, player, ctx)
        except Exception as exc:
            # Rendering is deterministic: an event that fails once always fails, so retrying
            # would only block the queue behind it.
            logger.exception("rendering bot event %s (%s) failed", row.id, row.kind)
            self._give_up(row, exc, now)
            result.gave_up += 1
            return False

        try:
            await self._sender.send(embed)
        except Exception as exc:
            if is_delivery_blocked(exc):
                # The channel is unusable, not this event: keep its attempts for later.
                result.blocked = row.last_error = self._record_blocked(exc)
                return True
            row.attempts += 1
            row.last_error = _error_text(exc)
            if _is_permanent_send_error(exc):
                row.processed_at = now
                result.gave_up += 1
                logger.error("bot event %s (%s) rejected by Discord: %s", row.id, row.kind, exc)
                return False
            self._record_send_failure()
            if row.attempts >= self.max_attempts:
                row.processed_at = now
                result.gave_up += 1
                logger.error(
                    "giving up on bot event %s (%s) after %d attempts: %s",
                    row.id,
                    row.kind,
                    row.attempts,
                    exc,
                )
            else:
                result.failed += 1
                logger.warning(
                    "sending bot event %s (%s) failed (attempt %d/%d): %s",
                    row.id,
                    row.kind,
                    row.attempts,
                    self.max_attempts,
                    exc,
                )
            return True

        row.processed_at = now
        row.last_error = None
        result.sent += 1
        self._record_send_success()
        return False

    def _give_up(self, row: BotEvent, exc: Exception, now: datetime) -> None:
        row.attempts += 1
        row.processed_at = now
        row.last_error = _error_text(exc)
        logger.error("dropping bot event %s (%s): %s", row.id, row.kind, exc)


# --- daily leaderboard --------------------------------------------------------------------


def daily_post_due(now_local: datetime, last_post_date: date | None, post_hour: int) -> bool:
    """LPBot ``tryDailyTrigger``: at or after the post hour, once per local day."""
    today = now_local.date()
    return now_local.hour >= post_hour and (last_post_date is None or last_post_date < today)


def _parse_date(value: object) -> date | None:
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class DailyLeaderboardPoster:
    """Posts the season-to-date solo LP leaderboard once per day (see module docstring)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        sender: EmbedSender,
    ) -> None:
        self._factory = session_factory
        self._settings = settings
        self._sender = sender

    @property
    def season_year(self) -> int:
        return self._settings.season_start.astimezone(self._settings.discord_zoneinfo).year

    def scheduled_now(self, now: datetime | None = None) -> datetime:
        """The time to use for a scheduled tick: timers can fire a hair early, so a tick
        within :data:`DAILY_EARLY_TOLERANCE` before the post hour is treated as on time."""
        now = now or datetime.now(UTC)
        tz = self._settings.discord_zoneinfo
        local = now.astimezone(tz)
        post_time = dtime(hour=self._settings.discord_daily_post_hour)
        # Tomorrow's slot matters for a midnight post hour (fired at 23:59:59.9).
        for day in (local.date(), local.date() + timedelta(days=1)):
            target = datetime.combine(day, post_time, tzinfo=tz)
            if timedelta(0) < target - local <= DAILY_EARLY_TOLERANCE:
                return target.astimezone(UTC)
        return now

    async def build_embed(self, session: AsyncSession, *, now: datetime) -> discord.Embed:
        deltas = await season_lp_deltas(session, since=self._settings.season_start, until=now)
        return embeds.daily_leaderboard(
            [LeaderboardEntry(name=d.riot_id, lp_delta=d.delta) for d in deltas],
            season_year=self.season_year,
            timestamp=now,
        )

    async def post_if_due(self, *, now: datetime | None = None, force: bool = False) -> bool:
        """Post unless today's leaderboard is already out (or it is before the post hour).
        ``force`` posts regardless. Returns True when a post was sent."""
        now = now or datetime.now(UTC)
        local = now.astimezone(self._settings.discord_zoneinfo)
        async with self._factory() as session:
            state = await lock_state(session, DAILY_STATE_KEY)
            last = _parse_date(state.get("last_post_date"))
            if not force and not daily_post_due(
                local, last, self._settings.discord_daily_post_hour
            ):
                await session.rollback()
                return False
            embed = await self.build_embed(session, now=now)
            # Posting and recording the date are one step: a shutdown in between would make
            # the catch-up post at the next start repeat today's leaderboard.
            await run_to_completion(self._send_and_record(session, embed, now=now, local=local))
        logger.info("posted the daily leaderboard for %s", local.date().isoformat())
        return True

    async def _send_and_record(
        self, session: AsyncSession, embed: discord.Embed, *, now: datetime, local: datetime
    ) -> None:
        await self._sender.send(embed)
        await put_state(
            session,
            DAILY_STATE_KEY,
            {
                "last_post_date": local.date().isoformat(),
                "posted_at": now.isoformat(),
                "season_year": self.season_year,
            },
        )
        await session.commit()
