"""data crawler: matches.source and the crawl_players frontier

* ``matches.source``: "roster" for everything stored so far (poller, lookups, imports) and
  "crawl" for games the data crawler adds from players HexTrack doesn't track.
* ``crawl_players``: the crawler's queue of players to fetch history for.
* ``ix_matches_source_queue_start``: roster-only lookups skip crawled games.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("source", sa.Text(), server_default=sa.text("'roster'"), nullable=False),
    )
    op.create_index(
        "ix_matches_source_queue_start",
        "matches",
        ["source", "queue_id", sa.text("game_start DESC")],
        unique=False,
    )
    op.create_table(
        "crawl_players",
        sa.Column("puuid", sa.Text(), nullable=False),
        sa.Column("found_via", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=True),
        sa.Column("division", sa.Text(), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matches_added", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("puuid"),
    )
    op.create_index(
        "ix_crawl_players_queue", "crawl_players", ["crawled_at", "discovered_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_crawl_players_queue", table_name="crawl_players")
    op.drop_table("crawl_players")
    op.drop_index("ix_matches_source_queue_start", table_name="matches")
    op.drop_column("matches", "source")
