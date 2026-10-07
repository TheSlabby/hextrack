"""Training-data export: one CSV row per participant of the scorable games (read-only).

``hextrack model export-dataset`` streams this as gzipped CSV to stdout, so model research can
run on a copy of production's games (including the crawler's) without access to the database
itself: ``sudo hextrack-admin model export-dataset > games.csv.gz``.

The export runs in a read-only transaction and goes through Postgres ``COPY ... TO STDOUT``,
so memory stays flat however many games there are. PUUIDs are replaced by an unsalted
SHA-256 prefix (``player``): enough to group a player's games, not to look them up. Riot IDs
are left out. Besides the ``match_participants`` stat columns it carries a curated set of
Riot's per-participant ``challenges`` (``c_<name>``) read from the stored raw match JSON.
"""

from __future__ import annotations

import gzip
from collections.abc import Sequence
from typing import IO, Final

from sqlalchemy import Engine, select
from sqlalchemy.dialects import postgresql

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


def export_query(queues: Sequence[int], max_matches: int | None = None) -> str:
    """The ``SELECT`` behind the export, with every value inlined (it runs under COPY)."""
    games = (
        select(Match.match_id)
        .where(registry.scorable_match_clause(), Match.queue_id.in_([int(q) for q in queues]))
        .order_by(Match.game_start.desc(), Match.match_id.desc())
    )
    if max_matches is not None:
        games = games.limit(int(max_matches))
    games_sql = str(
        games.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    stats = ", ".join(f"mp.{name}" for name in stat_columns())
    challenges = ", ".join(
        f"(ch.c->>'{name}')::double precision AS \"c_{name}\"" for name in EXPORT_CHALLENGES
    )
    # The raw JSON is unpacked once per game (``ch``), not once per participant: detoasting
    # a ~45 kB document ten times per game made the export ten times slower.
    return f"""
WITH g AS ({games_sql}),
ch AS MATERIALIZED (
    SELECT m.match_id, (p->>'participantId')::int AS participant_id, p->'challenges' AS c
    FROM g
    JOIN matches m ON m.match_id = g.match_id
    CROSS JOIN LATERAL jsonb_array_elements(m.raw->'info'->'participants') AS p
)
SELECT m.match_id, m.game_start, m.game_duration, m.queue_id, m.patch, m.source,
       left(encode(sha256(convert_to(mp.puuid, 'UTF8')), 'hex'), 16) AS player,
       coalesce(s.is_tracked, false) AS tracked,
       {stats},
       mp.model_version, {challenges}
FROM g
JOIN matches m ON m.match_id = g.match_id
JOIN match_participants mp ON mp.match_id = m.match_id
LEFT JOIN summoners s ON s.puuid = mp.puuid
LEFT JOIN ch ON ch.match_id = mp.match_id AND ch.participant_id = mp.participant_id
ORDER BY m.game_start, m.match_id, mp.participant_id
"""


def export_dataset(
    engine: Engine,
    out: IO[bytes],
    *,
    queues: Sequence[int] = (420, 440),
    max_matches: int | None = None,
) -> int:
    """Write the gzipped CSV (with a header row) to ``out``; returns the CSV byte count."""
    sql = export_query(queues, max_matches)
    written = 0
    with engine.connect() as conn:
        dbapi = conn.connection.driver_connection
        with dbapi.cursor() as cur:  # type: ignore[union-attr]
            cur.execute("SET TRANSACTION READ ONLY")
            with (
                gzip.GzipFile(fileobj=out, mode="wb", compresslevel=6) as gz,
                cur.copy(f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)") as copy,
            ):
                for chunk in copy:
                    gz.write(chunk)
                    written += len(chunk)
        conn.rollback()
    return written
