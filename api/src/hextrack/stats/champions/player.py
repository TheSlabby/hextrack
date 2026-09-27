"""One roster player's ranked games on one champion this season, next to the whole field.

Rows: the player's ``match_participants`` on the champion in ranked solo / flex (filtered by
``queue``), started at or after the season start, remakes excluded, roster games only
(``matches.source = 'roster'``): the same set the squad view counts
(:func:`hextrack.stats.champions.read.champion_squad`). Not cached (a live query over one
player's rows).

* **AI Score:** the average, the per-game scores and the best game use only rows scored by
  ``model_version`` (the active model, as the squad view); other rows show None.
* **Main position:** most games, then TOP .. UTILITY order (as the squad view).
* **Field numbers:** the champion rollups (``champion_stats``) for that position, summed over
  every season patch with counted games, same queue filter.
* **Squad rank:** the player's place in the squad view's order (most games, then wins, then
  name), out of the roster players in it.
* **Core build:** the first three completed non-boots items of each of their games with a
  stored timeline, classified with that game's patch item data exactly as the rollups do
  (:func:`hextrack.stats.champions.rollup.timeline_keys`); the most common one, its pick
  rate over their games that have a core. Games whose patch item data cannot be loaded are
  left out; with no item data at all the core is None (never an error).
* **Rune page / spells:** most common among their games (ties: more wins, then key), pick
  rate over all their games.
* **Best game:** the highest AI Score among their wins, else among all their games (ties:
  newest); None when nothing is scored.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.api.schemas import (
    BuildOption,
    ChampionPlayer,
    ChampionPlayerGame,
    LeaderboardQueue,
    RunePageOption,
    SpellOption,
)
from hextrack.config import Settings
from hextrack.db.models import Match, MatchParticipant, MatchTimelinePlayer, Summoner
from hextrack.stats import present
from hextrack.stats.aggregate import LEADERBOARD_QUEUES, stat_rows
from hextrack.stats.champions import KIND_CORE, KIND_RUNE_PAGE, ROLES, join_key, split_key
from hextrack.stats.champions.items import ItemCatalog
from hextrack.stats.champions.read import (
    _role_rows,
    champion_names,
    champion_squad,
    resolve_champion,
    resolve_window,
)
from hextrack.stats.champions.rollup import PlayerLine, TimelineLine, rune_keys, timeline_keys
from hextrack.stats.metrics import (
    clamp_rate,
    per_minute,
    rounded,
    safe_div,
    to_int,
    total_kda,
    winrate,
)

logger = logging.getLogger(__name__)

#: Games in ``recent``.
RECENT_GAMES = 5
_ROLE_ORDER = {role: i for i, role in enumerate(ROLES)}


class PlayerNotFound(LookupError):
    """The puuid is not a roster (tracked) summoner."""


class CatalogSource(Protocol):
    async def item_catalog(self, patch: str) -> ItemCatalog | None: ...


@dataclass(slots=True)
class _Game:
    match_id: str
    participant_id: int
    game_start: datetime
    queue_id: int
    position: str
    win: bool
    kills: int
    deaths: int
    assists: int
    cs: int
    damage: int
    gold: int
    duration_s: int
    items: list[int]
    spells: tuple[int, int]
    primary_style_id: int | None
    secondary_style_id: int | None
    rune_ids: list[int] | None
    #: Only when scored by the requested model version.
    ai_score: float | None
    patch: str
    has_timeline: bool

    def api(self) -> ChampionPlayerGame:
        return ChampionPlayerGame(
            match_id=self.match_id,
            game_start=self.game_start,
            queue_id=self.queue_id,
            position=present.normalize_position(self.position),
            win=self.win,
            kills=self.kills,
            deaths=self.deaths,
            assists=self.assists,
            cs=self.cs,
            game_duration=self.duration_s,
            items=self.items,
            ai_score=self.ai_score,
            patch=self.patch,
        )


def _recency(game: _Game) -> tuple[datetime, str]:
    """Sort key, newest last (sort with ``reverse=True`` for newest first)."""
    return (game.game_start, game.match_id)


def main_position(games: Iterable[_Game]) -> str:
    """Most played position (ties: TOP .. UTILITY, then name); "" with no games."""
    counts = Counter(g.position or "" for g in games)
    if not counts:
        return ""
    return min(counts.items(), key=lambda kv: (-kv[1], _ROLE_ORDER.get(kv[0], len(ROLES)), kv[0]))[
        0
    ]


def best_game(games: Sequence[_Game]) -> _Game | None:
    """Highest AI Score among wins, else among all games (ties: newest)."""
    scored = [g for g in games if g.ai_score is not None]
    pool = [g for g in scored if g.win] or scored
    if not pool:
        return None
    return max(pool, key=lambda g: (g.ai_score or 0.0, *_recency(g)))


@dataclass(slots=True)
class _Choice:
    games: int = 0
    wins: int = 0
    extra: int = 0


def _top(choices: Mapping[str, _Choice]) -> tuple[str, _Choice] | None:
    if not choices:
        return None
    return min(choices.items(), key=lambda kv: (-kv[1].games, -kv[1].wins, kv[0]))


def top_rune_page(games: Sequence[_Game]) -> RunePageOption | None:
    pages: dict[str, _Choice] = defaultdict(_Choice)
    for g in games:
        line = PlayerLine(
            participant_id=g.participant_id,
            team_id=0,
            champion_id=0,
            champion_name="",
            position=g.position,
            win=g.win,
            primary_style_id=g.primary_style_id,
            secondary_style_id=g.secondary_style_id,
            rune_ids=g.rune_ids,
        )
        for kind, key in rune_keys(line):
            if kind == KIND_RUNE_PAGE:
                pages[key].games += 1
                pages[key].wins += int(g.win)
    top = _top(pages)
    if top is None:
        return None
    key, choice = top
    ids = split_key(key)
    return RunePageOption(
        primary_style_id=ids[0],
        secondary_style_id=ids[1],
        rune_ids=ids[2:],
        games=choice.games,
        wins=choice.wins,
        win_rate=winrate(choice.wins, choice.games),
        pick_rate=winrate(choice.games, len(games)),
    )


def top_spells(games: Sequence[_Game]) -> SpellOption | None:
    pairs: dict[str, _Choice] = defaultdict(_Choice)
    for g in games:
        spells = sorted(g.spells)
        if all(spells):
            pairs[join_key(spells)].games += 1
            pairs[join_key(spells)].wins += int(g.win)
    top = _top(pairs)
    if top is None:
        return None
    key, choice = top
    return SpellOption(
        spell_ids=split_key(key),
        games=choice.games,
        wins=choice.wins,
        win_rate=winrate(choice.wins, choice.games),
        pick_rate=winrate(choice.games, len(games)),
    )


def top_core(
    games: Sequence[_Game],
    timelines: Mapping[str, TimelineLine],
    catalogs: Mapping[str, ItemCatalog | None],
) -> BuildOption | None:
    """The most common core among ``games`` with a timeline (``timelines`` by match id) and
    item data for their patch; pick rate over those that have a core."""
    cores: dict[str, _Choice] = defaultdict(_Choice)
    with_core = 0
    for g in games:
        timeline = timelines.get(g.match_id)
        catalog = catalogs.get(g.patch)
        if timeline is None or catalog is None:
            continue
        for kind, key, extra in timeline_keys(timeline, catalog):
            if kind == KIND_CORE:
                with_core += 1
                choice = cores[key]
                choice.games += 1
                choice.wins += int(g.win)
                choice.extra += extra
    top = _top(cores)
    if top is None:
        return None
    key, choice = top
    return BuildOption(
        items=split_key(key),
        games=choice.games,
        wins=choice.wins,
        win_rate=winrate(choice.wins, choice.games),
        pick_rate=winrate(choice.games, with_core),
        avg_time_s=rounded(safe_div(choice.extra, choice.games)),
    )


# --- queries ------------------------------------------------------------------------------


async def _games(
    session: AsyncSession,
    settings: Settings,
    *,
    puuid: str,
    champion_id: int,
    queue: LeaderboardQueue,
    model_version: str | None,
) -> list[_Game]:
    mp = MatchParticipant
    stmt = (
        stat_rows(queues=LEADERBOARD_QUEUES[queue], since=settings.season_start, puuids=[puuid])
        .add_columns(
            mp.participant_id,
            mp.gold_earned,
            mp.items,
            mp.summoner1_id,
            mp.summoner2_id,
            mp.primary_style_id,
            mp.secondary_style_id,
            mp.rune_ids,
            Match.patch,
            Match.timeline_state,
        )
        .where(mp.champion_id == champion_id, Match.source == "roster")
    )
    games: list[_Game] = []
    for r in (await session.execute(stmt)).mappings():
        scored = model_version is not None and r["model_version"] == model_version
        games.append(
            _Game(
                match_id=r["match_id"],
                participant_id=int(r["participant_id"]),
                game_start=r["game_start"],
                queue_id=int(r["queue_id"]),
                position=r["team_position"] or "",
                win=bool(r["win"]),
                kills=to_int(r["kills"]),
                deaths=to_int(r["deaths"]),
                assists=to_int(r["assists"]),
                cs=to_int(r["cs"]),
                damage=to_int(r["damage"]),
                gold=to_int(r["gold_earned"]),
                duration_s=to_int(r["game_duration"]),
                items=[int(item or 0) for item in r["items"] or ()],
                spells=(to_int(r["summoner1_id"]), to_int(r["summoner2_id"])),
                primary_style_id=r["primary_style_id"],
                secondary_style_id=r["secondary_style_id"],
                rune_ids=list(r["rune_ids"]) if r["rune_ids"] is not None else None,
                ai_score=clamp_rate(r["ai_score"]) if scored else None,
                patch=r["patch"],
                has_timeline=r["timeline_state"] == "ok",
            )
        )
    games.sort(key=_recency, reverse=True)
    return games


async def _timelines(
    session: AsyncSession, puuid: str, games: Sequence[_Game]
) -> dict[str, TimelineLine]:
    """match id -> the player's timeline row, for their games whose timeline is stored."""
    ids = sorted({g.match_id for g in games if g.has_timeline})
    if not ids:
        return {}
    mtp, mp = MatchTimelinePlayer, MatchParticipant
    stmt = (
        select(mtp.match_id, mtp.purchases, mtp.purchase_s, mtp.skill_order)
        .join(
            mp,
            and_(mp.match_id == mtp.match_id, mp.participant_id == mtp.participant_id),
        )
        .where(mp.puuid == puuid, mtp.match_id.in_(ids))
    )
    return {
        match_id: TimelineLine(
            purchases=list(purchases or ()),
            purchase_s=list(purchase_s or ()),
            skill_order=list(skill_order or ()),
        )
        for match_id, purchases, purchase_s, skill_order in (await session.execute(stmt)).all()
    }


