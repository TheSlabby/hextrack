"""Period / queue filters shared by the squad, insights and records endpoints.

Owner: contract (task X0). Builders import these instead of re-deriving the rules:

* :func:`since_cutoff` turns ``since=season|all`` into the ``since`` argument of
  :func:`hextrack.stats.aggregate.stat_rows` (a datetime or None).
* :func:`queue_ids` turns ``queue=all|solo|flex`` into the ranked queue ids (420 / 440).
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from hextrack.api.schemas import LeaderboardQueue, StatsSince
from hextrack.config import Settings
from hextrack.stats.aggregate import LEADERBOARD_QUEUES

#: Default small-sample thresholds (echoed in the responses as ``min_games``).
SQUAD_MIN_GAMES: Final = 5
SESSION_MIN_GAMES: Final = 5
SCHEDULE_MIN_GAMES: Final = 5
MATCHUP_MIN_GAMES_DEFAULT: Final = 3
#: Unlucky loss: lost with a score >= this; lucky win: won with a score <= LUCK_LOW.
LUCK_HIGH: Final = 0.6
LUCK_LOW: Final = 0.4


def since_cutoff(settings: Settings, since: StatsSince) -> datetime | None:
    """``settings.season_start`` for "season", None (no lower bound) for "all"."""
    return settings.season_start if since == "season" else None


def queue_ids(queue: LeaderboardQueue) -> tuple[int, ...]:
    """Ranked queue ids for a queue filter: all = (420, 440), solo = (420,), flex = (440,)."""
    return LEADERBOARD_QUEUES[queue]
