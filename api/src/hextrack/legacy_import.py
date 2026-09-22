"""Import legacy data (Neon ``Matches`` table, LPBot SQLite, players.txt) (owner: B6).

Every match goes through ``hextrack.ingest.service.ingest_match_json`` (enqueue_events=False)
so validation and scoring are identical to live ingestion. Idempotent.

Sources (any combination):

* **LPBot SQLite** (``LPBot/src/MatchDB.cpp``): ``matches(id, match_json)`` are ingested;
  ``puuids(player_name, puuid)`` maps players.txt lines ("Name#TAG") to puuids;
  ``player_data(timestamp ms, puuid, rank, tier, lp, wins, losses)`` holds the solo queue
  standing LPBot recorded on every poll. Those rows are collapsed to what the new poller
  stores: a snapshot when the standing changed plus a heartbeat after 24 unchanged hours.
  The file is opened read-only.
* **Neon Postgres** (``prisma/schema.prisma``): ``"Matches"("matchId", data)`` are ingested;
  each ``"RiotAccount"`` becomes a summoner (Riot ID, icon parsed from ``profileIconURL``,
  level) with one snapshot per ranked queue in ``rankedInfo``, taken at ``lastUpdate``. Table
  names are resolved through the connection's ``search_path`` (add
  ``?options=-csearch_path%3Dmyschema`` to the URL for a non-default schema).
* **players.txt**: one "Name#TAG" per line marks a tracked summoner. Lines are resolved to a
  puuid through the SQLite ``puuids`` table, then stored summoners, then the Riot IDs seen in
  match participants (newest game wins). No Riot API calls are made.

Corrupt match rows (unparsable JSON, Riot error bodies, payloads without
``info.participants``) are skipped and counted in ``matches_invalid``. Re-running an import
creates nothing new: matches are ``ON CONFLICT DO NOTHING``, snapshots are de-duplicated on
(puuid, queue, taken_at) and summoner rows are only created or have missing fields filled.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import psycopg
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.config import Settings
from hextrack.db.engine import make_async_engine, make_session_factory
from hextrack.db.models import MatchParticipant, RankSnapshot, Summoner
from hextrack.ingest.context import IngestContext
from hextrack.ingest.mapping import InvalidMatchPayload, ms_to_datetime
from hextrack.ingest.service import ingest_match_json
from hextrack.rank import (
    APEX_TIERS,
    DIVISION_ORDER,
    RANKED_QUEUE_TYPES,
    RANKED_SOLO_5x5,
    normalize_tier,
    rank_value,
)
from hextrack.riot.client import RiotClient
from hextrack.riotid import InvalidRiotId, RiotId, parse_riot_id, riot_id_key

if TYPE_CHECKING:
    from hextrack.hextrack_ai.inference import Scorer

logger = logging.getLogger(__name__)

#: Commit after this many ingested matches.
COMMIT_EVERY: Final = 100
#: Rows fetched per SQLite round trip.
SQLITE_BATCH: Final = 200
#: An unchanged standing is re-recorded after this long (matches the poller).
HEARTBEAT_INTERVAL: Final = timedelta(hours=24)
#: Only the first N error messages are kept in the report (all are counted/logged).
MAX_ERROR_MESSAGES: Final = 200
_PROFILE_ICON_RE: Final = re.compile(r"/profileicon/(\d+)\.(?:png|jpg|webp)", re.IGNORECASE)
_DB_URL_SCHEME_RE: Final = re.compile(r"^postgres(?:ql)?(?:\+\w+)?://")


@dataclass(slots=True)
class ImportReport:
    matches_seen: int = 0
    matches_created: int = 0
    matches_skipped_existing: int = 0
    matches_invalid: int = 0
    rank_snapshots_created: int = 0
    summoners_tracked: int = 0
    errors: list[str] = field(default_factory=list)
    #: Newly created matches that were AI-scored.
    matches_scored: int = 0
    #: Summoner rows created from legacy accounts / puuids / rank history.
    summoners_created: int = 0
    #: Legacy rank rows read (LPBot player_data rows + Neon rankedInfo entries).
    rank_rows_seen: int = 0
    #: Collapsed snapshots that were already stored (re-import).
    rank_snapshots_skipped_existing: int = 0
    #: players.txt lines that could not be matched to a puuid.
    players_unresolved: int = 0

    def error(self, message: str) -> None:
        logger.warning("legacy import: %s", message)
        if len(self.errors) < MAX_ERROR_MESSAGES:
            self.errors.append(message)
        elif len(self.errors) == MAX_ERROR_MESSAGES:
            self.errors.append("... further errors omitted (see the log)")


# --- collected legacy state ------------------------------------------------------------------


@dataclass(slots=True)
class _Identity:
    """What a legacy source says about an account."""

    riot_id: RiotId | None = None
    profile_icon_id: int | None = None
    summoner_level: int | None = None
    last_refreshed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class _RankRow:
    puuid: str
    queue_type: str
    tier: str
    rank: str | None
    lp: int
    wins: int
    losses: int
    taken_at: datetime
    is_heartbeat: bool = False

    @property
    def standing(self) -> tuple[str, str | None, int, int, int]:
        return (self.tier, self.rank, self.lp, self.wins, self.losses)


@dataclass(slots=True)
class _Legacy:
    #: players.txt line (as LPBot stored it) -> puuid, from the SQLite ``puuids`` table.
    puuid_by_player_line: dict[str, str] = field(default_factory=dict)
    identities: dict[str, _Identity] = field(default_factory=dict)
    rank_rows: list[_RankRow] = field(default_factory=list)

    def identity(self, puuid: str) -> _Identity:
        return self.identities.setdefault(puuid, _Identity())


# --- helpers ---------------------------------------------------------------------------------


def _parse_riot_id(value: object) -> RiotId | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_riot_id(value)
    except InvalidRiotId:
        return None


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return default


def _epoch_to_datetime(value: object) -> datetime | None:
    """LPBot stores epoch milliseconds; tolerate seconds too."""
    ts = _as_int(value, default=-1)
    if ts <= 0:
        return None
    return ms_to_datetime(ts if ts >= 100_000_000_000 else ts * 1000)


def _aware(value: object) -> datetime | None:
    """Prisma ``DateTime`` columns are ``timestamp(3)`` without zone, in UTC."""
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _normalize_standing(tier: object, rank: object) -> tuple[str, str | None] | None:
    if not isinstance(tier, str) or not tier.strip():
        return None
    try:
        t = normalize_tier(tier)
    except ValueError:
        return None
    if t in APEX_TIERS:
        return t, None
    r = rank.strip().upper() if isinstance(rank, str) else ""
    if r not in DIVISION_ORDER:
        return None
    return t, r


def _load_json(value: object) -> object:
    if isinstance(value, bytes | bytearray | memoryview):
        value = bytes(value).decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


class RankCollapser:
    """Streaming change-only filter for legacy rank rows (LPBot stored one per poll).

    :meth:`push` returns the row to keep, or None: a row is kept when the standing changed
    since the last kept row of that (puuid, queue), or as a heartbeat once
    :data:`HEARTBEAT_INTERVAL` passed without a change. Rows of one (puuid, queue) must
    arrive in time order. Memory is one row per (puuid, queue).
    """

    def __init__(self) -> None:
        self._last: dict[tuple[str, str], _RankRow] = {}

    def push(self, row: _RankRow) -> _RankRow | None:
        key = (row.puuid, row.queue_type)
        previous = self._last.get(key)
        if previous is None or previous.standing != row.standing:
            kept = row
        elif row.taken_at - previous.taken_at >= HEARTBEAT_INTERVAL:
            kept = replace(row, is_heartbeat=True)
        else:
            return None
        self._last[key] = kept
        return kept


def collapse_rank_rows(rows: Iterable[_RankRow]) -> Iterator[_RankRow]:
    """:class:`RankCollapser` over an iterable (sorted by time within each puuid/queue)."""
    collapser = RankCollapser()
    for row in rows:
        kept = collapser.push(row)
        if kept is not None:
            yield kept


def libpq_url(url: str) -> str:
    """SQLAlchemy-style URL (``postgresql+asyncpg://``) -> libpq URL for psycopg."""
    return _DB_URL_SCHEME_RE.sub("postgresql://", url.strip(), count=1)


# --- match ingestion -------------------------------------------------------------------------


async def _ingest(
    ctx: IngestContext,
    session: AsyncSession,
    report: ImportReport,
    source: str,
    row_id: object,
    payload: object,
) -> None:
    report.matches_seen += 1
    try:
        raw = _load_json(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        report.matches_invalid += 1
        report.error(f"{source} match {row_id}: unparsable JSON ({exc})")
        return
    info = raw.get("info") if isinstance(raw, dict) else None
    if not isinstance(raw, dict) or not isinstance(info, dict) or not info.get("participants"):
        report.matches_invalid += 1
        report.error(f"{source} match {row_id}: corrupt row without info.participants")
        return
    try:
        result = await ingest_match_json(ctx, session, raw, enqueue_events=False)
    except InvalidMatchPayload as exc:
        report.matches_invalid += 1
        report.error(f"{source} match {row_id}: {exc}")
        return
    if result.created:
        report.matches_created += 1
        report.matches_scored += 1 if result.scored else 0
    else:
        report.matches_skipped_existing += 1
    if (report.matches_created + report.matches_skipped_existing) % COMMIT_EVERY == 0:
        await session.commit()


# --- LPBot SQLite ----------------------------------------------------------------------------


def _open_sqlite(path: Path) -> sqlite3.Connection:
    uri = path.expanduser().resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, check_same_thread=False)


def _sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(r[0]) for r in rows}


