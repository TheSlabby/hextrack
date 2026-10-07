"""Training-data export: one CSV row per participant of the scorable games (read-only).

``hextrack model export-dataset`` streams this as gzipped CSV to stdout, so model research can
run on a copy of production's games (including the crawler's) without access to the database
itself: ``sudo hextrack-admin model export-dataset > games.csv.gz``.

The export runs in one read-only transaction and goes through Postgres ``COPY ... TO STDOUT``
in chunks of games, so memory stays flat however many games there are. PUUIDs are replaced
by an unsalted SHA-256 prefix (``player``): enough to group a player's games, not to look
them up. Riot IDs are left out. Besides the ``match_participants`` stat columns it carries a
curated set of Riot's per-participant ``challenges`` (``c_<name>``) read from the stored raw
match JSON.
"""

from __future__ import annotations

import gzip
from collections.abc import Sequence
from typing import IO, Any, Final

from sqlalchemy import Engine, Select, select, text

from hextrack.db.models import Match, MatchParticipant
from hextrack.hextrack_ai import registry

#: ``match_participants`` columns that are never exported (identity, cosmetics, scores of
#: other shapes); everything else that is a plain number or boolean is.
_SKIP_COLUMNS: Final = frozenset(
    {
        "match_id",
        "puuid",
        "riot_id_game_name",
        "riot_id_tagline",
        "profile_icon_id",
        "summoner_level",
        "champion_name",
        "items",
        "rune_ids",
        "stat_shards",
        "game_start",
        "queue_id",
        "ai_scored_at",
        "model_version",
    }
)

#: Riot ``challenges`` fields exported as ``c_<name>`` (numbers; missing -> empty).
EXPORT_CHALLENGES: Final[tuple[str, ...]] = (
    "kda",
    "killParticipation",
    "teamDamagePercentage",
    "damageTakenOnTeamPercentage",
    "goldPerMinute",
    "damagePerMinute",
    "visionScorePerMinute",
    "soloKills",
    "takedowns",
    "laneMinionsFirst10Minutes",
    "jungleCsBefore10Minutes",
    "earlyLaningPhaseGoldExpAdvantage",
    "laningPhaseGoldExpAdvantage",
    "maxCsAdvantageOnLaneOpponent",
    "maxLevelLeadLaneOpponent",
    "visionScoreAdvantageLaneOpponent",
    "takedownsFirstXMinutes",
    "turretPlatesTaken",
    "skillshotsHit",
    "skillshotsDodged",
    "effectiveHealAndShielding",
    "enemyChampionImmobilizations",
    "controlWardsPlaced",
    "stealthWardsPlaced",
    "wardTakedowns",
    "wardTakedownsBefore20M",
    "outnumberedKills",
    "pickKillWithAlly",
    "saveAllyFromDeath",
    "killsNearEnemyTurret",
    "killsUnderOwnTurret",
    "epicMonsterSteals",
    "dragonTakedowns",
    "baronTakedowns",
    "riftHeraldTakedowns",
    "turretTakedowns",
    "bountyGold",
    "deathsByEnemyChamps",
    "abilityUses",
    "maxKillDeficit",
    "survivedSingleDigitHpCount",
    "tookLargeDamageSurvived",
    "immobilizeAndKillWithAlly",
    "enemyJungleMonsterKills",
    "moreEnemyJungleThanOpponent",
    "playedChampSelectPosition",
)


def stat_columns() -> list[str]:
    """``match_participants`` columns in the export, in table order."""
    out: list[str] = []
    for col in MatchParticipant.__table__.columns:
        if col.name in _SKIP_COLUMNS:
            continue
        try:
            python_type = col.type.python_type
        except NotImplementedError:
            continue
        if python_type in (int, float, bool) or col.name == "team_position":
            out.append(col.name)
    return out


#: Games per COPY. Small enough that Postgres never spills a join or sort to disk (the Pi's
#: database lives on an SD card: one big COPY of every game ran for over an hour).
EXPORT_CHUNK_MATCHES: Final = 1000


