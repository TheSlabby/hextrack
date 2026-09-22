"""discovery watermark, Arena subteams, one remake rule

Three changes that belong to the same deploy:

* ``summoners.synced_through``: how far match discovery is known to be complete for a
  player, so a partly ingested gap is listed again instead of being skipped forever
  (``hextrack.ingest.service.discover``).
* ``match_participants.player_subteam_id`` / ``placement``: Arena (CHERRY) games are eight
  duos, not two teams of eight. Backfilled from the stored raw payloads.
* one remake rule everywhere: a game shorter than 5 minutes is a remake at ingestion too,
  the way match history and the season stats have always counted it. Rows stored under the
  old rule are corrected and their AI scores cleared, because those games are not scorable
  (run ``hextrack model rescore`` afterwards, which will skip them).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-22 18:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Keep in step with hextrack.ingest.mapping.REMAKE_MAX_SECONDS.
REMAKE_MAX_SECONDS = 300


def upgrade() -> None:
    op.add_column("summoners", sa.Column("synced_through", sa.DateTime(timezone=True), nullable=True))
    op.add_column("match_participants", sa.Column("player_subteam_id", sa.SmallInteger(), nullable=True))
    op.add_column("match_participants", sa.Column("placement", sa.SmallInteger(), nullable=True))

    # Arena subteams and placements out of the stored match-v5 payloads.
    op.execute(
        sa.text(
            """
            UPDATE match_participants mp
               SET player_subteam_id = NULLIF((raw_p ->> 'playerSubteamId')::int, 0),
                   placement         = NULLIF((raw_p ->> 'placement')::int, 0)
              FROM matches m
              CROSS JOIN LATERAL jsonb_array_elements(m.raw -> 'info' -> 'participants') AS raw_p
             WHERE m.match_id = mp.match_id
               AND m.game_mode = 'CHERRY'
               AND raw_p ->> 'puuid' = mp.puuid
            """
        )
    )

    # One remake rule: short games are remakes, so they are excluded from the AI Score and
    # from the events the bot posts, exactly as the stats layer already shows them.
    op.execute(
        sa.text(
            """
            UPDATE match_participants mp
               SET ai_score = NULL, ai_scored_at = NULL, model_version = NULL
              FROM matches m
             WHERE m.match_id = mp.match_id
               AND m.game_duration < :cutoff
               AND mp.ai_score IS NOT NULL
            """
        ).bindparams(cutoff=REMAKE_MAX_SECONDS)
    )
    op.execute(
        sa.text(
            """
            UPDATE matches
               SET remake = true, scored_at = NULL, model_version = NULL
             WHERE game_duration < :cutoff
               AND remake IS NOT true
            """
        ).bindparams(cutoff=REMAKE_MAX_SECONDS)
    )


def downgrade() -> None:
    # The remake and AI-score corrections are data fixes; only the columns come back off.
    op.drop_column("match_participants", "placement")
    op.drop_column("match_participants", "player_subteam_id")
    op.drop_column("summoners", "synced_through")