async def _sqlite_rows(conn: sqlite3.Connection, query: str) -> AsyncIterator[tuple[Any, ...]]:
    cursor = await asyncio.to_thread(conn.execute, query)
    try:
        while True:
            batch = await asyncio.to_thread(cursor.fetchmany, SQLITE_BATCH)
            if not batch:
                return
            for row in batch:
                yield tuple(row)
    finally:
        cursor.close()


async def _import_sqlite(
    ctx: IngestContext,
    session: AsyncSession,
    path: Path,
    legacy: _Legacy,
    report: ImportReport,
) -> None:
    conn = await asyncio.to_thread(_open_sqlite, path)
    try:
        tables = await asyncio.to_thread(_sqlite_tables, conn)
        for required in ("matches", "puuids", "player_data"):
            if required not in tables:
                report.error(f"sqlite: table {required!r} not found in {path}")

        if "puuids" in tables:
            async for player_name, puuid in _sqlite_rows(
                conn, "SELECT player_name, puuid FROM puuids"
            ):
                if not isinstance(puuid, str) or not puuid.strip():
                    continue
                puuid = puuid.strip()
                line = str(player_name or "").strip()
                if line:
                    legacy.puuid_by_player_line[line] = puuid
                ident = legacy.identity(puuid)
                ident.riot_id = ident.riot_id or _parse_riot_id(line)

        if "matches" in tables:
            async for row_id, match_json in _sqlite_rows(
                conn, "SELECT id, match_json FROM matches ORDER BY rowid"
            ):
                await _ingest(ctx, session, report, "sqlite", row_id, match_json)
            await session.commit()

        if "player_data" in tables:
            collapser = RankCollapser()
            unusable = 0
            async for ts, puuid, rank, tier, lp, wins, losses in _sqlite_rows(
                conn,
                "SELECT timestamp, puuid, rank, tier, lp, wins, losses FROM player_data "
                "ORDER BY puuid, timestamp",
            ):
                report.rank_rows_seen += 1
                taken_at = _epoch_to_datetime(ts)
                standing = _normalize_standing(tier, rank)
                if not isinstance(puuid, str) or taken_at is None or standing is None:
                    unusable += 1
                    continue
                kept = collapser.push(
                    _RankRow(
                        puuid=puuid.strip(),
                        queue_type=RANKED_SOLO_5x5,
                        tier=standing[0],
                        rank=standing[1],
                        lp=max(0, _as_int(lp)),
                        wins=max(0, _as_int(wins)),
                        losses=max(0, _as_int(losses)),
                        taken_at=taken_at,
                    )
                )
                if kept is not None:
                    legacy.rank_rows.append(kept)
            if unusable:
                report.error(
                    f"sqlite player_data: skipped {unusable} rows without a valid puuid, "
                    "timestamp or tier/division"
                )
    finally:
        await asyncio.to_thread(conn.close)


