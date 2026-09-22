"""Discord embed builders: pure functions, no database or network access.

Ported from LPBot.cpp (``playerInfoEmbed``, ``tierUpEmbed``, ``tierDownEmbed``,
``badGameEmbed``, ``greatGameEmbed``, ``dailyEmbed``). The copy and the ANSI colouring are
kept; the differences are:

* author links go to the HexTrack summoner page (``{public_url}/summoner/na/Name-TAG``)
  instead of op.gg;
* profile and champion icons come from Data Dragon for the current patch;
* the ``AI Score: NN%`` footer is left out when the game has not been scored (LPBot
  printed ``0%``);
* the rank emblem image is attached only when ``HEXTRACK_RANK_ICON_BASE`` is set;
* the daily leaderboard receives LP deltas computed with :func:`hextrack.rank.rank_value`,
  so promotions into Master+ count as the LP actually gained (LPBot added a phantom
  division);
* a tier-down embed is red (LPBot reused the tier-up green) and a great game is green
  (LPBot reused the bad-game red), so the colour matches the news.

Event payloads (see :mod:`hextrack.ingest.events`) are validated into
:class:`TierChangeEvent` / :class:`GameEvent` before they reach a builder.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from urllib.parse import quote

import discord
from pydantic import BaseModel, ConfigDict, Field, field_validator

from hextrack.queues import queue_label
from hextrack.rank import RANKED_SOLO_5x5, display_rank, normalize_tier, queue_type_label
from hextrack.riot.ddragon import FALLBACK_VERSION, champion_icon_url, profile_icon_url
from hextrack.riot.routing import PLATFORM_TO_SHORT
from hextrack.riotid import format_riot_id, to_slug

if TYPE_CHECKING:
    from hextrack.config import Settings

# --- colours (the dpp::colors values LPBot used) --------------------------------------------

#: dpp::colors::green_snake
GREEN_SNAKE: Final = 0x6CBB3C
#: dpp::colors::red_blood
RED_BLOOD: Final = 0x660000
#: dpp::colors::gold
GOLD: Final = 0xFFD700

TIER_UP_COLOUR: Final = GREEN_SNAKE
TIER_DOWN_COLOUR: Final = RED_BLOOD
GREAT_GAME_COLOUR: Final = GREEN_SNAKE
BAD_GAME_COLOUR: Final = RED_BLOOD
PLAYER_INFO_COLOUR: Final = RED_BLOOD
DAILY_COLOUR: Final = GOLD

# --- copy ---------------------------------------------------------------------------------

GREAT_GAME_TITLE: Final = "An AMAZING game! :O"
BAD_GAME_TITLE: Final = "What a TERRIBLE game! LOL"
PLAYER_INFO_TITLE: Final = "Solo/Duo Ranked Info"
FLEX_INFO_TITLE: Final = "Flex Ranked Info"
EMPTY_LEADERBOARD: Final = "No ranked games played yet this season!"
TROPHY: Final = "\N{TROPHY}"
MEDALS: Final[tuple[str, ...]] = (
    "\N{FIRST PLACE MEDAL}",
    "\N{SECOND PLACE MEDAL}",
    "\N{THIRD PLACE MEDAL}",
)

# --- ANSI escape sequences (Discord ```ansi code blocks) ------------------------------------

ANSI_WHITE: Final = "\x1b[0;37m"
ANSI_RED: Final = "\x1b[0;31m"
ANSI_BOLD_GREEN: Final = "\x1b[1;32m"
ANSI_BOLD_RED: Final = "\x1b[1;31m"

#: Riot's default profile icon, used when we have never seen the player's icon.
DEFAULT_PROFILE_ICON: Final = 29
#: Discord's limit is 4096; stay below it so the closing fence always fits.
DESCRIPTION_BUDGET: Final = 3900


# --- inputs -------------------------------------------------------------------------------


class _EventModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class TierChangeEvent(_EventModel):
    """``tier_up`` / ``tier_down`` payload."""

    puuid: str
    game_name: str
    tag_line: str
    queue_type: str = RANKED_SOLO_5x5
    old_tier: str | None = None
    old_rank: str | None = None
    new_tier: str
    new_rank: str | None = None
    lp: int = 0
    rank_value: int | None = None

    @field_validator("new_tier")
    @classmethod
    def _known_tier(cls, value: str) -> str:
        return normalize_tier(value)

    @field_validator("old_tier")
    @classmethod
    def _known_old_tier(cls, value: str | None) -> str | None:
        return normalize_tier(value) if value else None


class GameEvent(_EventModel):
    """``great_game`` / ``bad_game`` / ``new_match`` payload."""

    puuid: str
    game_name: str
    tag_line: str
    match_id: str
    queue_id: int
    champion_id: int
    champion_name: str
    win: bool
    kills: int = Field(ge=0)
    deaths: int = Field(ge=0)
    assists: int = Field(ge=0)
    kda: float | None = None
    ai_score: float | None = None
    game_start: datetime | None = None
    game_duration: int | None = None

    @field_validator("game_start")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @property
    def kda_ratio(self) -> float:
        """(K + A) / max(D, 1), as LPBot computed it."""
        if self.kda is not None and math.isfinite(self.kda):
            return self.kda
        return (self.kills + self.assists) / max(self.deaths, 1)


@dataclass(frozen=True, slots=True)
class PlayerRef:
    """Who an embed is about. Prefer the current name from ``summoners`` over the payload."""

    puuid: str
    game_name: str
    tag_line: str
    profile_icon_id: int | None = None

    @property
    def riot_id(self) -> str:
        return format_riot_id(self.game_name, self.tag_line)


@dataclass(frozen=True, slots=True)
class RankLine:
    """Latest league-v4 standing for ``/lp``."""

    queue_type: str
    tier: str
    rank: str | None
    lp: int
    wins: int
    losses: int
    taken_at: datetime | None = None

    @property
    def games(self) -> int:
        return self.wins + self.losses

    @property
    def winrate(self) -> float | None:
        return self.wins / self.games if self.games else None


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    """One row of the daily post: a tracked player's season-to-date LP change."""

    name: str
    lp_delta: int