def export_games_query(queues: Sequence[int], max_matches: int | None = None) -> Select[Any]:
    """Match ids of the exported games, oldest first."""
    games = (
        select(Match.match_id)
        .where(registry.scorable_match_clause(), Match.queue_id.in_([int(q) for q in queues]))
        .order_by(Match.game_start.desc(), Match.match_id.desc())
    )
    if max_matches is not None:
        games = games.limit(int(max_matches))
    return games


def export_query(match_ids: Sequence[str]) -> str:
    """The ``SELECT`` behind one COPY chunk, with every value inlined (COPY takes no binds)."""
    ids = ", ".join("'" + m.replace("'", "''") + "'" for m in match_ids) or "NULL"
    stats = ", ".join(f"mp.{name}" for name in stat_columns())
    challenges = ", ".join(
        f"(ch.c->>'{name}')::double precision AS \"c_{name}\"" for name in EXPORT_CHALLENGES
    )
    # The raw JSON is unpacked once per game (``ch``), not once per participant: detoasting
    # a ~45 kB document ten times per game made the export ten times slower.
    return f"""
WITH ch AS MATERIALIZED (
    SELECT m.match_id, (p->>'participantId')::int AS participant_id, p->'challenges' AS c
    FROM matches m
    CROSS JOIN LATERAL jsonb_array_elements(m.raw->'info'->'participants') AS p
    WHERE m.match_id IN ({ids})
)
SELECT m.match_id, m.game_start, m.game_duration, m.queue_id, m.patch, m.source,
       left(encode(sha256(convert_to(mp.puuid, 'UTF8')), 'hex'), 16) AS player,
       coalesce(s.is_tracked, false) AS tracked,
       {stats},
       mp.model_version, {challenges}
FROM matches m
JOIN match_participants mp ON mp.match_id = m.match_id
LEFT JOIN summoners s ON s.puuid = mp.puuid
LEFT JOIN ch ON ch.match_id = mp.match_id AND ch.participant_id = mp.participant_id
WHERE m.match_id IN ({ids})
ORDER BY m.game_start, m.match_id, mp.participant_id
"""


def export_dataset(
    engine: Engine,
    out: IO[bytes],
    *,
    queues: Sequence[int] = (420, 440),
    max_matches: int | None = None,
    chunk_matches: int = EXPORT_CHUNK_MATCHES,
) -> int:
    """Write the gzipped CSV (one header row, games oldest first) to ``out``; returns the CSV
    byte count. Runs one read-only transaction, one COPY per ``chunk_matches`` games."""
    written = 0
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        ids = [row.match_id for row in conn.execute(export_games_query(queues, max_matches))]
        ids.reverse()
        dbapi = conn.connection.driver_connection
        with (
            gzip.GzipFile(fileobj=out, mode="wb", compresslevel=6) as gz,
            dbapi.cursor() as cur,  # type: ignore[union-attr]
        ):
            for start in range(0, max(len(ids), 1), chunk_matches):
                header = "true" if start == 0 else "false"
                sql = export_query(ids[start : start + chunk_matches])
                with cur.copy(f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER {header})") as cp:
                    for chunk in cp:
                        gz.write(chunk)
                        written += len(chunk)
        conn.rollback()
    return written


#: Text only an export COPY contains, so cancelling never touches any other query. It sits in
#: the first few hundred characters: pg_stat_activity keeps only the first 1 kB of a query.
_EXPORT_MARKER: Final = "p->'challenges' AS c"


def cancel_running_exports(engine: Engine) -> list[int]:
    """Cancel export COPYs still running as this database role (e.g. one whose client went
    away); returns their backend pids. A role may always cancel its own queries."""
    stmt = text(
        "SELECT pid FROM pg_stat_activity WHERE usename = current_user"
        " AND pid <> pg_backend_pid() AND query LIKE 'COPY (%' AND position(:marker in query) > 0"
    )
    with engine.connect() as conn:
        pids = [int(p) for p in conn.execute(stmt, {"marker": _EXPORT_MARKER}).scalars()]
        for pid in pids:
            conn.execute(text("SELECT pg_cancel_backend(:pid)"), {"pid": pid})
        conn.rollback()
    return pids
