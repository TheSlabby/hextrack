"""scored-participants index for the role percentile population

The population query (``stats/role_percentile.py``) read every ``match_participants`` row
(1.5M+, mostly crawled and unscored) to find the ~60k scored ones: about 0.5 s with the table
in memory, 8+ s from the SD card. This partial covering index holds only scored rows.

Built CONCURRENTLY so the API and worker keep writing while it builds.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_match_participants_scored_position",
            "match_participants",
            ["team_position"],
            unique=False,
            postgresql_include=["ai_score", "model_version", "queue_id", "match_id"],
            postgresql_where=sa.text("ai_score IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_match_participants_scored_position",
            table_name="match_participants",
            postgresql_concurrently=True,
            if_exists=True,
        )