@dataclass(frozen=True, slots=True)
class EmbedContext:
    """Everything the builders need besides the event: links and static-asset URLs."""

    public_url: str
    platform: str = "na1"
    ddragon_version: str = FALLBACK_VERSION
    rank_icon_base: str | None = None
    #: champion id -> Data Dragon key; overrides the match-v5 ``championName`` when known
    #: (they differ for a few champions, e.g. FiddleSticks vs Fiddlesticks).
    champion_keys: Mapping[int, str] = field(default_factory=dict)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        ddragon_version: str = FALLBACK_VERSION,
        champion_keys: Mapping[int, str] | None = None,
    ) -> EmbedContext:
        return cls(
            public_url=settings.public_url,
            platform=settings.riot_platform,
            ddragon_version=ddragon_version,
            rank_icon_base=settings.rank_icon_base,
            champion_keys=dict(champion_keys or {}),
        )

    def summoner_url(self, game_name: str, tag_line: str) -> str:
        """``{public_url}/summoner/na/Game%20Name-TAG`` (slug split on the last "-")."""
        short = PLATFORM_TO_SHORT.get(self.platform.lower(), "na")
        slug = quote(to_slug(game_name, tag_line), safe="")
        return f"{self.public_url.rstrip('/')}/summoner/{short}/{slug}"

    def match_url(self, match_id: str, game_name: str, tag_line: str) -> str:
        """``{public_url}/match/NA1_123?player=Game%20Name-TAG`` (the web match page, with
        this player highlighted)."""
        match = quote(match_id, safe="")
        player = quote(to_slug(game_name, tag_line), safe="")
        return f"{self.public_url.rstrip('/')}/match/{match}?player={player}"

    def profile_icon_url(self, icon_id: int | None) -> str:
        return profile_icon_url(self.ddragon_version, icon_id or DEFAULT_PROFILE_ICON)

    def champion_icon_url(self, champion_id: int | None, champion_name: str | None) -> str | None:
        key = (self.champion_keys.get(champion_id) if champion_id is not None else None) or (
            champion_name or ""
        ).strip()
        return champion_icon_url(self.ddragon_version, key) if key else None

    def rank_emblem_url(self, tier: str | None) -> str | None:
        """``{rank_icon_base}{tier}.png`` like LPBot; None when no base is configured.

        A "/" is inserted unless the base already ends with a separator, so both
        ``https://cdn/emblems/`` and ``https://cdn/emblems`` work.
        """
        if not self.rank_icon_base or not tier:
            return None
        base = self.rank_icon_base
        if not base.endswith(("/", "-", "_", "=")):
            base += "/"
        return f"{base}{tier.strip().lower()}.png"


