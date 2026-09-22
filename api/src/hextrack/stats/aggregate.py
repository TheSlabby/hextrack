"""Set-based aggregates: the season profile of one player and the roster leaderboard.

All the heavy lifting is SQL (GROUP BY, FILTER, window functions, ``DISTINCT ON``); Python
only stitches a handful of result sets together. See :mod:`hextrack.stats` for the shared
definitions of "ranked", "season" and "remake".
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import (
    ColumnElement,
    Float,
    Select,
    and_,
    cast,
    false,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hextrack.api.schemas import (
    BestAlly,
    ChampionStat,
    Leaderboard,
    LeaderboardEntry,
    LeaderboardQueue,
    ProfileStats,
    RoleStat,
    SummonerProfile,
)
from hextrack.config import Settings
from hextrack.db.models import Match, MatchParticipant, Summoner
from hextrack.queues import RANKED_FLEX, RANKED_QUEUES, RANKED_SOLO
from hextrack.rank import RANKED_FLEX_SR, RANKED_SOLO_5x5
from hextrack.stats import present, queries
from hextrack.stats.metrics import (
    clamp_rate,
    rounded,
    safe_div,
    to_float,
    to_int,
    to_optional_float,
    total_kda,
    winrate,
)

#: Profile limits (mirrored by the response schema constraints).
TOP_CHAMPIONS: Final = 7
PROFILE_RECENT_FORM: Final = 20
#: Leaderboard limits.
LEADERBOARD_TOP_CHAMPIONS: Final = 3
LEADERBOARD_RECENT_FORM: Final = 10

LEADERBOARD_QUEUES: Final[dict[str, tuple[int, ...]]] = {
    "all": tuple(sorted(RANKED_QUEUES)),
    "solo": (RANKED_SOLO,),
    "flex": (RANKED_FLEX,),
}


# --- the filtered participant set --------------------------------------------------------


def stat_rows(
    *,
    queues: Collection[int],
    since: datetime | None,
    puuids: Collection[str] | None = None,
) -> Select:
    """Participant lines that count towards stats: the given queues, games started at or
    after ``since``, remakes excluded. Columns: match_id, puuid, team_id, game_start, win,
    kills, deaths, assists, champion_id, champion_name, team_position, cs, damage,
    vision_score, ai_score, model_version, game_duration."""
    mp = MatchParticipant
    stmt = (
        select(
            mp.match_id,
            mp.puuid,
            mp.team_id,
            mp.game_start,
            mp.win,
            mp.kills,
            mp.deaths,
            mp.assists,
            mp.champion_id,
            mp.champion_name,
            mp.team_position,
            (mp.total_minions_killed + mp.neutral_minions_killed).label("cs"),
            mp.total_damage_dealt_to_champions.label("damage"),
            mp.vision_score,
            mp.ai_score,
            mp.model_version,
            Match.game_duration,
        )
        .join(Match, Match.match_id == mp.match_id)
        .where(mp.queue_id.in_(sorted(queues)), queries.not_remake())
    )
    if since is not None:
        stmt = stmt.where(mp.game_start >= since)
    if puuids is not None:
        stmt = stmt.where(mp.puuid.in_(list(puuids)))
    return stmt


def _ai_filter(
    model_version_column: ColumnElement[str | None], version: str | None
) -> ColumnElement[bool]:
    """FILTER condition selecting scores of ``version`` (nothing when version is None)."""
    return model_version_column == version if version is not None else false()


def _per_minute_sql(
    value: ColumnElement[int], duration: ColumnElement[int]
) -> ColumnElement[float]:
    return cast(value, Float) * 60.0 / func.nullif(duration, 0)


# --- profile -------------------------------------------------------------------------------


async def season_stats(
    session: AsyncSession, puuid: str, *, since: datetime, model_version: str | None
) -> ProfileStats:
    """Season aggregates over ranked queues for one player (one query)."""
    mine = stat_rows(queues=RANKED_QUEUES, since=since, puuids=[puuid]).cte("mine")
    mp = aliased(MatchParticipant)
    team = (
        select(mp.match_id, mp.team_id, func.sum(mp.kills).label("team_kills"))
        .join(mine, and_(mine.c.match_id == mp.match_id, mine.c.team_id == mp.team_id))
        .group_by(mp.match_id, mp.team_id)
        .cte("team")
    )
    kp = func.coalesce(
        func.least(
            cast(mine.c.kills + mine.c.assists, Float) / func.nullif(team.c.team_kills, 0), 1.0
        ),
        0.0,
    )
    ai = _ai_filter(mine.c.model_version, model_version)
    stmt = select(
        func.count().label("games"),
        func.count().filter(mine.c.win.is_(True)).label("wins"),
        func.sum(mine.c.kills).label("kills"),
        func.sum(mine.c.deaths).label("deaths"),
        func.sum(mine.c.assists).label("assists"),
        func.avg(_per_minute_sql(mine.c.cs, mine.c.game_duration)).label("cs_per_min"),
        func.avg(_per_minute_sql(mine.c.damage, mine.c.game_duration)).label("damage_per_min"),
        func.avg(_per_minute_sql(mine.c.vision_score, mine.c.game_duration)).label(
            "vision_per_min"
        ),
        func.avg(kp).label("kill_participation"),
        func.avg(mine.c.ai_score).filter(ai).label("ai_score"),
        func.count(mine.c.ai_score).filter(ai).label("ai_games"),
    ).select_from(
        mine.join(team, and_(team.c.match_id == mine.c.match_id, team.c.team_id == mine.c.team_id))
    )
    row = (await session.execute(stmt)).mappings().one()
    games, wins = to_int(row["games"]), to_int(row["wins"])
    kills, deaths, assists = to_int(row["kills"]), to_int(row["deaths"]), to_int(row["assists"])
    return ProfileStats(
        games=games,
        wins=wins,
        losses=games - wins,
        winrate=winrate(wins, games),
        avg_kills=rounded(safe_div(kills, games)),
        avg_deaths=rounded(safe_div(deaths, games)),
        avg_assists=rounded(safe_div(assists, games)),
        kda=total_kda(kills, deaths, assists),
        avg_cs_per_min=rounded(to_float(row["cs_per_min"])),
        avg_damage_per_min=rounded(to_float(row["damage_per_min"])),
        avg_vision_per_min=rounded(to_float(row["vision_per_min"])),
        avg_kill_participation=rounded(clamp_rate(to_float(row["kill_participation"])) or 0.0),
        avg_ai_score=clamp_rate(to_optional_float(row["ai_score"])),
        ai_scored_games=to_int(row["ai_games"]),
    )


async def champion_stats(
    session: AsyncSession,
    puuid: str,
    *,
    since: datetime,
    model_version: str | None,
    limit: int = TOP_CHAMPIONS,
) -> list[ChampionStat]:
    """Most played champions this season (ranked), most games first."""
    mine = stat_rows(queues=RANKED_QUEUES, since=since, puuids=[puuid]).subquery("mine")
    games = func.count()
    wins = func.count().filter(mine.c.win.is_(True))
    ai = _ai_filter(mine.c.model_version, model_version)
    stmt = (
        select(
            mine.c.champion_id,
            func.max(mine.c.champion_name).label("champion_name"),
            games.label("games"),
            wins.label("wins"),
            func.sum(mine.c.kills).label("kills"),
            func.sum(mine.c.deaths).label("deaths"),
            func.sum(mine.c.assists).label("assists"),
            func.avg(mine.c.ai_score).filter(ai).label("ai_score"),
        )
        .group_by(mine.c.champion_id)
        .order_by(games.desc(), wins.desc(), func.max(mine.c.champion_name))
        .limit(limit)
    )
    return [
        ChampionStat(
            champion_id=row["champion_id"],
            champion_name=row["champion_name"],
            games=to_int(row["games"]),
            wins=to_int(row["wins"]),
            winrate=winrate(to_int(row["wins"]), to_int(row["games"])),
            kda=total_kda(to_int(row["kills"]), to_int(row["deaths"]), to_int(row["assists"])),
            avg_ai_score=clamp_rate(to_optional_float(row["ai_score"])),
        )
        for row in (await session.execute(stmt)).mappings()
    ]


async def role_stats(session: AsyncSession, puuid: str, *, since: datetime) -> list[RoleStat]:
    """Games per position this season (ranked), most games first."""
    mine = stat_rows(queues=RANKED_QUEUES, since=since, puuids=[puuid]).subquery("mine")
    games = func.count()
    wins = func.count().filter(mine.c.win.is_(True))
    stmt = (
        select(mine.c.team_position, games.label("games"), wins.label("wins"))
        .group_by(mine.c.team_position)
        .order_by(games.desc(), mine.c.team_position)
    )
    return [
        RoleStat(
            position=present.normalize_position(row["team_position"]),
            games=to_int(row["games"]),
            wins=to_int(row["wins"]),
            winrate=winrate(to_int(row["wins"]), to_int(row["games"])),
        )
        for row in (await session.execute(stmt)).mappings()
    ]


async def recent_form(
    session: AsyncSession, puuid: str, *, limit: int = PROFILE_RECENT_FORM
) -> list[bool]:
    """Win/loss of the player's latest ranked games (any season), newest first."""
    rows = stat_rows(queues=RANKED_QUEUES, since=None, puuids=[puuid]).subquery("mine")
    stmt = (
        select(rows.c.win).order_by(rows.c.game_start.desc(), rows.c.match_id.desc()).limit(limit)
    )
    return [bool(win) for win in (await session.scalars(stmt)).all()]


