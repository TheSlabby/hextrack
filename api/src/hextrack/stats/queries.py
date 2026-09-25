"""Read-side lookups and row fetches used by the HTTP routes.

Every function takes an open :class:`AsyncSession`, only reads, and never commits.
"""

from __future__ import annotations

import base64
import binascii
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy import ColumnElement, and_, false, func, not_, or_, select, tuple_
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.api.schemas import MatchDetail, MatchPage
from hextrack.db.models import AiModel, Match, MatchParticipant, RankSnapshot, Summoner
from hextrack.ingest.mapping import CLASSIC, GAME_COMPLETE, MIN_COMPLETE_DURATION_SECONDS
from hextrack.queues import RANKED_QUEUES
from hextrack.rank import RANK_HEARTBEAT_INTERVAL, RANKED_QUEUE_TYPES
from hextrack.riotid import has_control_characters, normalize_game_name, normalize_tag_line
from hextrack.stats import present
from hextrack.stats.metrics import REMAKE_MAX_SECONDS

if TYPE_CHECKING:
    from hextrack.hextrack_ai.inference import Scorer
    from hextrack.stats.role_percentile import RolePercentileTable

#: ``match_participants`` columns the response builders in :mod:`hextrack.stats.present`
#: read (``raw``-free, so a page of 20 matches moves ~200 narrow rows).
PARTICIPANT_COLUMNS: Final = (
    MatchParticipant.match_id,
    MatchParticipant.puuid,
    MatchParticipant.participant_id,
    MatchParticipant.team_id,
    MatchParticipant.riot_id_game_name,
    MatchParticipant.riot_id_tagline,
    MatchParticipant.team_position,
    MatchParticipant.player_subteam_id,
    MatchParticipant.placement,
    MatchParticipant.champion_id,
    MatchParticipant.champion_name,
    MatchParticipant.champ_level,
    MatchParticipant.win,
    MatchParticipant.kills,
    MatchParticipant.deaths,
    MatchParticipant.assists,
    MatchParticipant.total_minions_killed,
    MatchParticipant.neutral_minions_killed,
    MatchParticipant.gold_earned,
    MatchParticipant.total_damage_dealt_to_champions,
    MatchParticipant.total_damage_taken,
    MatchParticipant.vision_score,
    MatchParticipant.wards_placed,
    MatchParticipant.wards_killed,
    MatchParticipant.vision_wards_bought,
    MatchParticipant.items,
    MatchParticipant.summoner1_id,
    MatchParticipant.summoner2_id,
    MatchParticipant.largest_multi_kill,
    MatchParticipant.ai_score,
    MatchParticipant.model_version,
)
#: Real tag lines are alphanumeric; ingestion appends "~<puuid prefix>" to the tag of an
#: account that no longer exists so its Riot ID can be reused.
PARKED_TAG_MARKER: Final = "~"
#: ``matches`` columns of a match-history item.
MATCH_HEADER_COLUMNS: Final = (
    Match.match_id,
    Match.queue_id,
    Match.game_mode,
    Match.game_start,
    Match.game_duration,
    Match.patch,
    Match.remake,
)


# --- shared SQL predicates -------------------------------------------------------------------


def remake_clause() -> ColumnElement[bool]:
    """``matches`` row is a remake (early surrender or shorter than 5 minutes)."""
    return or_(Match.remake.is_(True), Match.game_duration < REMAKE_MAX_SECONDS)


def not_remake() -> ColumnElement[bool]:
    return not_(remake_clause())


def scorable_clause() -> ColumnElement[bool]:
    """SQL form of :func:`hextrack.ingest.mapping.is_scorable` over ``matches``."""
    return and_(
        Match.game_mode == CLASSIC,
        Match.remake.is_(False),
        or_(
            Match.end_of_game_result == GAME_COMPLETE,
            and_(
                Match.end_of_game_result.is_(None),
                Match.game_duration > MIN_COMPLETE_DURATION_SECONDS,
            ),
        ),
    )


def _is_tracked_column() -> ColumnElement[bool]:
    return func.coalesce(Summoner.is_tracked, false()).label("is_tracked")


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- summoners -------------------------------------------------------------------------------


