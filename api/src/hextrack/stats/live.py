"""Read side of live games: the worker's ``app_state`` snapshot (see ingest/live.py) joined
with the roster, stored ranks and season numbers, champion names from Data Dragon."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.api.schemas import LiveBan, LiveGame, LiveGames, LiveParticipant, RankEntry
from hextrack.config import Settings
from hextrack.db.models import RankSnapshot
from hextrack.db.repo.app_state import get_state
from hextrack.ingest.live import STATE_KEY
from hextrack.queues import QUEUE_LABELS, RANKED_QUEUES, queue_label
from hextrack.rank import (
    APEX_TIERS,
    DIVISION_ORDER,
    RANKED_FLEX_SR,
    RANKED_SOLO_5x5,
    normalize_tier,
    rank_value,
)
from hextrack.riot.ddragon import DDragon
from hextrack.riot.schemas import CurrentGameInfoDto, CurrentGameParticipantDto, LeagueEntryDto
from hextrack.stats import present, queries
from hextrack.stats.aggregate import stat_rows
from hextrack.stats.metrics import clamp_rate, to_float, to_int, winrate
from hextrack.stats.squad import _scored_by

logger = logging.getLogger(__name__)

#: A snapshot older than ``STALE_POLLS`` poll intervals plus :data:`STALE_GRACE` means the
#: worker stopped; its games are hidden rather than shown as ghosts.
STALE_POLLS: Final = 3
STALE_GRACE: Final = timedelta(seconds=60)
#: spectator-v5 ``bannedChampions[].championId`` for "no ban".
NO_BAN: Final = -1
BLUE, RED = 100, 200
#: Champion names are optional; never hold the response for Data Dragon longer than this.
DDRAGON_TIMEOUT_SECONDS: Final = 3.0
#: Labels for games whose queue id is missing or unknown (spectator ``gameMode``).
MODE_LABELS: Final[dict[str, str]] = {
    "CLASSIC": "Summoner's Rift",
    "ARAM": "ARAM",
    "URF": "URF",
    "ARURF": "ARURF",
    "ONEFORALL": "One for All",
    "NEXUSBLITZ": "Nexus Blitz",
    "ULTBOOK": "Ultimate Spellbook",
    "CHERRY": "Arena",
    "STRAWBERRY": "Swarm",
    "PRACTICETOOL": "Practice Tool",
    "TUTORIAL": "Tutorial",
}


@dataclass(slots=True)
class _Stored:
    info: CurrentGameInfoDto
    ranks: Mapping[str, Any]
    first_seen_at: datetime
    seen_at: datetime


@dataclass(slots=True)
class _Totals:
    games: int = 0
    wins: int = 0
    ai_sum: float = 0.0
    ai_count: int = 0

    @property
    def avg_ai_score(self) -> float | None:
        return clamp_rate(self.ai_sum / self.ai_count) if self.ai_count else None


async def live_games(
    session: AsyncSession,
    settings: Settings,
    ddragon: DDragon,
    *,
    model_version: str | None,
    now: datetime,
) -> LiveGames:
    """Current roster games; empty when the snapshot is stale (worker down)."""
    interval = settings.poll_interval_seconds
    empty = LiveGames(checked_at=None, interval_seconds=interval, games=[])
    if not settings.live_games:
        return empty
    state = await get_state(session, STATE_KEY)
    if not state:
        return empty
    checked_at = _parse_time(state.get("checked_at"))
    if checked_at is None:
        return empty
    if now - checked_at > timedelta(seconds=STALE_POLLS * interval) + STALE_GRACE:
        return LiveGames(checked_at=checked_at, interval_seconds=interval, games=[])

    stored = _stored_games(state.get("games"))
    if not stored:
        return LiveGames(checked_at=checked_at, interval_seconds=interval, games=[])

    puuids = {puuid for game in stored for p in game.info.participants if (puuid := _puuid(p))}
    roster = {s.puuid for s in await queries.tracked_summoners(session)}
    tracked_here = puuids & roster
    snapshots = await queries.current_rank_snapshots(
        session, tracked_here, season_start=settings.season_start, now=now
    )
    totals, champions = await _season_numbers(
        session, puuids, since=settings.season_start, model_version=model_version
    )
    champion_names = await _champion_names(ddragon)

    games = [
        _live_game(
            game,
            settings=settings,
            roster=roster,
            snapshots=snapshots,
            totals=totals,
            champions=champions,
            champion_names=champion_names,
        )
        for game in stored
    ]
    games.sort(key=_game_sort_key)
    return LiveGames(checked_at=checked_at, interval_seconds=interval, games=games)


async def _champion_names(ddragon: DDragon) -> dict[int, str]:
    """Data Dragon's champion map, or ``{}`` (names None) when it is slow or failing."""
    try:
        return await asyncio.wait_for(ddragon.champion_map(), DDRAGON_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("live: Data Dragon champion map unavailable (%s)", exc)
        return {}


# --- stored state ----------------------------------------------------------------------------


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _stored_games(raw: Any) -> list[_Stored]:
    """Validated games of the snapshot; malformed entries are skipped (and logged)."""
    games: list[_Stored] = []
    seen: set[int] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        try:
            info = CurrentGameInfoDto.model_validate(entry.get("info"))
        except ValidationError as exc:
            logger.warning("skipping malformed live game: %s", exc.errors()[:1])
            continue
        first_seen_at = _parse_time(entry.get("first_seen_at"))
        seen_at = _parse_time(entry.get("seen_at")) or first_seen_at
        if first_seen_at is None or seen_at is None or info.game_id in seen:
            continue
        seen.add(info.game_id)
        ranks = entry.get("ranks")
        games.append(
            _Stored(
                info=info,
                ranks=ranks if isinstance(ranks, dict) else {},
                first_seen_at=first_seen_at,
                seen_at=seen_at,
            )
        )
    return games


def _puuid(participant: CurrentGameParticipantDto) -> str | None:
    """The participant's puuid, None for bots (spectator may send "" or a placeholder)."""
    if participant.bot or not participant.puuid:
        return None
    return participant.puuid


# --- season numbers --------------------------------------------------------------------------


async def _season_numbers(
    session: AsyncSession,
    puuids: Collection[str],
    *,
    since: datetime,
    model_version: str | None,
) -> tuple[dict[str, _Totals], dict[tuple[str, int], _Totals]]:
    """Per player and per (player, champion) ranked totals this season, from ONE grouped
    query; AI sums only count lines scored by ``model_version``."""
    if not puuids:
        return {}, {}
    rows = stat_rows(queues=RANKED_QUEUES, since=since, puuids=puuids).subquery("rows")
    scored = _scored_by(rows.c.model_version, rows.c.ai_score, model_version)
    stmt = select(
        rows.c.puuid,
        rows.c.champion_id,
        func.count().label("games"),
        func.count().filter(rows.c.win.is_(True)).label("wins"),
        func.sum(rows.c.ai_score).filter(scored).label("ai_sum"),
        func.count().filter(scored).label("ai_count"),
    ).group_by(rows.c.puuid, rows.c.champion_id)
    totals: dict[str, _Totals] = defaultdict(_Totals)
    champions: dict[tuple[str, int], _Totals] = {}
    for row in (await session.execute(stmt)).mappings():
        line = _Totals(
            games=to_int(row["games"]),
            wins=to_int(row["wins"]),
            ai_sum=to_float(row["ai_sum"]),
            ai_count=to_int(row["ai_count"]),
        )
        champions[(row["puuid"], row["champion_id"])] = line
        player = totals[row["puuid"]]
        player.games += line.games
        player.wins += line.wins
        player.ai_sum += line.ai_sum
        player.ai_count += line.ai_count
    return dict(totals), champions


# --- building the response -------------------------------------------------------------------


def _game_sort_key(game: LiveGame) -> tuple[bool, float, float]:
    """Loading games (no start yet) first, then the most recently started."""
    started = game.started_at.timestamp() if game.started_at is not None else 0.0
    return (game.started_at is not None, -started, -game.first_seen_at.timestamp())


def _queue_label(queue_id: int | None, game_mode: str | None) -> str:
    if queue_id is not None and queue_id in QUEUE_LABELS:
        return queue_label(queue_id)
    if game_mode:
        mode = game_mode.strip().upper()
        return MODE_LABELS.get(mode) or mode.title()
    if queue_id is not None:
        return queue_label(queue_id)
    return "Live game"


def _split_riot_id(riot_id: str | None) -> tuple[str | None, str | None]:
    """``"Name#TAG"`` split on the LAST "#"; a value without "#" is all game name."""
    if not riot_id or not riot_id.strip():
        return None, None
    name, sep, tag = riot_id.strip().rpartition("#")
    if not sep:
        return riot_id.strip(), None
    return name or None, tag or None


def _entry_rank(entries: Any, queue_type: str, *, taken_at: datetime) -> RankEntry | None:
    """RankEntry from stored league-v4 entry JSON for one queue (None if absent/invalid)."""
    for raw in entries if isinstance(entries, list) else []:
        try:
            entry = LeagueEntryDto.model_validate(raw)
        except ValidationError:
            continue
        if entry.queue_type != queue_type:
            continue
        try:
            tier = normalize_tier(entry.tier)
        except ValueError:
            return None
        division: str | None = None
        if tier not in APEX_TIERS:
            division = (entry.rank or "").strip().upper()
            if division not in DIVISION_ORDER:
                return None
        return RankEntry(
            queue_type=queue_type,  # type: ignore[arg-type]
            tier=tier,  # type: ignore[arg-type]
            rank=division,  # type: ignore[arg-type]
            lp=entry.league_points,
            wins=entry.wins,
            losses=entry.losses,
            winrate=winrate(entry.wins, entry.wins + entry.losses),
            rank_value=rank_value(tier, division, entry.league_points),
            taken_at=taken_at,
        )
    return None


def _live_game(
    game: _Stored,
    *,
    settings: Settings,
    roster: Collection[str],
    snapshots: Mapping[str, Mapping[str, RankSnapshot]],
    totals: Mapping[str, _Totals],
    champions: Mapping[tuple[str, int], _Totals],
    champion_names: Mapping[int, str],
) -> LiveGame:
    info = game.info
    platform = (info.platform_id or settings.riot_platform).strip()
    participants = sorted(
        (p for p in info.participants if p.team_id in (BLUE, RED)),
        key=lambda p: p.team_id != BLUE,  # stable: Riot's order within each team
    )
    return LiveGame(
        game_id=info.game_id,
        match_id=f"{platform.upper()}_{info.game_id}",
        platform=platform.lower(),
        queue_id=info.game_queue_config_id,
        queue_label=_queue_label(info.game_queue_config_id, info.game_mode),
        game_mode=info.game_mode,
        map_id=info.map_id,
        started_at=(
            datetime.fromtimestamp(info.game_start_time / 1000, UTC)
            if info.game_start_time > 0
            else None
        ),
        first_seen_at=game.first_seen_at,
        seen_at=game.seen_at,
        bans=[
            LiveBan(
                champion_id=ban.champion_id,
                champion_name=champion_names.get(ban.champion_id),
                team_id=ban.team_id,  # type: ignore[arg-type]
            )
            for ban in info.banned_champions
            if ban.champion_id != NO_BAN and ban.team_id in (BLUE, RED)
        ],
        participants=[
            _participant(
                p,
                game=game,
                roster=roster,
                snapshots=snapshots,
                totals=totals,
                champions=champions,
                champion_names=champion_names,
            )
            for p in participants
        ],
    )


def _participant(
    p: CurrentGameParticipantDto,
    *,
    game: _Stored,
    roster: Collection[str],
    snapshots: Mapping[str, Mapping[str, RankSnapshot]],
    totals: Mapping[str, _Totals],
    champions: Mapping[tuple[str, int], _Totals],
    champion_names: Mapping[int, str],
) -> LiveParticipant:
    puuid = _puuid(p)
    game_name, tag_line = _split_riot_id(p.riot_id)
    tracked = puuid is not None and puuid in roster
    solo: RankEntry | None = None
    flex: RankEntry | None = None
    if puuid is not None and tracked:
        by_queue = snapshots.get(puuid, {})
        solo = present.rank_entry(by_queue.get(RANKED_SOLO_5x5))
        flex = present.rank_entry(by_queue.get(RANKED_FLEX_SR))
    elif puuid is not None:
        entries = game.ranks.get(puuid)
        solo = _entry_rank(entries, RANKED_SOLO_5x5, taken_at=game.first_seen_at)
        flex = _entry_rank(entries, RANKED_FLEX_SR, taken_at=game.first_seen_at)
    season = totals.get(puuid, _Totals()) if puuid is not None else _Totals()
    on_champion = (
        champions.get((puuid, p.champion_id), _Totals()) if puuid is not None else _Totals()
    )
    perks = p.perks
    return LiveParticipant(
        puuid=puuid,
        game_name=game_name,
        tag_line=tag_line,
        team_id=p.team_id,  # type: ignore[arg-type]
        champion_id=p.champion_id,
        champion_name=champion_names.get(p.champion_id),
        spell1_id=p.spell1_id,
        spell2_id=p.spell2_id,
        keystone_id=perks.perk_ids[0] if perks is not None and perks.perk_ids else None,
        primary_style_id=perks.perk_style if perks is not None else None,
        secondary_style_id=perks.perk_sub_style if perks is not None else None,
        profile_icon_id=p.profile_icon_id,
        bot=p.bot,
        is_tracked=tracked,
        solo=solo,
        flex=flex,
        season_games=season.games,
        season_wins=season.wins,
        avg_ai_score=season.avg_ai_score,
        champion_games=on_champion.games,
        champion_wins=on_champion.wins,
    )
