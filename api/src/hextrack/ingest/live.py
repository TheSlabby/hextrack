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

Rules of a round:

* custom and practice games (``gameType == "CUSTOM_GAME"`` or queue 0) are ignored;
* a missing or rejected key, a persistent 429 or Riot being down ends the round early. Previous
  games none of whose roster players got an answer this round are then kept as they were
  (for at most :data:`CARRY_OVER_MAX_AGE` since they were last seen), so one bad round never
  blanks the page; games whose players answered "not in game" disappear;
* ``ranks`` holds every non-roster participant whose league lookup succeeded (``[]`` when
  unranked). Lookups that failed are retried next round, so a continuing game only costs
  spectator calls. Roster ranks come from the stored rank snapshots instead;
* when no player got an answer at all (e.g. the key is missing) nothing is written, so
  ``checked_at`` keeps saying when the roster was last really checked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from hextrack.db.engine import session_scope
from hextrack.db.repo import app_state as app_state_repo
from hextrack.db.repo import summoners as summoners_repo
from hextrack.demo.names import DEMO_PUUID_PREFIX
from hextrack.ingest.context import IngestContext
from hextrack.riot.errors import (
    RiotError,
    RiotForbidden,
    RiotKeyMissing,
    RiotRateLimited,
    RiotUnavailable,
)
from hextrack.riot.schemas import CurrentGameInfoDto

logger = logging.getLogger(__name__)

STATE_KEY = "live_games"
#: A game carried over from an incomplete round is dropped once it wasn't seen for this long.
CARRY_OVER_MAX_AGE: Final = timedelta(hours=1)
#: Errors kept in a LiveReport.
MAX_REPORTED_ERRORS: Final = 20

#: Errors that end the round: nothing after them would succeed either.
_ROUND_ENDING: Final = (RiotForbidden, RiotKeyMissing, RiotRateLimited, RiotUnavailable)
_CUSTOM_GAME_TYPE: Final = "CUSTOM_GAME"


@dataclass(slots=True)
class LiveReport:
    checked: int = 0
    games: int = 0
    rank_lookups: int = 0
    errors: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(message)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_custom(game: CurrentGameInfoDto) -> bool:
    return game.game_type == _CUSTOM_GAME_TYPE or not game.game_queue_config_id


def _game_id(entry: Any) -> int | None:
    """``info.gameId`` of a stored game entry, or None when the entry is malformed."""
    if not isinstance(entry, dict):
        return None
    info = entry.get("info")
    game_id = info.get("gameId") if isinstance(info, dict) else None
    return game_id if isinstance(game_id, int) else None


def _puuids_of(entry: dict[str, Any]) -> set[str]:
    participants = entry["info"].get("participants")
    if not isinstance(participants, list):
        return set()
    return {p["puuid"] for p in participants if isinstance(p, dict) and p.get("puuid")}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def refresh_live_games(ctx: IngestContext) -> LiveReport:
    """Check every tracked player, then replace the stored state (own session and commit)."""
    report = LiveReport()
    async with ctx.session_factory() as session:
        roster = await summoners_repo.list_tracked(session)
        previous = await app_state_repo.get_state(session, STATE_KEY) or {}
    # Demo players have synthetic puuids Riot doesn't know (see the poller).
    tracked = [s.puuid for s in roster if not s.puuid.startswith(DEMO_PUUID_PREFIX)]
    tracked_set = set(tracked)
    previous_games: dict[int, dict[str, Any]] = {}
    for entry in previous.get("games") or []:
        game_id = _game_id(entry)
        if game_id is not None:
            previous_games[game_id] = entry

    # --- spectator: one call per roster player not already found in a game -----------------
    found: dict[int, CurrentGameInfoDto] = {}
    #: Roster players Riot answered for this round (in a game, or not).
    resolved: set[str] = set()
    complete = True
    stopped = False
    for puuid in tracked:
        if puuid in resolved:
            continue
        report.checked += 1
        try:
            game = await ctx.riot.active_game_by_puuid(puuid)
        except _ROUND_ENDING as exc:
            logger.warning("live: round stopped at %s: %s", puuid, exc)
            report.add_error(f"{puuid}: {exc}")
            complete, stopped = False, True
            break
        except RiotError as exc:
            logger.warning("live: %s skipped: %s", puuid, exc)
            report.add_error(f"{puuid}: {exc}")
            complete = False
            continue
        resolved.add(puuid)
        if game is None:
            continue
        resolved.update(p.puuid for p in game.participants if p.puuid in tracked_set)
        if not _is_custom(game):
            found.setdefault(game.game_id, game)

    if tracked and not resolved:
        return report  # nothing learned (key missing, Riot down): keep the old checked_at

    now = _utcnow()
    games: list[dict[str, Any]] = []
    for game_id, game in found.items():
        before = previous_games.get(game_id)
        ranks = before.get("ranks") if before is not None else None
        games.append(
            {
                "info": game.model_dump(by_alias=True, mode="json"),
                "ranks": dict(ranks) if isinstance(ranks, dict) else {},
                "first_seen_at": (before or {}).get("first_seen_at") or now.isoformat(),
                "seen_at": now.isoformat(),
            }
        )
    if not complete:
        # Keep what this round couldn't re-check, unchanged, while it is recent.
        for game_id, entry in previous_games.items():
            if game_id in found or _puuids_of(entry) & resolved:
                continue
            seen_at = _parse_time(entry.get("seen_at"))
            if seen_at is None or now - seen_at > CARRY_OVER_MAX_AGE:
                continue
            games.append(entry)

    # --- league-v4 for non-roster participants whose rank isn't stored yet -----------------
    # After a round-ending error they would fail too; missing ranks are retried next round.
    ranks_ok = not stopped
    for entry in games:
        if entry["info"].get("gameId") not in found:
            continue
        ranks = entry["ranks"]
        for puuid in sorted(_puuids_of(entry) - tracked_set - ranks.keys()):
            if not ranks_ok:
                break
            report.rank_lookups += 1
            try:
                entries = await ctx.riot.league_entries_by_puuid(puuid)
            except _ROUND_ENDING as exc:
                logger.warning("live: rank lookups stopped at %s: %s", puuid, exc)
                report.add_error(f"ranks {puuid}: {exc}")
                ranks_ok = False
                break
            except RiotError as exc:
                logger.warning("live: rank of %s skipped: %s", puuid, exc)
                report.add_error(f"ranks {puuid}: {exc}")
                continue
            ranks[puuid] = [e.model_dump(by_alias=True, mode="json") for e in entries]

    async with session_scope(ctx.session_factory) as session:
        await app_state_repo.set_state(
            session, STATE_KEY, {"checked_at": now.isoformat(), "games": games}
        )
    report.games = len(games)
    return report