# --- Neon ------------------------------------------------------------------------------------


def _icon_from_url(url: object) -> int | None:
    if not isinstance(url, str):
        return None
    match = _PROFILE_ICON_RE.search(url)
    return int(match.group(1)) if match else None


async def _neon_table_exists(conn: psycopg.AsyncConnection[Any], name: str) -> bool:
    cur = await conn.execute("SELECT to_regclass(%s) IS NOT NULL", (f'"{name}"',))
    row = await cur.fetchone()
    return bool(row and row[0])


async def _import_neon(
    ctx: IngestContext,
    session: AsyncSession,
    url: str,
    legacy: _Legacy,
    report: ImportReport,
) -> None:
    async with await psycopg.AsyncConnection.connect(libpq_url(url)) as conn:
        if await _neon_table_exists(conn, "Matches"):
            async with conn.cursor(name="hextrack_legacy_matches") as matches:
                await matches.execute('SELECT "matchId", data FROM "Matches" ORDER BY "matchId"')
                async for match_id, data in matches:
                    await _ingest(ctx, session, report, "neon", match_id, data)
            await session.commit()
        else:
            report.error('neon: table "Matches" not found')

        if not await _neon_table_exists(conn, "RiotAccount"):
            report.error('neon: table "RiotAccount" not found')
            return
        accounts = await conn.execute(
            'SELECT "riotId", puuid, "lastUpdate", "profileIconURL", "summonerLevel", '
            '"rankedInfo" FROM "RiotAccount" ORDER BY id'
        )
        for riot_id, puuid, last_update, icon_url, level, ranked_info in await accounts.fetchall():
            if not isinstance(puuid, str) or not puuid.strip():
                continue
            puuid = puuid.strip()
            ident = legacy.identity(puuid)
            ident.riot_id = _parse_riot_id(riot_id) or ident.riot_id
            if riot_id and ident.riot_id is None:
                report.error(f"neon RiotAccount {puuid}: unparsable riotId {riot_id!r}")
            ident.profile_icon_id = _icon_from_url(icon_url) or ident.profile_icon_id
            ident.summoner_level = level if isinstance(level, int) else ident.summoner_level
            updated = _aware(last_update)
            ident.last_refreshed_at = updated or ident.last_refreshed_at
            try:
                entries = _load_json(ranked_info)
            except ValueError:
                entries = None
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                queue_type = entry.get("queueType")
                if queue_type not in RANKED_QUEUE_TYPES:
                    continue
                report.rank_rows_seen += 1
                standing = _normalize_standing(entry.get("tier"), entry.get("rank"))
                if standing is None or updated is None:
                    report.error(f"neon RiotAccount {puuid}: unusable {queue_type} entry")
                    continue
                legacy.rank_rows.append(
                    _RankRow(
                        puuid=puuid,
                        queue_type=str(queue_type),
                        tier=standing[0],
                        rank=standing[1],
                        lp=max(0, _as_int(entry.get("leaguePoints"))),
                        wins=max(0, _as_int(entry.get("wins"))),
                        losses=max(0, _as_int(entry.get("losses"))),
                        taken_at=updated,
                    )
                )