async def _catalogs(
    ddragon: CatalogSource | None, patches: Iterable[str]
) -> dict[str, ItemCatalog | None]:
    out: dict[str, ItemCatalog | None] = {}
    for patch in sorted(set(patches)):
        catalog = None
        if ddragon is not None:
            try:
                catalog = await ddragon.item_catalog(patch)
            except Exception as exc:  # item data is optional here; never fail the page
                logger.warning("item data for patch %s unavailable: %s", patch, exc)
        out[patch] = catalog
    return out


@dataclass(slots=True)
class _Field:
    win_rate: float | None = None
    kda: float | None = None
    cs_per_min: float | None = None
    avg_damage: float | None = None


async def _field(
    session: AsyncSession, champion_id: int, position: str, queue: LeaderboardQueue
) -> _Field:
    if position not in ROLES:
        return _Field()
    window = await resolve_window(session, "season", queue)
    if not window.patches:
        return _Field()
    row = next(
        (r for r in await _role_rows(session, champion_id, window) if r.position == position), None
    )
    if row is None or row.games <= 0:
        return _Field()
    return _Field(
        win_rate=winrate(row.wins, row.games),
        kda=total_kda(row.kills, row.deaths, row.assists),
        cs_per_min=per_minute(row.cs, row.duration_s),
        avg_damage=rounded(safe_div(row.damage, row.games)),
    )


