"""Legacy importer: LPBot SQLite (exact MatchDB.cpp schema), Neon (prisma schema), players.txt."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hextrack.config import Settings
from hextrack.db.models import BotEvent, Match, MatchParticipant, RankSnapshot, Summoner
from hextrack.legacy_import import (
    ImportReport,
    _RankRow,
    collapse_rank_rows,
    libpq_url,
    run_import,
)
from hextrack.rank import rank_value
from tests.factories import make_match_json, spec

T0 = datetime(2025, 3, 1, 18, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)

#: Verbatim from LPBot/src/MatchDB.cpp.
LPBOT_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS matches (id TEXT PRIMARY KEY, match_json TEXT);",
    "CREATE TABLE IF NOT EXISTS puuids (player_name TEXT PRIMARY KEY, puuid TEXT);",
    "CREATE TABLE IF NOT EXISTS player_data ("
    "timestamp INTEGER NOT NULL,"
    "puuid TEXT NOT NULL,"
    "rank TEXT,"
    "tier TEXT,"
    "lp INTEGER,"
    "wins INTEGER,"
    "losses INTEGER,"
    "PRIMARY KEY (timestamp, puuid)"
    ");",
)

#: What `prisma migrate` generates for hextrack/prisma/schema.prisma.
PRISMA_SCHEMA = (
    'CREATE TABLE "RiotAccount" ('
    '"id" SERIAL NOT NULL, "riotId" TEXT NOT NULL, "puuid" TEXT NOT NULL, '
    '"lastUpdate" TIMESTAMP(3), "profileIconURL" TEXT, "summonerLevel" INTEGER, '
    '"rankedInfo" JSONB, CONSTRAINT "RiotAccount_pkey" PRIMARY KEY ("id"))',
    'CREATE TABLE "Matches" ("matchId" TEXT NOT NULL, "data" JSONB NOT NULL, '
    'CONSTRAINT "Matches_pkey" PRIMARY KEY ("matchId"))',
    'CREATE UNIQUE INDEX "RiotAccount_riotId_key" ON "RiotAccount"("riotId")',
    'CREATE UNIQUE INDEX "RiotAccount_puuid_key" ON "RiotAccount"("puuid")',
)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _legacy_matches() -> list[dict[str, Any]]:
    """Three games of the old friend group (the second has a teammate who is not tracked)."""
    return [
        make_match_json(
            "NA1_5000000001",
            [
                spec("puuid-hex", "Hex Walker", "NA1"),
                spec("puuid-mid", "mid or feed", "4200"),
                spec("puuid-sup", "Ward Bot", "SUP"),
            ],
            start=T0 + HOUR,
        ),
        make_match_json(
            "NA1_5000000002",
            [spec("puuid-hex", "Hex Walker", "NA1"), spec("puuid-sup", "Ward Bot", "SUP")],
            start=T0 + 2 * HOUR,
            winning_team=200,
        ),
        make_match_json(
            "NA1_5000000003",
            [spec("puuid-mid", "Mid Or Feed", "4200")],  # renamed casing in a later game
            start=T0 + 3 * HOUR,
        ),
    ]


def _corrupt_rows() -> list[tuple[str, str]]:
    return [
        (
            "NA1_9000000001",
            json.dumps({"status": {"message": "Rate limit exceeded", "status_code": 429}}),
        ),
        ("NA1_9000000002", json.dumps({"metadata": {"matchId": "NA1_9000000002"}, "info": {}})),
        ("NA1_9000000003", '{"metadata": {"matchId": "NA1_900'),  # truncated write
    ]


def _build_lpbot_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        for stmt in LPBOT_SCHEMA:
            conn.execute(stmt)
        for raw in _legacy_matches():
            conn.execute(
                "INSERT INTO matches (id, match_json) VALUES (?,?)",
                (raw["metadata"]["matchId"], json.dumps(raw)),
            )
        conn.executemany("INSERT INTO matches (id, match_json) VALUES (?,?)", _corrupt_rows())
        conn.executemany(
            "INSERT INTO puuids (player_name, puuid) VALUES (?,?)",
            [("Hex Walker#NA1", "puuid-hex"), ("mid or feed#4200", "puuid-mid")],
        )
        rows = [
            # LPBot re-inserted the same standing every poll: 3 identical rows.
            (T0, "puuid-hex", "II", "GOLD", 40, 10, 8),
            (T0 + 2 * MINUTE, "puuid-hex", "II", "GOLD", 40, 10, 8),
            (T0 + 4 * MINUTE, "puuid-hex", "II", "GOLD", 40, 10, 8),
            # a win
            (T0 + 90 * MINUTE, "puuid-hex", "II", "GOLD", 58, 11, 8),
            (T0 + 92 * MINUTE, "puuid-hex", "II", "GOLD", 58, 11, 8),
            # unchanged for a day -> one heartbeat, the next poll is dropped again
            (T0 + 26 * HOUR, "puuid-hex", "II", "GOLD", 58, 11, 8),
            (T0 + 27 * HOUR, "puuid-hex", "II", "GOLD", 58, 11, 8),
            # promotion
            (T0 + 28 * HOUR, "puuid-hex", "I", "GOLD", 3, 12, 8),
            # apex tiers: LPBot stored Riot's "I"
            (T0, "puuid-mid", "I", "MASTER", 120, 80, 70),
            (T0 + 2 * MINUTE, "puuid-mid", "I", "MASTER", 120, 80, 70),
            # unusable rows
            (T0 + 3 * MINUTE, "puuid-mid", "", "", 0, 0, 0),
            (T0, "puuid-ghost", "IV", "IRON", 0, 1, 9),  # no Riot ID anywhere
        ]
        conn.executemany(
            "INSERT INTO player_data (puuid, timestamp, rank, tier, lp, wins, losses) "
            "VALUES (?,?,?,?,?,?,?)",
            [(p, _ms(ts), r, t, lp, w, lo) for ts, p, r, t, lp, w, lo in rows],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def lpbot_db(tmp_path: Path) -> Path:
    path = tmp_path / "database.sqlite"
    _build_lpbot_db(path)
    return path


@pytest.fixture
def players_txt(tmp_path: Path) -> Path:
    path = tmp_path / "players.txt"
    # BOM + CRLF like a file edited on Windows; a line only resolvable through match history
    # and one nobody knows.
    path.write_bytes("\ufeffHex Walker#NA1\r\nward bot#sup\r\n\r\nNobody Home#XYZ\r\n".encode())
    return path


async def _count(factory: async_sessionmaker[AsyncSession], model: Any, *where: Any) -> int:
    async with factory() as session:
        stmt = select(func.count()).select_from(model)
        if where:
            stmt = stmt.where(*where)
        return int(await session.scalar(stmt) or 0)


# --- pure helpers ----------------------------------------------------------------------------


def test_collapse_keeps_changes_and_daily_heartbeats() -> None:
    def row(at: datetime, lp: int, puuid: str = "p") -> _RankRow:
        return _RankRow(puuid, "RANKED_SOLO_5x5", "GOLD", "II", lp, 1, 1, at)

    rows = [
        row(T0, 10),
        row(T0 + MINUTE, 10),
        row(T0 + 25 * HOUR, 10),
        row(T0 + 26 * HOUR, 10),
        row(T0 + 26 * HOUR + MINUTE, 30),
        row(T0, 50, puuid="q"),
    ]
    kept = list(collapse_rank_rows(rows))
    assert [(r.puuid, r.taken_at, r.lp, r.is_heartbeat) for r in kept] == [
        ("p", T0, 10, False),
        ("p", T0 + 25 * HOUR, 10, True),
        ("p", T0 + 26 * HOUR + MINUTE, 30, False),
        ("q", T0, 50, False),
    ]


def test_libpq_url() -> None:
    assert libpq_url("postgresql+asyncpg://u:p@h:5432/db?x=1") == "postgresql://u:p@h:5432/db?x=1"
    assert libpq_url("postgres://u@h/db") == "postgresql://u@h/db"
    assert libpq_url("postgresql://u@h/db?sslmode=require") == "postgresql://u@h/db?sslmode=require"


# --- LPBot SQLite ----------------------------------------------------------------------------


async def test_sqlite_import_and_idempotency(
    clean_db: None,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    lpbot_db: Path,
    players_txt: Path,
) -> None:
    report = await run_import(settings, lpbot_db, None, players_txt)
    assert isinstance(report, ImportReport)
    assert report.matches_seen == 6
    assert report.matches_created == 3
    assert report.matches_invalid == 3
    assert report.matches_skipped_existing == 0
    # hex: T0, +90m, +26h heartbeat, +28h promotion; mid: one MASTER row; ghost skipped.
    assert report.rank_snapshots_created == 5
    assert report.rank_rows_seen == 12
    assert report.summoners_tracked == 2
    assert report.players_unresolved == 1
    assert any("Nobody Home#XYZ" in e for e in report.errors)
    assert any("puuid-ghost" in e for e in report.errors)
    assert sum("corrupt" in e or "unparsable" in e or "error body" in e for e in report.errors) == 3

    assert await _count(session_factory, Match) == 3
    assert await _count(session_factory, MatchParticipant) == 30
    async with session_factory() as session:
        hex_walker = await session.get(Summoner, "puuid-hex")
        assert hex_walker is not None
        assert (hex_walker.game_name, hex_walker.tag_line) == ("Hex Walker", "NA1")
        assert hex_walker.is_tracked and hex_walker.tracked_since == T0
        assert hex_walker.last_seen == T0 + 2 * HOUR
        assert hex_walker.profile_icon_id is not None
        mid = await session.get(Summoner, "puuid-mid")
        assert mid is not None and not mid.is_tracked
        # The newest game's Riot ID wins over the players.txt spelling.
        assert (mid.game_name, mid.tag_line) == ("Mid Or Feed", "4200")
        # Resolved through match participants only ("ward bot#sup" is case-insensitive).
        support = await session.get(Summoner, "puuid-sup")
        assert support is not None and support.is_tracked
        assert (support.game_name, support.tag_line) == ("Ward Bot", "SUP")
        assert await session.get(Summoner, "puuid-ghost") is None

        snaps = (
            await session.scalars(
                select(RankSnapshot)
                .where(RankSnapshot.puuid == "puuid-hex")
                .order_by(RankSnapshot.taken_at)
            )
        ).all()
        assert [(s.taken_at, s.tier, s.rank, s.lp, s.is_heartbeat) for s in snaps] == [
            (T0, "GOLD", "II", 40, False),
            (T0 + 90 * MINUTE, "GOLD", "II", 58, False),
            (T0 + 26 * HOUR, "GOLD", "II", 58, True),
            (T0 + 28 * HOUR, "GOLD", "I", 3, False),
        ]
        assert {s.queue_type for s in snaps} == {"RANKED_SOLO_5x5"}
        assert snaps[-1].rank_value == rank_value("GOLD", "I", 3)
        assert (snaps[-1].wins, snaps[-1].losses) == (12, 8)
        master = (
            await session.scalars(select(RankSnapshot).where(RankSnapshot.puuid == "puuid-mid"))
        ).one()
        assert (master.tier, master.rank, master.lp) == ("MASTER", None, 120)
        assert master.rank_value == rank_value("MASTER", None, 120)
        assert await session.scalar(select(func.count()).select_from(BotEvent)) == 0

    again = await run_import(settings, lpbot_db, None, players_txt)
    assert again.matches_created == 0
    assert again.matches_skipped_existing == 3
    assert again.matches_invalid == 3
    assert again.rank_snapshots_created == 0
    assert again.rank_snapshots_skipped_existing == 5
    assert again.summoners_created == 0
    assert again.summoners_tracked == 2
    assert await _count(session_factory, Match) == 3
    assert await _count(session_factory, RankSnapshot) == 5
    assert await _count(session_factory, Summoner) == 3
    # The legacy file is opened read-only and left untouched.
    conn = sqlite3.connect(lpbot_db)
    try:
        assert conn.execute("SELECT count(*) FROM player_data").fetchone() == (12,)
    finally:
        conn.close()


async def test_sqlite_import_keeps_existing_summoner_data(
    clean_db: None,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    lpbot_db: Path,
) -> None:
    async with session_factory() as session:
        session.add(
            Summoner(
                puuid="puuid-hex",
                game_name="Hex Walker",
                tag_line="NA1",
                platform="na1",
                profile_icon_id=4321,
                summoner_level=400,
                is_tracked=True,
                tracked_since=T0 - timedelta(days=30),
            )
        )
        await session.commit()
    report = await run_import(settings, lpbot_db, None, None)
    assert report.summoners_tracked == 0
    async with session_factory() as session:
        hex_walker = await session.get(Summoner, "puuid-hex")
        assert hex_walker is not None
        assert (hex_walker.profile_icon_id, hex_walker.summoner_level) == (4321, 400)
        assert hex_walker.is_tracked and hex_walker.tracked_since == T0 - timedelta(days=30)
        assert hex_walker.last_seen == T0 + 2 * HOUR


# --- Neon ------------------------------------------------------------------------------------


@pytest.fixture
async def neon_url(engine: AsyncEngine, test_database_url: str) -> AsyncIterator[str]:
    """A schema in the test database laid out like the old Neon database."""
    schema = f"legacy_neon_{uuid.uuid4().hex[:8]}"
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        for stmt in PRISMA_SCHEMA:
            await conn.execute(text(stmt))
    try:
        yield f"{test_database_url}?options=-csearch_path%3D{schema}"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


async def _fill_neon(engine: AsyncEngine, url: str, matches: list[tuple[str, Any]]) -> None:
    schema = url.rsplit("%3D", 1)[1]
    solo = {
        "leagueId": "x",
        "queueType": "RANKED_SOLO_5x5",
        "tier": "GOLD",
        "rank": "II",
        "puuid": "puuid-hex",
        "leaguePoints": 45,
        "wins": 30,
        "losses": 25,
        "veteran": False,
        "inactive": False,
        "freshBlood": False,
        "hotStreak": True,
    }
    flex = {**solo, "queueType": "RANKED_FLEX_SR", "tier": "SILVER", "rank": "I", "leaguePoints": 7}
    arena = {"queueType": "CHERRY", "wins": 3, "losses": 1}
    accounts = [
        (
            "Hex Walker#NA1",
            "puuid-hex",
            datetime(2025, 3, 10, 12, 30, 15, 123000),
            "https://static.bigbrain.gg/assets/lol/riot_static/15.5.1/img/profileicon/5000.png",
            120,
            json.dumps([solo, flex, arena]),
        ),
        (
            "Ward Bot#SUP",
            "puuid-sup",
            datetime(2025, 3, 11, 8, 0, 0),
            None,
            88,
            json.dumps({"status": {"message": "Forbidden", "status_code": 403}}),
        ),
        ("Lonely Ranker#LR1", "puuid-lonely", None, None, None, None),
    ]
    async with engine.begin() as conn:
        await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        for riot_id, puuid, updated, icon, level, ranked in accounts:
            await conn.execute(
                text(
                    'INSERT INTO "RiotAccount" ("riotId", puuid, "lastUpdate", "profileIconURL", '
                    '"summonerLevel", "rankedInfo") '
                    "VALUES (:r, :p, :u, :i, :l, CAST(:ranked AS jsonb))"
                ),
                {"r": riot_id, "p": puuid, "u": updated, "i": icon, "l": level, "ranked": ranked},
            )
        for match_id, data in matches:
            await conn.execute(
                text('INSERT INTO "Matches" ("matchId", data) VALUES (:m, CAST(:d AS jsonb))'),
                {"m": match_id, "d": data if isinstance(data, str) else json.dumps(data)},
            )


async def test_neon_import_and_idempotency(
    clean_db: None,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    neon_url: str,
) -> None:
    legacy = _legacy_matches()
    await _fill_neon(
        engine,
        neon_url,
        [
            (legacy[0]["metadata"]["matchId"], legacy[0]),
            (legacy[1]["metadata"]["matchId"], legacy[1]),
            ("NA1_9000000001", {"status": {"message": "Rate limit exceeded", "status_code": 429}}),
        ],
    )
    report = await run_import(settings, None, neon_url, None)
    assert report.matches_seen == 3
    assert report.matches_created == 2
    assert report.matches_invalid == 1
    assert report.summoners_created == 3
    assert report.rank_snapshots_created == 2  # solo + flex; arena and error bodies ignored
    assert report.summoners_tracked == 0

    async with session_factory() as session:
        hex_walker = await session.get(Summoner, "puuid-hex")
        assert hex_walker is not None and not hex_walker.is_tracked
        assert hex_walker.profile_icon_id == 5000
        assert hex_walker.summoner_level == 120
        assert hex_walker.last_refreshed_at == datetime(2025, 3, 10, 12, 30, 15, 123000, tzinfo=UTC)
        snaps = {
            s.queue_type: s
            for s in (
                await session.scalars(select(RankSnapshot).where(RankSnapshot.puuid == "puuid-hex"))
            ).all()
        }
        assert set(snaps) == {"RANKED_SOLO_5x5", "RANKED_FLEX_SR"}
        solo = snaps["RANKED_SOLO_5x5"]
        assert (solo.tier, solo.rank, solo.lp, solo.wins, solo.losses) == ("GOLD", "II", 45, 30, 25)
        assert solo.taken_at == hex_walker.last_refreshed_at
        assert snaps["RANKED_FLEX_SR"].rank_value == rank_value("SILVER", "I", 7)
        lonely = await session.get(Summoner, "puuid-lonely")
        assert lonely is not None and (lonely.game_name, lonely.tag_line) == (
            "Lonely Ranker",
            "LR1",
        )
        support = await session.get(Summoner, "puuid-sup")
        assert support is not None and support.summoner_level == 88

    again = await run_import(settings, None, neon_url, None)
    assert again.matches_created == 0 and again.matches_skipped_existing == 2
    assert again.rank_snapshots_created == 0 and again.summoners_created == 0
    assert await _count(session_factory, RankSnapshot) == 2
    assert await _count(session_factory, Summoner) == 3


async def test_all_sources_together(
    clean_db: None,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    neon_url: str,
    lpbot_db: Path,
    players_txt: Path,
) -> None:
    legacy = _legacy_matches()
    extra = make_match_json(
        "NA1_5000000004", [spec("puuid-hex", "Hex Walker", "NA1")], start=T0 + 30 * HOUR
    )
    await _fill_neon(
        engine,
        neon_url,
        [(legacy[0]["metadata"]["matchId"], legacy[0]), ("NA1_5000000004", extra)],
    )
    report = await run_import(settings, lpbot_db, neon_url, players_txt)
    assert report.matches_seen == 8
    assert report.matches_created == 4
    assert report.matches_skipped_existing == 1  # the game both apps stored
    assert report.matches_invalid == 3
    assert report.rank_snapshots_created == 5 + 2
    assert report.summoners_tracked == 2
    async with session_factory() as session:
        hex_walker = await session.get(Summoner, "puuid-hex")
        assert hex_walker is not None and hex_walker.is_tracked
        assert hex_walker.last_seen == T0 + 30 * HOUR
        assert hex_walker.profile_icon_id == 5000
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RankSnapshot)
                .where(RankSnapshot.puuid == "puuid-hex")
            )
            == 6
        )