async def find_summoner_by_riot_id(
    session: AsyncSession, game_name: str, tag_line: str, *, platform: str
) -> Summoner | None:
    """Case-insensitive Riot ID lookup (uses ``uq_summoners_riot_id_lower``)."""
    name, tag = normalize_game_name(game_name), normalize_tag_line(tag_line)
    stmt = select(Summoner).where(
        func.lower(Summoner.game_name) == func.lower(name),
        func.lower(Summoner.tag_line) == func.lower(tag),
        Summoner.platform == platform,
    )
    return await session.scalar(stmt)


async def get_summoner(session: AsyncSession, puuid: str) -> Summoner | None:
    return await session.get(Summoner, puuid)


async def summoner_exists(session: AsyncSession, puuid: str) -> bool:
    found = await session.scalar(select(Summoner.puuid).where(Summoner.puuid == puuid))
    return found is not None


async def tracked_summoners(session: AsyncSession) -> list[Summoner]:
    """The roster, ordered by Riot ID (case-insensitive)."""
    stmt = (
        select(Summoner)
        .where(Summoner.is_tracked.is_(True))
        .order_by(func.lower(Summoner.game_name), func.lower(Summoner.tag_line), Summoner.puuid)
    )
    return list((await session.scalars(stmt)).all())


async def search_summoners(session: AsyncSession, query: str, *, limit: int) -> list[Summoner]:
    """Case-insensitive contains-match on the game name, or on ``name#tag`` when the query
    contains "#". Tracked players first, then prefix matches, then shorter names."""
    name_part, sep, tag_part = query.strip().rpartition("#")
    if sep:
        needle = normalize_game_name(name_part) + "#" + normalize_tag_line(tag_part)
        target = func.lower(Summoner.game_name + "#" + Summoner.tag_line)
    else:
        needle = normalize_game_name(query)
        target = func.lower(Summoner.game_name)
    if not needle.strip("#"):
        return []
    escaped = _like_escape(needle)
    contains = target.like(func.lower(f"%{escaped}%"), escape="\\")
    prefix = target.like(func.lower(f"{escaped}%"), escape="\\")
    stmt = (
        select(Summoner)
        # Accounts deleted at Riot keep their rows with a parked, unusable tag
        # ("TAG~puuid8", see hextrack.ingest.service); they are not searchable players.
        .where(contains, not_(Summoner.tag_line.contains(PARKED_TAG_MARKER, autoescape=True)))
        .order_by(
            Summoner.is_tracked.desc(),
            prefix.desc(),
            func.length(Summoner.game_name),
            func.lower(Summoner.game_name),
            func.lower(Summoner.tag_line),
            Summoner.puuid,
        )
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


# --- ranks -----------------------------------------------------------------------------------


async def latest_rank_snapshots(
    session: AsyncSession,
    puuids: Collection[str],
    *,
    queue_types: Collection[str] = RANKED_QUEUE_TYPES,
) -> dict[str, dict[str, RankSnapshot]]:
    """puuid -> queue_type -> newest snapshot (one ``DISTINCT ON`` query)."""
    if not puuids:
        return {}
    stmt = (
        select(RankSnapshot)
        .where(
            RankSnapshot.puuid.in_(list(puuids)),
            RankSnapshot.queue_type.in_(list(queue_types)),
        )
        .order_by(
            RankSnapshot.puuid,
            RankSnapshot.queue_type,
            RankSnapshot.taken_at.desc(),
            RankSnapshot.id.desc(),
        )
        .distinct(RankSnapshot.puuid, RankSnapshot.queue_type)
    )
    result: dict[str, dict[str, RankSnapshot]] = defaultdict(dict)
    for snapshot in (await session.scalars(stmt)).all():
        result[snapshot.puuid][snapshot.queue_type] = snapshot
    return dict(result)


#: How far a snapshot may lag behind the summoner's last refresh and still count as their
#: current standing. A refreshed ranked queue gets a heartbeat row every
#: :data:`RANK_HEARTBEAT_INTERVAL`; twice that leaves room for a worker that was catching up
#: while the row was written.
RANK_STALE_AFTER: Final = 2 * RANK_HEARTBEAT_INTERVAL


def is_current_rank(
    snapshot: RankSnapshot,
    *,
    last_refreshed_at: datetime | None,
    season_start: datetime,
    now: datetime,
) -> bool:
    """Whether a stored snapshot still describes the player's standing today.

    league-v4 returns nothing at all for a queue the player is unranked in, so an old row
    simply stays the newest one; showing it would report last season's rank (or the rank
    before a season reset) as current. Two things rule that out:

    * the snapshot was taken before the current season started, so it cannot describe it;
    * the summoner has been refreshed since, well past the heartbeat interval: every queue
      Riot still reports gets a row at least that often (see
      :func:`hextrack.ingest.service.snapshot_action`), so a much older row means the queue
      was missing from the answer, i.e. the player is unranked there.
    """
    if season_start <= now and snapshot.taken_at < season_start:
        return False
    if last_refreshed_at is None:
        return True
    return snapshot.taken_at > last_refreshed_at - RANK_STALE_AFTER


async def current_rank_snapshots(
    session: AsyncSession,
    puuids: Collection[str],
    *,
    season_start: datetime,
    queue_types: Collection[str] = RANKED_QUEUE_TYPES,
    now: datetime | None = None,
) -> dict[str, dict[str, RankSnapshot]]:
    """:func:`latest_rank_snapshots` restricted to snapshots that are still current
    (:func:`is_current_rank`); a player who is unranked in a queue simply has no entry."""
    latest = await latest_rank_snapshots(session, puuids, queue_types=queue_types)
    if not latest:
        return {}
    rows = await session.execute(
        select(Summoner.puuid, Summoner.last_refreshed_at).where(Summoner.puuid.in_(list(latest)))
    )
    refreshed = {puuid: refreshed_at for puuid, refreshed_at in rows.all()}
    at = now or datetime.now(UTC)
    current: dict[str, dict[str, RankSnapshot]] = {}
    for puuid, by_queue in latest.items():
        kept = {
            queue_type: snapshot
            for queue_type, snapshot in by_queue.items()
            if is_current_rank(
                snapshot,
                last_refreshed_at=refreshed.get(puuid),
                season_start=season_start,
                now=at,
            )
        }
        if kept:
            current[puuid] = kept
    return current


async def first_rank_snapshots_since(
    session: AsyncSession, puuids: Collection[str], *, queue_type: str, since: datetime
) -> dict[str, RankSnapshot]:
    """puuid -> oldest snapshot of ``queue_type`` taken at or after ``since``."""
    if not puuids:
        return {}
    stmt = (
        select(RankSnapshot)
        .where(
            RankSnapshot.puuid.in_(list(puuids)),
            RankSnapshot.queue_type == queue_type,
            RankSnapshot.taken_at >= since,
        )
        .order_by(RankSnapshot.puuid, RankSnapshot.taken_at, RankSnapshot.id)
        .distinct(RankSnapshot.puuid)
    )
    return {s.puuid: s for s in (await session.scalars(stmt)).all()}


async def rank_history(session: AsyncSession, puuid: str, queue_type: str) -> list[RankSnapshot]:
    """Every snapshot of one queue, oldest first."""
    stmt = (
        select(RankSnapshot)
        .where(RankSnapshot.puuid == puuid, RankSnapshot.queue_type == queue_type)
        .order_by(RankSnapshot.taken_at, RankSnapshot.id)
    )
    return list((await session.scalars(stmt)).all())


# --- match history cursor --------------------------------------------------------------------

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND: Final = timedelta(microseconds=1)


class InvalidCursor(ValueError):
    """The ``cursor`` query parameter was not produced by :func:`encode_cursor`."""


@dataclass(frozen=True, slots=True)
class MatchCursor:
    """Keyset position: the last item of the previous page."""

    game_start: datetime
    match_id: str


def encode_cursor(cursor: MatchCursor) -> str:
    """Opaque URL-safe token for ``(game_start, match_id)`` (microsecond exact)."""
    micros = (cursor.game_start - _EPOCH) // _MICROSECOND
    payload = f"{micros}|{cursor.match_id}".encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_cursor(token: str) -> MatchCursor:
    """Inverse of :func:`encode_cursor`; raises :class:`InvalidCursor`.

    The decoded match id is checked for control characters: a handcrafted cursor carrying a
    NUL byte would otherwise reach asyncpg as invalid UTF-8 and fail the query.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        micros_text, sep, match_id = payload.partition("|")
        if not sep or not match_id or not micros_text.lstrip("-").isdigit():
            raise InvalidCursor("malformed cursor")
        if has_control_characters(match_id):
            raise InvalidCursor("malformed cursor")
        game_start = _EPOCH + int(micros_text) * _MICROSECOND
    except (binascii.Error, UnicodeError, ValueError, OverflowError) as exc:
        raise InvalidCursor("malformed cursor") from exc
    return MatchCursor(game_start=game_start, match_id=match_id)


# --- matches ---------------------------------------------------------------------------------


async def participants_for_matches(
    session: AsyncSession, match_ids: Sequence[str]
) -> dict[str, list[RowMapping]]:
    """match_id -> every participant row (with ``is_tracked``), in one query."""
    if not match_ids:
        return {}
    stmt = (
        select(*PARTICIPANT_COLUMNS, _is_tracked_column())
        .outerjoin(Summoner, Summoner.puuid == MatchParticipant.puuid)
        .where(MatchParticipant.match_id.in_(list(match_ids)))
        .order_by(MatchParticipant.match_id, MatchParticipant.participant_id)
    )
    grouped: dict[str, list[RowMapping]] = defaultdict(list)
    for row in (await session.execute(stmt)).mappings():
        grouped[row["match_id"]].append(row)
    return dict(grouped)


async def match_page(
    session: AsyncSession,
    puuid: str,
    *,
    cursor: MatchCursor | None,
    limit: int,
    queue: int | Collection[int] | None,
    role_percentiles: RolePercentileTable | None = None,
) -> MatchPage:
    """One page of a player's history, newest first, keyset-paginated on
    ``(game_start desc, match_id desc)``. Two queries: the page's matches, then all of
    their participants. ``queue`` filters on one queue id or any of several (an empty
    collection means no filter). ``role_percentiles`` fills ``ai_role_percentile``."""
    mp = MatchParticipant
    stmt = (
        # The keyset is the indexed (puuid, game_start) copy on match_participants.
        select(*MATCH_HEADER_COLUMNS, mp.game_start.label("sort_start"))
        .join(mp, mp.match_id == Match.match_id)
        .where(mp.puuid == puuid, mp.team_id.in_(present.TEAM_IDS))
        .order_by(mp.game_start.desc(), mp.match_id.desc())
        .limit(limit + 1)
    )
    queues = sorted({queue} if isinstance(queue, int) else set(queue or ()))
    if len(queues) == 1:
        stmt = stmt.where(mp.queue_id == queues[0])
    elif queues:
        stmt = stmt.where(mp.queue_id.in_(queues))
    if cursor is not None:
        stmt = stmt.where(
            # The plain range lets Postgres seek the (puuid, game_start desc) index; the row
            # comparison breaks ties between games that started at the same instant.
            mp.game_start <= cursor.game_start,
            tuple_(mp.game_start, mp.match_id) < tuple_(cursor.game_start, cursor.match_id),
        )
    headers = list((await session.execute(stmt)).mappings())
    has_more = len(headers) > limit
    headers = headers[:limit]

    participants = await participants_for_matches(session, [h["match_id"] for h in headers])
    items = []
    for header in headers:
        item = present.match_summary(
            header, participants.get(header["match_id"], []), puuid, role_percentiles
        )
        if item is not None:
            items.append(item)
    next_cursor = (
        encode_cursor(MatchCursor(headers[-1]["sort_start"], headers[-1]["match_id"]))
        if has_more and headers
        else None
    )
    return MatchPage(items=items, next_cursor=next_cursor)


async def match_detail(
    session: AsyncSession,
    match_id: str,
    *,
    role_percentiles: RolePercentileTable | None = None,
) -> MatchDetail | None:
    """Both teams of one stored match; only ``raw -> info -> teams`` is read from the raw
    payload (objectives and bans). ``role_percentiles`` fills ``ai_role_percentile``."""
    stmt = select(
        Match.match_id,
        Match.queue_id,
        Match.game_mode,
        Match.game_version,
        Match.patch,
        Match.game_start,
        Match.game_duration,
        Match.remake,
        Match.model_version,
        Match.raw["info"]["teams"].label("raw_teams"),
    ).where(Match.match_id == match_id)
    header = (await session.execute(stmt)).mappings().first()
    if header is None:
        return None
    participants = await participants_for_matches(session, [match_id])
    return present.match_detail(header, participants.get(match_id, []), role_percentiles)


# --- AI Score --------------------------------------------------------------------------------


async def active_model_version(session: AsyncSession) -> str | None:
    return await session.scalar(select(AiModel.version).where(AiModel.is_active.is_(True)))


async def latest_scored_version(session: AsyncSession, puuid: str) -> str | None:
    """Model version of the player's most recently scored game."""
    stmt = (
        select(MatchParticipant.model_version)
        .where(
            MatchParticipant.puuid == puuid,
            MatchParticipant.ai_score.is_not(None),
            MatchParticipant.model_version.is_not(None),
        )
        .order_by(
            MatchParticipant.ai_scored_at.desc().nulls_last(),
            MatchParticipant.game_start.desc(),
        )
        .limit(1)
    )
    return await session.scalar(stmt)


async def resolve_model_version(
    session: AsyncSession, scorer: Scorer | None, *, puuid: str | None = None
) -> str | None:
    """The model version whose stored scores an average may use.

    The ``ai_models`` row marked active wins; otherwise the loaded model; otherwise (only
    when ``puuid`` is given) the version of that player's most recently scored game.
    """
    version = await active_model_version(session)
    if version is None and scorer is not None:
        version = scorer.version
    if version is None and puuid is not None:
        version = await latest_scored_version(session, puuid)
    return version


async def ai_trend_rows(
    session: AsyncSession, puuid: str, *, model_version: str, limit: int
) -> list[RowMapping]:
    """The player's ``limit`` most recent games scored by ``model_version``, oldest first."""
    stmt = (
        select(
            MatchParticipant.match_id,
            MatchParticipant.game_start,
            MatchParticipant.champion_name,
            MatchParticipant.win,
            MatchParticipant.ai_score,
        )
        .where(
            MatchParticipant.puuid == puuid,
            MatchParticipant.ai_score.is_not(None),
            MatchParticipant.model_version == model_version,
        )
        .order_by(MatchParticipant.game_start.desc(), MatchParticipant.match_id.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).mappings())
    rows.reverse()
    return rows


async def explain_rows(
    session: AsyncSession,
    puuid: str,
    *,
    limit: int,
    queues: Collection[int] = RANKED_QUEUES,
) -> list[tuple[MatchParticipant, int]]:
    """The player's ``limit`` most recent scorable games as (participant row, game duration
    in seconds), newest first."""
    stmt = (
        select(MatchParticipant, Match.game_duration)
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(
            MatchParticipant.puuid == puuid,
            MatchParticipant.queue_id.in_(sorted(queues)),
            scorable_clause(),
        )
        .order_by(MatchParticipant.game_start.desc(), MatchParticipant.match_id.desc())
        .limit(limit)
    )
    return [(row[0], int(row[1])) for row in (await session.execute(stmt)).all()]


async def explain_row(
    session: AsyncSession, match_id: str, puuid: str
) -> tuple[MatchParticipant, int, bool] | None:
    """One player's line in one match as (participant row, game duration in seconds,
    scorable), or None when they didn't play in it."""
    stmt = (
        select(MatchParticipant, Match.game_duration, scorable_clause())
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(MatchParticipant.match_id == match_id, MatchParticipant.puuid == puuid)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return row[0], int(row[1]), bool(row[2])


__all__ = [
    "InvalidCursor",
    "explain_row",
    "MATCH_HEADER_COLUMNS",
    "MatchCursor",
    "PARKED_TAG_MARKER",
    "PARTICIPANT_COLUMNS",
    "RANK_STALE_AFTER",
    "active_model_version",
    "ai_trend_rows",
    "current_rank_snapshots",
    "decode_cursor",
    "encode_cursor",
    "explain_rows",
    "find_summoner_by_riot_id",
    "first_rank_snapshots_since",
    "get_summoner",
    "is_current_rank",
    "latest_rank_snapshots",
    "latest_scored_version",
    "match_detail",
    "match_page",
    "not_remake",
    "participants_for_matches",
    "rank_history",
    "remake_clause",
    "resolve_model_version",
    "scorable_clause",
    "search_summoners",
    "summoner_exists",
    "tracked_summoners",
]