async def most_played_champion(session: AsyncSession, puuid: str) -> str | None:
    """Data Dragon key of the champion played most across every stored game."""
    mp = MatchParticipant
    stmt = (
        select(mp.champion_name)
        .where(mp.puuid == puuid)
        .group_by(mp.champion_name)
        .order_by(func.count().desc(), func.max(mp.game_start).desc(), mp.champion_name)
        .limit(1)
    )
    return await session.scalar(stmt)


def can_refresh_at(summoner: Summoner, settings: Settings, *, now: datetime) -> datetime | None:
    """When the Update button unlocks (None = now)."""
    if summoner.last_refreshed_at is None:
        return None
    unlock = summoner.last_refreshed_at + timedelta(seconds=settings.ondemand_cooldown_seconds)
    return unlock if unlock > now else None


async def summoner_profile(
    session: AsyncSession,
    settings: Settings,
    summoner: Summoner,
    *,
    model_version: str | None,
    now: datetime,
) -> SummonerProfile:
    """Everything the profile header and overview need (6-7 small queries)."""
    puuid = summoner.puuid
    since = settings.season_start
    ranks = (
        await queries.current_rank_snapshots(session, [puuid], season_start=since, now=now)
    ).get(puuid, {})
    stats = await season_stats(session, puuid, since=since, model_version=model_version)
    champions = await champion_stats(session, puuid, since=since, model_version=model_version)
    roles = await role_stats(session, puuid, since=since)
    form = await recent_form(session, puuid)
    main = champions[0].champion_name if champions else await most_played_champion(session, puuid)
    return SummonerProfile(
        puuid=puuid,
        game_name=summoner.game_name,
        tag_line=summoner.tag_line,
        platform=summoner.platform,
        profile_icon_id=summoner.profile_icon_id,
        summoner_level=summoner.summoner_level,
        is_tracked=summoner.is_tracked,
        tracked_since=summoner.tracked_since,
        last_refreshed_at=summoner.last_refreshed_at,
        can_refresh_at=can_refresh_at(summoner, settings, now=now),
        solo=present.rank_entry(ranks.get(RANKED_SOLO_5x5)),
        flex=present.rank_entry(ranks.get(RANKED_FLEX_SR)),
        stats=stats,
        top_champions=champions,
        roles=roles,
        recent_form=form,
        main_champion=main,
    )


