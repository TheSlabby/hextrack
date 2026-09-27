"""champion pages: full rune pages, bans, match timelines and champion rollups

* ``match_participants``: ``primary_style_id``, ``rune_ids`` (4 primary + 2 secondary) and
  ``stat_shards``. ``matches.ban_ids``. All NULL for stored games; new games get them at
  ingestion and the champion rollup worker fills older ones from ``raw`` as it counts them
  (a backfill here would rewrite every row).
* ``matches.timeline_state`` / ``timeline_attempts``: the crawler's timeline backlog. Season
  ranked games are marked "pending": every roster game and 1 in HEXTRACK_TIMELINE_SAMPLE
  crawled games (by match number, the same rule ingestion uses).
* ``matches.champ_rollup``: the rollup worker's queue (0 = to count).
* ``match_timeline_players`` and the ``champion_*`` rollup tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hextrack.config import get_settings

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SMALLINT_ARRAY = postgresql.ARRAY(sa.SmallInteger())


def _count(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), server_default=sa.text("0"), nullable=False)


def _sum(name: str) -> sa.Column:
    return sa.Column(name, sa.BigInteger(), server_default=sa.text("0"), nullable=False)


def _key() -> list[sa.Column]:
    return [
        sa.Column("champion_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Text(), nullable=False),
        sa.Column("patch", sa.Text(), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("match_participants", sa.Column("primary_style_id", sa.SmallInteger()))
    op.add_column("match_participants", sa.Column("rune_ids", SMALLINT_ARRAY))
    op.add_column("match_participants", sa.Column("stat_shards", SMALLINT_ARRAY))

    op.add_column("matches", sa.Column("ban_ids", SMALLINT_ARRAY))
    op.add_column("matches", sa.Column("timeline_state", sa.Text()))
    op.add_column(
        "matches",
        sa.Column(
            "timeline_attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "matches",
        sa.Column("champ_rollup", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )

    op.create_table(
        "match_timeline_players",
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("participant_id", sa.SmallInteger(), nullable=False),
        sa.Column("purchases", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("purchase_s", SMALLINT_ARRAY, nullable=False),
        sa.Column("skill_order", SMALLINT_ARRAY, nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.match_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("match_id", "participant_id"),
    )
    op.create_table(
        "champion_stats",
        *_key(),
        sa.Column("champion_key", sa.Text(), nullable=False),
        _count("games"),
        _count("wins"),
        _sum("kills"),
        _sum("deaths"),
        _sum("assists"),
        _sum("damage"),
        _sum("cs"),
        _sum("gold"),
        _sum("duration_s"),
        _count("timeline_games"),
        _count("timeline_wins"),
        sa.PrimaryKeyConstraint("champion_id", "position", "patch", "queue_id"),
    )
    op.create_index(
        "ix_champion_stats_patch_queue", "champion_stats", ["patch", "queue_id"], unique=False
    )
    op.create_table(
        "champion_bans",
        sa.Column("patch", sa.Text(), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("champion_id", sa.Integer(), nullable=False),
        _count("bans"),
        sa.PrimaryKeyConstraint("patch", "queue_id", "champion_id"),
    )
    op.create_table(
        "champion_patch_totals",
        sa.Column("patch", sa.Text(), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=False),
        _count("matches"),
        _count("timeline_matches"),
        sa.PrimaryKeyConstraint("patch", "queue_id"),
    )
    op.create_table(
        "champion_rollups",
        *_key(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        _count("games"),
        _count("wins"),
        _sum("extra_sum"),
        sa.PrimaryKeyConstraint("champion_id", "position", "patch", "queue_id", "kind", "key"),
    )
    # Rows are updated in place all day; leave room for HOT updates.
    op.execute("ALTER TABLE champion_rollups SET (fillfactor = 80)")
    op.execute("ALTER TABLE champion_stats SET (fillfactor = 80)")
    op.create_table(
        "champion_matchups",
        *_key(),
        sa.Column("opponent_id", sa.Integer(), nullable=False),
        _count("games"),
        _count("wins"),
        _sum("gold_diff_sum"),
        sa.PrimaryKeyConstraint("champion_id", "position", "patch", "queue_id", "opponent_id"),
    )

    op.create_index(
        "ix_matches_timeline_pending",
        "matches",
        ["source", sa.text("game_start DESC")],
        unique=False,
        postgresql_where=sa.text("timeline_state = 'pending'"),
    )
    op.create_index(
        "ix_matches_rollup_todo",
        "matches",
        ["ingested_at"],
        unique=False,
        postgresql_where=sa.text("champ_rollup IN (0, 3)"),
    )

    settings = get_settings()
    op.get_bind().execute(
        sa.text(
            """
            UPDATE matches SET timeline_state = 'pending'
            WHERE queue_id IN (420, 440) AND NOT remake AND game_start >= :season
              AND (source = 'roster'
                   OR substring(match_id from '_([0-9]+)$')::bigint % :sample = 0)
            """
        ),
        {"season": settings.season_start, "sample": settings.timeline_sample},
    )


def downgrade() -> None:
    op.drop_index("ix_matches_rollup_todo", table_name="matches")
    op.drop_index("ix_matches_timeline_pending", table_name="matches")
    op.drop_table("champion_matchups")
    op.drop_table("champion_rollups")
    op.drop_table("champion_patch_totals")
    op.drop_table("champion_bans")
    op.drop_index("ix_champion_stats_patch_queue", table_name="champion_stats")
    op.drop_table("champion_stats")
    op.drop_table("match_timeline_players")
    op.drop_column("matches", "champ_rollup")
    op.drop_column("matches", "timeline_attempts")
    op.drop_column("matches", "timeline_state")
    op.drop_column("matches", "ban_ids")
    op.drop_column("match_participants", "stat_shards")
    op.drop_column("match_participants", "rune_ids")
    op.drop_column("match_participants", "primary_style_id")