async def champion_player(
    session: AsyncSession,
    settings: Settings,
    *,
    champion: str,
    puuid: str,
    queue: LeaderboardQueue,
    model_version: str | None,
    ddragon: Any | None = None,
) -> ChampionPlayer:
    """See the module docstring. Raises :class:`hextrack.stats.champions.read.ChampionNotFound`
    or :class:`PlayerNotFound`."""
    names = await champion_names(session)
    champion_id, champion_name = resolve_champion(names, champion)
    summoner = await session.get(Summoner, puuid)
    if summoner is None or not summoner.is_tracked:
        raise PlayerNotFound(puuid)

    games = await _games(
        session,
        settings,
        puuid=puuid,
        champion_id=champion_id,
        queue=queue,
        model_version=model_version,
    )
    n = len(games)
    wins = sum(g.win for g in games)
    kills = sum(g.kills for g in games)
    deaths = sum(g.deaths for g in games)
    assists = sum(g.assists for g in games)
    scores = [g.ai_score for g in games if g.ai_score is not None]
    main = main_position(games)
    field = await _field(session, champion_id, main, queue)

    squad_rank: int | None = None
    squad = await champion_squad(
        session, settings, champion=str(champion_id), queue=queue, model_version=model_version
    )
    squad_players = len(squad.rows)
    for index, row in enumerate(squad.rows, start=1):
        if row.puuid == puuid:
            squad_rank = index
            break

    timelines = await _timelines(session, puuid, games)
    core = None
    if timelines:
        patches = {g.patch for g in games if g.match_id in timelines}
        core = top_core(games, timelines, await _catalogs(ddragon, patches))

    best = best_game(games)
    return ChampionPlayer(
        champion_id=champion_id,
        champion_name=champion_name,
        puuid=summoner.puuid,
        game_name=summoner.game_name,
        tag_line=summoner.tag_line,
        profile_icon_id=summoner.profile_icon_id,
        queue=queue,
        model_version=model_version,
        games=n,
        wins=wins,
        win_rate=winrate(wins, n) if n else None,
        avg_kills=rounded(safe_div(kills, n)),
        avg_deaths=rounded(safe_div(deaths, n)),
        avg_assists=rounded(safe_div(assists, n)),
        kda=total_kda(kills, deaths, assists),
        cs_per_min=per_minute(sum(g.cs for g in games), sum(g.duration_s for g in games)),
        avg_damage=rounded(safe_div(sum(g.damage for g in games), n)),
        avg_gold=rounded(safe_div(sum(g.gold for g in games), n)),
        avg_ai_score=clamp_rate(sum(scores) / len(scores)) if scores else None,
        main_position=present.normalize_position(main),
        field_win_rate=field.win_rate,
        field_kda=field.kda,
        field_cs_per_min=field.cs_per_min,
        field_avg_damage=field.avg_damage,
        squad_rank=squad_rank,
        squad_players=squad_players,
        core=core,
        timeline_games=len(timelines),
        rune_page=top_rune_page(games),
        spells=top_spells(games),
        recent=[g.api() for g in games[:RECENT_GAMES]],
        best_game=best.api() if best is not None else None,
    )
