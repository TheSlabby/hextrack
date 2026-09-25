"""Live games: which roster players are in a game right now (Riot spectator-v5).

The worker calls :func:`refresh_live_games` after every poll. It asks spectator-v5 about each
tracked player (one call covers everyone else in the same game), fetches league entries once
per new game for the participants who aren't on the roster, and stores the result under the
``app_state`` key :data:`STATE_KEY`:

    {"checked_at": ISO-8601,
     "games": [{"info": <spectator CurrentGameInfo JSON>,
                "ranks": {puuid: [<league-v4 entry JSON>, ...]},
                "first_seen_at": ISO-8601, "seen_at": ISO-8601}]}

The API (:mod:`hextrack.stats.live`) reads it; nothing here is served directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hextrack.ingest.context import IngestContext

STATE_KEY = "live_games"


@dataclass(slots=True)
class LiveReport:
    checked: int = 0
    games: int = 0
    rank_lookups: int = 0
    errors: list[str] = field(default_factory=list)


async def refresh_live_games(ctx: IngestContext) -> LiveReport:
    """Check every tracked player, then replace the stored state (own session and commit)."""
    raise NotImplementedError