# --- leaderboard ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Totals:
    games: int = 0
    wins: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    ai_score: float | None = None


async def _leaderboard_totals(
    session: AsyncSession, rows: Select, *, model_version: str | None
) -> dict[str, _Totals]:
    sq = rows.subquery("rows")
    ai = _ai_filter(sq.c.model_version, model_version)
    stmt = select(
        sq.c.puuid,
        func.count().label("games"),
        func.count().filter(sq.c.win.is_(True)).label("wins"),
        func.sum(sq.c.kills).label("kills"),
        func.sum(sq.c.deaths).label("deaths"),
        func.sum(sq.c.assists).label("assists"),
        func.avg(sq.c.ai_score).filter(ai).label("ai_score"),
    ).group_by(sq.c.puuid)
    return {
        row["puuid"]: _Totals(
            games=to_int(row["games"]),
            wins=to_int(row["wins"]),
            kills=to_int(row["kills"]),
            deaths=to_int(row["deaths"]),
            assists=to_int(row["assists"]),
            ai_score=clamp_rate(to_optional_float(row["ai_score"])),
        )
        for row in (await session.execute(stmt)).mappings()
    }


async def best_allies(session: AsyncSession, rows: Select) -> dict[str, BestAlly]:
    """puuid -> the tracked teammate they shared the most games with.

    ``rows`` must already be limited to tracked players, so a self-join on
    ``(match_id, team_id)`` only ever pairs two tracked players on the same side (enemies
    and untracked players never count). Ties: more wins together, then name.
    """
    cte = rows.cte("rows")
    me, ally = cte.alias("me"), cte.alias("ally")
    games = func.count()
    wins = func.count().filter(me.c.win.is_(True))
    pairs = (
        select(
            me.c.puuid.label("puuid"),
            ally.c.puuid.label("ally_puuid"),
            games.label("games"),
            wins.label("wins"),
        )
        .select_from(
            me.join(
                ally,
                and_(
                    ally.c.match_id == me.c.match_id,
                    ally.c.team_id == me.c.team_id,
                    ally.c.puuid != me.c.puuid,
                ),
            )
        )
        .group_by(me.c.puuid, ally.c.puuid)
        .subquery("pairs")
    )
    stmt = (
        select(
            pairs.c.puuid,
            pairs.c.ally_puuid,
            pairs.c.games,
            pairs.c.wins,
            Summoner.game_name,
            Summoner.tag_line,
        )
        .join(Summoner, Summoner.puuid == pairs.c.ally_puuid)
        .order_by(
            pairs.c.puuid,
            pairs.c.games.desc(),
            pairs.c.wins.desc(),
            func.lower(Summoner.game_name),
            pairs.c.ally_puuid,
        )
        .distinct(pairs.c.puuid)
    )
    return {
        row["puuid"]: BestAlly(
            puuid=row["ally_puuid"],
            game_name=row["game_name"],
            tag_line=row["tag_line"],
            games=to_int(row["games"]),
            wins=to_int(row["wins"]),
            winrate=winrate(to_int(row["wins"]), to_int(row["games"])),
        )
        for row in (await session.execute(stmt)).mappings()
    }


