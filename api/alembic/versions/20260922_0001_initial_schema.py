"""initial schema

Tables: summoners, matches, match_participants, rank_snapshots, bot_events, ai_models,
app_state. Generated with autogenerate against an empty database and reviewed by hand
(expression / partial indexes verified against hextrack.db.models).

Revision ID: 0001
Revises:
Create Date: 2026-09-22 02:40:41.832783+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_models",
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("feature_names", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("version", name=op.f("pk_ai_models")),
    )
    op.create_index(
        "uq_ai_models_single_active",
        "ai_models",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "app_state",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_state")),
    )
    op.create_table(
        "bot_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_events")),
    )
    op.create_index(
        "ix_bot_events_pending",
        "bot_events",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    op.create_table(
        "matches",
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("platform_id", sa.Text(), nullable=True),
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("game_mode", sa.Text(), nullable=False),
        sa.Column("game_type", sa.Text(), nullable=True),
        sa.Column("game_version", sa.Text(), nullable=False),
        sa.Column("patch", sa.Text(), nullable=False),
        sa.Column("game_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("game_duration", sa.Integer(), nullable=False),
        sa.Column("end_of_game_result", sa.Text(), nullable=True),
        sa.Column("remake", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("match_id", name=op.f("pk_matches")),
    )
    op.create_index(
        "ix_matches_game_start", "matches", [sa.literal_column("game_start DESC")], unique=False
    )
    op.create_index(
        "ix_matches_queue_id_game_start",
        "matches",
        ["queue_id", sa.literal_column("game_start DESC")],
        unique=False,
    )
    op.create_table(
        "summoners",
        sa.Column("puuid", sa.Text(), nullable=False),
        sa.Column("game_name", sa.Text(), nullable=False),
        sa.Column("tag_line", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("profile_icon_id", sa.Integer(), nullable=True),
        sa.Column("summoner_level", sa.Integer(), nullable=True),
        sa.Column("is_tracked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tracked_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("puuid", name=op.f("pk_summoners")),
    )
    op.create_index(
        "ix_summoners_game_name_prefix",
        "summoners",
        [sa.literal_column("lower(game_name) text_pattern_ops")],
        unique=False,
    )
    op.create_index(
        "ix_summoners_tracked",
        "summoners",
        ["is_tracked"],
        unique=False,
        postgresql_where=sa.text("is_tracked"),
    )
    op.create_index(
        "uq_summoners_riot_id_lower",
        "summoners",
        [sa.literal_column("lower(game_name)"), sa.literal_column("lower(tag_line)"), "platform"],
        unique=True,
    )
    op.create_table(
        "match_participants",
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("puuid", sa.Text(), nullable=False),
        sa.Column("participant_id", sa.SmallInteger(), nullable=False),
        sa.Column("team_id", sa.SmallInteger(), nullable=False),
        sa.Column("game_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("riot_id_game_name", sa.Text(), nullable=True),
        sa.Column("riot_id_tagline", sa.Text(), nullable=True),
        sa.Column("profile_icon_id", sa.Integer(), nullable=True),
        sa.Column("summoner_level", sa.Integer(), nullable=True),
        sa.Column("champion_id", sa.Integer(), nullable=False),
        sa.Column("champion_name", sa.Text(), nullable=False),
        sa.Column("champ_level", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("team_position", sa.Text(), server_default=sa.text("'UNKNOWN'"), nullable=False),
        sa.Column("win", sa.Boolean(), nullable=False),
        sa.Column(
            "game_ended_in_early_surrender",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "game_ended_in_surrender", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("kills", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("deaths", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("assists", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "first_blood_kill", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("double_kills", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("triple_kills", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("quadra_kills", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("penta_kills", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("largest_multi_kill", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "largest_killing_spree", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("killing_sprees", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "longest_time_spent_living", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "total_time_spent_dead", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("gold_earned", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("gold_spent", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "total_minions_killed", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "neutral_minions_killed", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "total_ally_jungle_minions_killed",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_enemy_jungle_minions_killed",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("total_damage_dealt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "total_damage_dealt_to_champions",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "physical_damage_dealt_to_champions",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "magic_damage_dealt_to_champions",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "true_damage_dealt_to_champions",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("total_damage_taken", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "damage_self_mitigated", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "damage_dealt_to_objectives", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "damage_dealt_to_buildings", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "damage_dealt_to_turrets", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("vision_score", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("wards_placed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("wards_killed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("vision_wards_bought", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "detector_wards_placed", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("time_ccing_others", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_time_cc_dealt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_heal", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "total_heals_on_teammates", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "total_damage_shielded_on_teammates",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("turret_kills", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("turret_takedowns", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("inhibitor_kills", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("inhibitor_takedowns", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("dragon_kills", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("baron_kills", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "first_tower_kill", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("pings_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("summoner1_id", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("summoner2_id", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("primary_rune_id", sa.Integer(), nullable=True),
        sa.Column("secondary_style_id", sa.Integer(), nullable=True),
        sa.Column("ai_score", sa.Float(), nullable=True),
        sa.Column("ai_scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.match_id"],
            name=op.f("fk_match_participants_match_id_matches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("match_id", "puuid", name=op.f("pk_match_participants")),
    )
    op.create_index(
        "ix_match_participants_model_version", "match_participants", ["model_version"], unique=False
    )
    op.create_index(
        "ix_match_participants_puuid_game_start",
        "match_participants",
        ["puuid", sa.literal_column("game_start DESC")],
        unique=False,
    )
    op.create_index(
        "ix_match_participants_puuid_queue_game_start",
        "match_participants",
        ["puuid", "queue_id", sa.literal_column("game_start DESC")],
        unique=False,
    )
    op.create_index(
        "ix_match_participants_unscored",
        "match_participants",
        ["match_id"],
        unique=False,
        postgresql_where=sa.text("ai_score IS NULL"),
    )
    op.create_table(
        "rank_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("puuid", sa.Text(), nullable=False),
        sa.Column("queue_type", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("rank", sa.Text(), nullable=True),
        sa.Column("lp", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("rank_value", sa.Integer(), nullable=False),
        sa.Column(
            "taken_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("is_heartbeat", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(
            ["puuid"],
            ["summoners.puuid"],
            name=op.f("fk_rank_snapshots_puuid_summoners"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rank_snapshots")),
    )
    op.create_index(
        "ix_rank_snapshots_puuid_queue_taken_at",
        "rank_snapshots",
        ["puuid", "queue_type", sa.literal_column("taken_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_rank_snapshots_puuid_queue_taken_at", table_name="rank_snapshots")
    op.drop_table("rank_snapshots")
    op.drop_index(
        "ix_match_participants_unscored",
        table_name="match_participants",
        postgresql_where=sa.text("ai_score IS NULL"),
    )
    op.drop_index("ix_match_participants_puuid_queue_game_start", table_name="match_participants")
    op.drop_index("ix_match_participants_puuid_game_start", table_name="match_participants")
    op.drop_index("ix_match_participants_model_version", table_name="match_participants")
    op.drop_table("match_participants")
    op.drop_index("uq_summoners_riot_id_lower", table_name="summoners")
    op.drop_index(
        "ix_summoners_tracked", table_name="summoners", postgresql_where=sa.text("is_tracked")
    )
    op.drop_index("ix_summoners_game_name_prefix", table_name="summoners")
    op.drop_table("summoners")
    op.drop_index("ix_matches_queue_id_game_start", table_name="matches")
    op.drop_index("ix_matches_game_start", table_name="matches")
    op.drop_table("matches")
    op.drop_index(
        "ix_bot_events_pending",
        table_name="bot_events",
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    op.drop_table("bot_events")
    op.drop_table("app_state")
    op.drop_index(
        "uq_ai_models_single_active", table_name="ai_models", postgresql_where=sa.text("is_active")
    )
    op.drop_table("ai_models")