# --- small helpers ------------------------------------------------------------------------


def _code_safe(text: str) -> str:
    """Keep user text from closing a ``` code block."""
    return text.replace("`", "\u02cb")


def ansi_block(body: str) -> str:
    return f"```ansi\n{body}\n```"


def ansi_kda(kills: int, deaths: int, assists: int, *, great: bool) -> str:
    """LPBot's K/D/A line: great games bold-green kills, bad games red deaths."""
    if great:
        body = f"{ANSI_BOLD_GREEN}{kills}{ANSI_WHITE} / {deaths}{ANSI_WHITE} / {assists}"
    else:
        body = f"{ANSI_WHITE}{kills} / {ANSI_RED}{deaths}{ANSI_WHITE} / {assists}"
    return ansi_block(body)


def percent(ratio: float) -> int:
    """0..1 -> 0..100, rounding half away from zero like ``std::round``."""
    return min(100, max(0, math.floor(ratio * 100 + 0.5)))


def ai_score_footer(score: float | None) -> str | None:
    """``"AI Score: 83%"``, or None when the game was not scored."""
    if score is None or not math.isfinite(score):
        return None
    return f"AI Score: {percent(score)}%"


def format_kda_ratio(ratio: float) -> str:
    return f"{ratio:.2f}"


def _set_author(embed: discord.Embed, player: PlayerRef, ctx: EmbedContext) -> None:
    embed.set_author(
        name=player.riot_id,
        url=ctx.summoner_url(player.game_name, player.tag_line),
        icon_url=ctx.profile_icon_url(player.profile_icon_id),
    )


def _set_rank_image(embed: discord.Embed, tier: str | None, ctx: EmbedContext) -> None:
    url = ctx.rank_emblem_url(tier)
    if url:
        embed.set_image(url=url)


def _queue_suffix(queue_type: str) -> str:
    return "" if queue_type == RANKED_SOLO_5x5 else f" in {queue_type_label(queue_type)}"


# --- builders -----------------------------------------------------------------------------


def tier_up(event: TierChangeEvent, player: PlayerRef, ctx: EmbedContext) -> discord.Embed:
    """LPBot ``tierUpEmbed``: "Ranked up to GOLD!" in green with the new emblem."""
    embed = discord.Embed(
        title=f"Ranked up to {event.new_tier}!",
        description=(
            f"Now **{display_rank(event.new_tier, event.new_rank, event.lp)}** "
            f"in {queue_type_label(event.queue_type)}"
        ),
        colour=discord.Colour(TIER_UP_COLOUR),
    )
    _set_author(embed, player, ctx)
    _set_rank_image(embed, event.new_tier, ctx)
    return embed


def tier_down(event: TierChangeEvent, player: PlayerRef, ctx: EmbedContext) -> discord.Embed:
    """LPBot ``tierDownEmbed``: "{name} is a LOSER!" / "They just deranked to X! LOL"."""
    embed = discord.Embed(
        title=f"{discord.utils.escape_markdown(player.riot_id)} is a LOSER!",
        description=(
            f"They just deranked to {event.new_tier}{_queue_suffix(event.queue_type)}! LOL"
        ),
        colour=discord.Colour(TIER_DOWN_COLOUR),
    )
    _set_author(embed, player, ctx)
    _set_rank_image(embed, event.new_tier, ctx)
    return embed


def _game_embed(
    event: GameEvent,
    player: PlayerRef,
    ctx: EmbedContext,
    *,
    title: str,
    colour: int,
    great: bool,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=ansi_kda(event.kills, event.deaths, event.assists, great=great),
        colour=discord.Colour(colour),
        timestamp=event.game_start,
        url=ctx.match_url(event.match_id, player.game_name, player.tag_line),
    )
    _set_author(embed, player, ctx)
    thumbnail = ctx.champion_icon_url(event.champion_id, event.champion_name)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    embed.add_field(name="Champion", value=event.champion_name, inline=True)
    embed.add_field(name="Result", value="Victory" if event.win else "Defeat", inline=True)
    embed.add_field(name="KDA", value=format_kda_ratio(event.kda_ratio), inline=True)
    embed.add_field(name="Queue", value=queue_label(event.queue_id), inline=True)
    footer = ai_score_footer(event.ai_score)
    if footer:
        embed.set_footer(text=footer)
    return embed