async def top_champions_by_player(
    session: AsyncSession, rows: Select, *, limit: int = LEADERBOARD_TOP_CHAMPIONS
) -> dict[str, list[str]]:
    """puuid -> Data Dragon keys of the most played champions (most games first)."""
    sq = rows.subquery("rows")
    games = func.count()
    wins = func.count().filter(sq.c.win.is_(True))
    ranked = (
        select(
            sq.c.puuid,
            sq.c.champion_name,
            func.row_number()
            .over(
                partition_by=sq.c.puuid,
                order_by=(games.desc(), wins.desc(), sq.c.champion_name),
            )
            .label("rn"),
        )
        .group_by(sq.c.puuid, sq.c.champion_name)
        .subquery("ranked")
    )
    stmt = (
        select(ranked.c.puuid, ranked.c.champion_name)
        .where(ranked.c.rn <= limit)
        .order_by(ranked.c.puuid, ranked.c.rn)
    )
    result: dict[str, list[str]] = defaultdict(list)
    for puuid, champion in (await session.execute(stmt)).all():
        result[puuid].append(champion)
    return dict(result)


async def recent_form_by_player(
    session: AsyncSession, rows: Select, *, limit: int = LEADERBOARD_RECENT_FORM
) -> dict[str, list[bool]]:
    """puuid -> win/loss of the latest games in ``rows``, newest first."""
    sq = rows.subquery("rows")
    numbered = select(
        sq.c.puuid,
        sq.c.win,
        func.row_number()
        .over(partition_by=sq.c.puuid, order_by=(sq.c.game_start.desc(), sq.c.match_id.desc()))
        .label("rn"),
    ).subquery("numbered")
    stmt = (
        select(numbered.c.puuid, numbered.c.win)
        .where(numbered.c.rn <= limit)
        .order_by(numbered.c.puuid, numbered.c.rn)
    )
    result: dict[str, list[bool]] = defaultdict(list)
    for puuid, win in (await session.execute(stmt)).all():
        result[puuid].append(bool(win))
    return dict(result)