# --- summoners, snapshots, roster ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Seen:
    """A puuid's newest appearance in stored match participants."""

    game_name: str | None
    tag_line: str | None
    profile_icon_id: int | None
    summoner_level: int | None
    game_start: datetime


async def _latest_appearances(session: AsyncSession, puuids: Iterable[str]) -> dict[str, _Seen]:
    wanted = sorted(set(puuids))
    found: dict[str, _Seen] = {}
    for start in range(0, len(wanted), 1000):
        chunk = wanted[start : start + 1000]
        stmt = (
            select(
                MatchParticipant.puuid,
                MatchParticipant.riot_id_game_name,
                MatchParticipant.riot_id_tagline,
                MatchParticipant.profile_icon_id,
                MatchParticipant.summoner_level,
                MatchParticipant.game_start,
            )
            .where(MatchParticipant.puuid.in_(chunk))
            .distinct(MatchParticipant.puuid)
            .order_by(MatchParticipant.puuid, MatchParticipant.game_start.desc())
        )
        for puuid, name, tag, icon, level, game_start in (await session.execute(stmt)).all():
            found[puuid] = _Seen(name, tag, icon, level, game_start)
    return found


async def _puuids_by_participant_riot_id(session: AsyncSession, riot_id: RiotId) -> str | None:
    """The puuid that most recently played under ``riot_id`` (case-insensitive)."""
    stmt = (
        select(MatchParticipant.puuid)
        .where(func.lower(MatchParticipant.riot_id_game_name) == func.lower(riot_id.game_name))
        .where(func.lower(MatchParticipant.riot_id_tagline) == func.lower(riot_id.tag_line))
        .order_by(MatchParticipant.game_start.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def _ensure_summoners(
    session: AsyncSession,
    legacy: _Legacy,
    puuids: Iterable[str],
    platform: str,
    report: ImportReport,
) -> set[str]:
    """Create missing summoner rows for ``puuids`` (and fill empty icon/level/last_seen on
    existing ones). Returns the puuids that have a row afterwards."""
    wanted = sorted(set(puuids))
    if not wanted:
        return set()
    seen = await _latest_appearances(session, wanted)
    existing = set(
        (await session.scalars(select(Summoner.puuid).where(Summoner.puuid.in_(wanted)))).all()
    )
    for puuid in wanted:
        ident = legacy.identities.get(puuid, _Identity())
        appearance = seen.get(puuid)
        name: str | None = None
        tag: str | None = None
        if appearance and appearance.game_name and appearance.tag_line:
            name, tag = appearance.game_name, appearance.tag_line
        elif ident.riot_id is not None:
            name, tag = ident.riot_id.game_name, ident.riot_id.tag_line
        icon = ident.profile_icon_id or (appearance.profile_icon_id if appearance else None)
        level = ident.summoner_level or (appearance.summoner_level if appearance else None)
        last_seen = appearance.game_start if appearance else None
        if puuid in existing:
            fill: dict[str, Any] = {}
            if icon is not None:
                fill["profile_icon_id"] = func.coalesce(Summoner.profile_icon_id, icon)
            if level is not None:
                fill["summoner_level"] = func.coalesce(Summoner.summoner_level, level)
            if last_seen is not None:
                fill["last_seen"] = func.greatest(Summoner.last_seen, last_seen)
            if fill:
                await session.execute(
                    update(Summoner)
                    .where(Summoner.puuid == puuid)
                    .values(**fill)
                    .execution_options(synchronize_session=False)
                )
            continue
        if name is None or tag is None:
            report.error(f"no Riot ID known for puuid {puuid}; its legacy rank history skipped")
            continue
        result = await session.execute(
            insert(Summoner)
            .values(
                puuid=puuid,
                game_name=name,
                tag_line=tag,
                platform=platform,
                profile_icon_id=icon,
                summoner_level=level,
                is_tracked=False,
                last_seen=last_seen,
                last_refreshed_at=ident.last_refreshed_at,
            )
            .on_conflict_do_nothing()
            .returning(Summoner.puuid)
        )
        if result.first() is None:
            report.error(
                f"{name}#{tag} ({puuid}) clashes with another stored account's Riot ID; skipped"
            )
            continue
        existing.add(puuid)
        report.summoners_created += 1
    return existing


async def _insert_rank_rows(
    session: AsyncSession, rows: list[_RankRow], present: set[str], report: ImportReport
) -> None:
    rows = [r for r in rows if r.puuid in present]
    if not rows:
        return
    puuids = sorted({r.puuid for r in rows})
    stored: set[tuple[str, str, datetime]] = set()
    for start in range(0, len(puuids), 1000):
        chunk = puuids[start : start + 1000]
        result = await session.execute(
            select(RankSnapshot.puuid, RankSnapshot.queue_type, RankSnapshot.taken_at).where(
                RankSnapshot.puuid.in_(chunk)
            )
        )
        stored.update((p, q, t) for p, q, t in result.all())
    new_rows: list[dict[str, Any]] = []
    for r in rows:
        key = (r.puuid, r.queue_type, r.taken_at)
        if key in stored:
            report.rank_snapshots_skipped_existing += 1
            continue
        stored.add(key)
        new_rows.append(
            {
                "puuid": r.puuid,
                "queue_type": r.queue_type,
                "tier": r.tier,
                "rank": r.rank,
                "lp": r.lp,
                "wins": r.wins,
                "losses": r.losses,
                "rank_value": rank_value(r.tier, r.rank, r.lp),
                "taken_at": r.taken_at,
                "is_heartbeat": r.is_heartbeat,
            }
        )
    for start in range(0, len(new_rows), 1000):
        await session.execute(insert(RankSnapshot).values(new_rows[start : start + 1000]))
    report.rank_snapshots_created += len(new_rows)


def _player_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    return [line.strip() for line in text.splitlines() if line.strip()]


async def _resolve_player(
    session: AsyncSession, line: str, legacy: _Legacy, platform: str
) -> tuple[str, RiotId | None] | None:
    riot_id = _parse_riot_id(line)
    puuid = legacy.puuid_by_player_line.get(line)
    if puuid is None and riot_id is not None:
        key = riot_id_key(riot_id.game_name, riot_id.tag_line)
        for stored_line, candidate in legacy.puuid_by_player_line.items():
            parsed = _parse_riot_id(stored_line)
            if parsed is not None and riot_id_key(parsed.game_name, parsed.tag_line) == key:
                puuid = candidate
                break
    if puuid is None and riot_id is not None:
        stmt = (
            select(Summoner.puuid)
            .where(
                tuple_(func.lower(Summoner.game_name), func.lower(Summoner.tag_line))
                == tuple_(func.lower(riot_id.game_name), func.lower(riot_id.tag_line))
            )
            .order_by((Summoner.platform == platform).desc(), Summoner.puuid)
            .limit(1)
        )
        puuid = (await session.scalars(stmt)).first()
    if puuid is None and riot_id is not None:
        puuid = await _puuids_by_participant_riot_id(session, riot_id)
    if puuid is None:
        return None
    return puuid, riot_id


async def _mark_tracked(
    session: AsyncSession,
    path: Path,
    legacy: _Legacy,
    platform: str,
    report: ImportReport,
) -> None:
    resolved: dict[str, RiotId | None] = {}
    for line in _player_lines(path):
        found = await _resolve_player(session, line, legacy, platform)
        if found is None:
            report.players_unresolved += 1
            report.error(
                f"players.txt: could not resolve {line!r} (not in the LPBot puuids table, "
                "stored summoners or match history)"
            )
            continue
        puuid, riot_id = found
        ident = legacy.identity(puuid)
        ident.riot_id = ident.riot_id or riot_id
        resolved[puuid] = riot_id
    if not resolved:
        return
    present = await _ensure_summoners(session, legacy, resolved, platform, report)
    first_history: dict[str, datetime] = {}
    for row in legacy.rank_rows:
        if row.puuid in resolved:
            prev = first_history.get(row.puuid)
            first_history[row.puuid] = row.taken_at if prev is None else min(prev, row.taken_at)
    now = datetime.now(UTC)
    for puuid in sorted(resolved):
        if puuid not in present:
            continue
        await session.execute(
            update(Summoner)
            .where(Summoner.puuid == puuid)
            .values(
                is_tracked=True,
                tracked_since=func.coalesce(Summoner.tracked_since, first_history.get(puuid, now)),
            )
            .execution_options(synchronize_session=False)
        )
        report.summoners_tracked += 1


def _load_scorer(model_dir: Path) -> Scorer | None:
    from hextrack.hextrack_ai.inference import Scorer

    try:
        return Scorer.load(model_dir)
    except Exception:
        logger.exception("could not load the AI model from %s; importing unscored", model_dir)
        return None


async def run_import(
    settings: Settings,
    sqlite_path: Path | None,
    neon_url: str | None,
    players_path: Path | None,
) -> ImportReport:
    """Import from any combination of sources (None skips a source)."""
    report = ImportReport()
    legacy = _Legacy()
    platform = settings.riot_platform
    engine = make_async_engine(settings, pool_size=2, max_overflow=0)
    try:
        factory = make_session_factory(engine)
        # Offline client: nothing here talks to Riot, and a stray call fails fast.
        async with RiotClient(settings.model_copy(update={"riot_api_key": None})) as riot:
            ctx = IngestContext(
                settings=settings,
                session_factory=factory,
                riot=riot,
                scorer=_load_scorer(settings.model_dir),
            )
            async with factory() as session:
                if sqlite_path is not None:
                    await _import_sqlite(ctx, session, sqlite_path, legacy, report)
                if neon_url:
                    await _import_neon(ctx, session, neon_url, legacy, report)

                accounts = set(legacy.identities) | {r.puuid for r in legacy.rank_rows}
                present = await _ensure_summoners(session, legacy, accounts, platform, report)
                legacy.rank_rows.sort(key=lambda r: (r.puuid, r.queue_type, r.taken_at))
                await _insert_rank_rows(session, legacy.rank_rows, present, report)
                await session.commit()

                if players_path is not None:
                    await _mark_tracked(session, players_path, legacy, platform, report)
                    await session.commit()
    finally:
        await engine.dispose()
    logger.info(
        "legacy import: %d matches seen, %d created, %d existing, %d invalid; "
        "%d rank snapshots; %d tracked",
        report.matches_seen,
        report.matches_created,
        report.matches_skipped_existing,
        report.matches_invalid,
        report.rank_snapshots_created,
        report.summoners_tracked,
    )
    return report