def great_game(event: GameEvent, player: PlayerRef, ctx: EmbedContext) -> discord.Embed:
    """LPBot ``greatGameEmbed`` (KDA > 6): champion thumbnail, ANSI K/D/A, AI Score."""
    return _game_embed(
        event, player, ctx, title=GREAT_GAME_TITLE, colour=GREAT_GAME_COLOUR, great=True
    )


def bad_game(event: GameEvent, player: PlayerRef, ctx: EmbedContext) -> discord.Embed:
    """LPBot ``badGameEmbed`` (sent only when ``HEXTRACK_BAD_GAME_EMBEDS`` is on)."""
    return _game_embed(
        event, player, ctx, title=BAD_GAME_TITLE, colour=BAD_GAME_COLOUR, great=False
    )


def rank_leaderboard(entries: Iterable[LeaderboardEntry]) -> list[LeaderboardEntry]:
    """Players with a non-zero delta, best first (ties by name). Zero is skipped like
    LPBot: it means "no games this season" at least as often as "broke even"."""
    return sorted(
        (e for e in entries if e.lp_delta != 0),
        key=lambda e: (-e.lp_delta, e.name.casefold()),
    )


def _leaderboard_line(position: int, entry: LeaderboardEntry) -> str:
    prefix = MEDALS[position] + " " if position < len(MEDALS) else f"{position + 1}. "
    colour = f"{ANSI_BOLD_GREEN}+" if entry.lp_delta >= 0 else ANSI_BOLD_RED
    return f"{prefix}{colour}{entry.lp_delta} LP{ANSI_WHITE}   {_code_safe(entry.name)}"


def daily_leaderboard(
    entries: Iterable[LeaderboardEntry], *, season_year: int, timestamp: datetime
) -> discord.Embed:
    """LPBot ``dailyEmbed``: season-to-date solo LP change per tracked player, top 3 with
    medals, gains green and losses red."""
    ranked = rank_leaderboard(entries)
    if not ranked:
        description = EMPTY_LEADERBOARD
    else:
        lines: list[str] = []
        used = len(ansi_block(""))
        for position, entry in enumerate(ranked):
            line = _leaderboard_line(position, entry)
            remaining = len(ranked) - position
            if used + len(line) + 1 > DESCRIPTION_BUDGET:
                lines.append(f"{ANSI_WHITE}... and {remaining} more")
                break
            lines.append(line)
            used += len(line) + 1
        description = ansi_block("\n".join(lines))
    return discord.Embed(
        title=f"{TROPHY} Season {season_year} Leaderboard",
        description=description,
        colour=discord.Colour(DAILY_COLOUR),
        timestamp=timestamp,
    )


def player_info(player: PlayerRef, rank: RankLine | None, ctx: EmbedContext) -> discord.Embed:
    """LPBot ``playerInfoEmbed`` for ``/lp``: rank, LP, W/L and winrate."""
    queue_type = rank.queue_type if rank is not None else RANKED_SOLO_5x5
    embed = discord.Embed(
        title=PLAYER_INFO_TITLE if queue_type == RANKED_SOLO_5x5 else FLEX_INFO_TITLE,
        colour=discord.Colour(PLAYER_INFO_COLOUR),
        timestamp=rank.taken_at if rank is not None else None,
    )
    _set_author(embed, player, ctx)
    if rank is None:
        embed.description = "**Current Rank:** Unranked"
        return embed
    embed.description = f"**Current Rank:** {display_rank(rank.tier, rank.rank)}"
    embed.add_field(name="LP", value=f"{rank.lp} LP", inline=True)
    embed.add_field(name="W/L Record", value=f"{rank.wins}/{rank.losses}", inline=True)
    winrate = rank.winrate
    embed.add_field(
        name="Winrate",
        value=f"{percent(winrate)}%" if winrate is not None else "-",
        inline=True,
    )
    _set_rank_image(embed, rank.tier, ctx)
    return embed