async def lp_deltas(
    session: AsyncSession, puuids: Sequence[str], *, since: datetime
) -> dict[str, int]:
    """puuid -> rank_value(current solo standing) - rank_value(first solo snapshot at or
    after ``since``). Players without a solo snapshot this season, and players who are no
    longer ranked in solo queue, are left out."""
    baselines = await queries.first_rank_snapshots_since(
        session, puuids, queue_type=RANKED_SOLO_5x5, since=since
    )
    if not baselines:
        return {}
    latest = await queries.current_rank_snapshots(
        session, list(baselines), season_start=since, queue_types=(RANKED_SOLO_5x5,)
    )
    deltas: dict[str, int] = {}
    for puuid, baseline in baselines.items():
        current = latest.get(puuid, {}).get(RANKED_SOLO_5x5)
        if current is not None:
            deltas[puuid] = current.rank_value - baseline.rank_value
    return deltas


def _sort_key(entry: LeaderboardEntry) -> tuple[bool, float, float, int, str, str]:
    """avg AI Score desc (unscored last), then winrate desc, games desc, name."""
    return (
        entry.avg_ai_score is None,
        -(entry.avg_ai_score or 0.0),
        -entry.winrate,
        -entry.games,
        entry.game_name.casefold(),
        entry.tag_line.casefold(),
    )


async def leaderboard(
    session: AsyncSession,
    settings: Settings,
    *,
    queue: LeaderboardQueue,
    model_version: str | None,
) -> Leaderboard:
    """Season leaderboard of every tracked player, including those with no games yet."""
    roster = await queries.tracked_summoners(session)
    entries: list[LeaderboardEntry] = []
    if roster:
        puuids = [s.puuid for s in roster]
        rows = stat_rows(
            queues=LEADERBOARD_QUEUES[queue], since=settings.season_start, puuids=puuids
        )
        totals = await _leaderboard_totals(session, rows, model_version=model_version)
        allies = await best_allies(session, rows)
        champions = await top_champions_by_player(session, rows)
        form = await recent_form_by_player(session, rows)
        ranks = await queries.current_rank_snapshots(
            session, puuids, season_start=settings.season_start
        )
        deltas = await lp_deltas(session, puuids, since=settings.season_start)
        for summoner in roster:
            t = totals.get(summoner.puuid) or _Totals()
            player_ranks = ranks.get(summoner.puuid, {})
            entries.append(
                LeaderboardEntry(
                    puuid=summoner.puuid,
                    game_name=summoner.game_name,
                    tag_line=summoner.tag_line,
                    profile_icon_id=summoner.profile_icon_id,
                    summoner_level=summoner.summoner_level,
                    solo=present.rank_entry(player_ranks.get(RANKED_SOLO_5x5)),
                    flex=present.rank_entry(player_ranks.get(RANKED_FLEX_SR)),
                    games=t.games,
                    wins=t.wins,
                    losses=t.games - t.wins,
                    winrate=winrate(t.wins, t.games),
                    kda=total_kda(t.kills, t.deaths, t.assists),
                    avg_kills=rounded(safe_div(t.kills, t.games)),
                    avg_deaths=rounded(safe_div(t.deaths, t.games)),
                    avg_assists=rounded(safe_div(t.assists, t.games)),
                    avg_ai_score=t.ai_score,
                    lp_delta=deltas.get(summoner.puuid),
                    best_ally=allies.get(summoner.puuid),
                    top_champions=champions.get(summoner.puuid, []),
                    recent_form=form.get(summoner.puuid, []),
                )
            )
        entries.sort(key=_sort_key)
    return Leaderboard(
        season_start=settings.season_start,
        model_version=model_version,
        queue=queue,
        entries=entries,
    )
