"""Core ingestion operations (owner: B2).

All functions take an open ``session`` and do **not** commit; the caller owns the
transaction boundary (the poller commits per match / per summoner).

Riot calls are made before anything is written wherever possible, so a Riot failure leaves
the session clean and the caller can simply carry on with the next unit of work.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import RankSnapshot, Summoner
from hextrack.db.repo import matches as matches_repo
from hextrack.db.repo import ranks as ranks_repo
from hextrack.db.repo import summoners as summoners_repo
from hextrack.ingest import events
from hextrack.ingest.context import IngestContext
from hextrack.ingest.mapping import InvalidMatchPayload, MappedMatch, is_scorable, map_match
from hextrack.rank import (
    APEX_TIERS,
    DIVISION_ORDER,
    RANK_HEARTBEAT_INTERVAL,
    RANKED_QUEUE_TYPES,
    compare_tiers,
    normalize_tier,
    rank_value,
)
from hextrack.riot.errors import RiotBadResponse, RiotNotFound
from hextrack.riot.schemas import LeagueEntryDto
from hextrack.riotid import normalize_game_name, normalize_tag_line, riot_id_key

logger = logging.getLogger(__name__)

#: A tier change is only announced when the standing it is compared against is this fresh.
#: Anything older (the worker was down, a legacy import, a player added months later) is
#: recorded silently instead of being posted to Discord as news.
TIER_EVENT_MAX_AGE: Final = 2 * RANK_HEARTBEAT_INTERVAL
#: Upper bound on match ids collected by one season backfill (10 pages of 100).
MAX_BACKFILL_IDS: Final = 1000
#: Match-v5 ids filter: ranked queues only.
MATCH_TYPE: Final = "ranked"
#: Steady-state discovery lists from ``synced_through`` minus this much, so a match Riot
#: indexed late is still picked up (games of one player never overlap, so the watermark
#: itself is the start of a finished game).
SYNC_OVERLAP: Final = timedelta(hours=1)
#: First key of the two-key ``pg_advisory_xact_lock`` that serialises concurrent refreshes
#: of one summoner (the worker and an on-demand request), so rank snapshots never duplicate.
_REFRESH_LOCK_NAMESPACE: Final = 0x4854
#: How many chained renames :func:`store_identity` follows when freeing a Riot ID.
_MAX_RENAME_CHAIN: Final = 3


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class IngestResult:
    match_id: str
    #: False when the match already existed (ON CONFLICT DO NOTHING).
    created: bool
    #: True when this call wrote AI scores for the participants.
    scored: bool
    #: Number of participant rows in the match.
    participants: int


# --- summoner identity -------------------------------------------------------------------


async def store_identity(
    ctx: IngestContext,
    session: AsyncSession,
    *,
    puuid: str,
    game_name: str,
    tag_line: str,
    platform: str | None = None,
    profile_icon_id: int | None = None,
    summoner_level: int | None = None,
) -> Summoner:
    """Upsert a summoner under its current Riot ID.

    If another stored account still holds that Riot ID (it renamed and this player took
    the name), the other account's current Riot ID is looked up through account-v1 and
    stored first, so the case-insensitive unique index never trips.
    """
    platform = (platform or ctx.settings.riot_platform).lower()
    await _release_riot_id(ctx, session, game_name, tag_line, platform, owner=puuid, depth=0)
    return await summoners_repo.upsert_summoner(
        session,
        puuid=puuid,
        game_name=game_name,
        tag_line=tag_line,
        platform=platform,
        profile_icon_id=profile_icon_id,
        summoner_level=summoner_level,
    )


async def _release_riot_id(
    ctx: IngestContext,
    session: AsyncSession,
    game_name: str,
    tag_line: str,
    platform: str,
    *,
    owner: str,
    depth: int,
) -> None:
    holder = await summoners_repo.find_riot_id_holder(
        session, game_name, tag_line, platform, exclude_puuid=owner
    )
    if holder is None:
        return
    wanted = riot_id_key(game_name, tag_line)
    try:
        account = await ctx.riot.account_by_puuid(holder.puuid)
    except RiotNotFound:
        account = None
    if account is not None and account.game_name and account.tag_line:
        current = riot_id_key(account.game_name, account.tag_line)
        if current == wanted:
            raise RiotBadResponse(
                f"Riot reports {game_name}#{tag_line} for two accounts ({owner}, {holder.puuid})"
            )
        if depth >= _MAX_RENAME_CHAIN:
            raise RiotBadResponse(f"too many chained renames while storing {game_name}#{tag_line}")
        await _release_riot_id(
            ctx,
            session,
            account.game_name,
            account.tag_line,
            platform,
            owner=holder.puuid,
            depth=depth + 1,
        )
        logger.info(
            "summoner %s renamed %s -> %s#%s",
            holder.puuid,
            holder.riot_id,
            account.game_name,
            account.tag_line,
        )
        holder.game_name = normalize_game_name(account.game_name)
        holder.tag_line = normalize_tag_line(account.tag_line)
    else:
        # The account no longer exists: park its stale Riot ID under a unique placeholder.
        logger.warning("summoner %s (%s) no longer exists at Riot", holder.puuid, holder.riot_id)
        holder.tag_line = f"{holder.tag_line}~{holder.puuid[:8]}"
    await session.flush([holder])


# --- rank snapshots ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankState:
    """A league-v4 entry normalised for storage (``rank`` is None for apex tiers)."""

    queue_type: str
    tier: str
    rank: str | None
    lp: int
    wins: int
    losses: int
    rank_value: int

    def same_standing(self, snapshot: RankSnapshot) -> bool:
        return (self.tier, self.rank, self.lp, self.wins, self.losses) == (
            snapshot.tier,
            snapshot.rank,
            snapshot.lp,
            snapshot.wins,
            snapshot.losses,
        )


def rank_state(entry: LeagueEntryDto) -> RankState | None:
    """Normalise one league entry; None for non-ranked-SR queues or malformed tiers."""
    if entry.queue_type not in RANKED_QUEUE_TYPES:
        return None
    try:
        tier = normalize_tier(entry.tier)
    except ValueError:
        logger.warning("ignoring league entry with unknown tier %r", entry.tier)
        return None
    division: str | None = None
    if tier not in APEX_TIERS:
        division = (entry.rank or "").strip().upper()
        if division not in DIVISION_ORDER:
            logger.warning("ignoring %s league entry with unknown division %r", tier, entry.rank)
            return None
    return RankState(
        queue_type=entry.queue_type,
        tier=tier,
        rank=division,
        lp=entry.league_points,
        wins=entry.wins,
        losses=entry.losses,
        rank_value=rank_value(tier, division, entry.league_points),
    )


SnapshotAction = Literal["change", "heartbeat"]


def snapshot_action(
    previous: RankSnapshot | None, state: RankState, now: datetime
) -> SnapshotAction | None:
    """Change-only policy: a row on the first sighting or any change in tier / division /
    LP / wins / losses; otherwise a heartbeat row once :data:`RANK_HEARTBEAT_INTERVAL` has
    passed since the newest row; otherwise nothing."""
    if previous is None or not state.same_standing(previous):
        return "change"
    if now - previous.taken_at >= RANK_HEARTBEAT_INTERVAL:
        return "heartbeat"
    return None


def announces_tier_change(
    previous: RankSnapshot, summoner: Summoner, now: datetime, season_start: datetime
) -> bool:
    """Whether a tier change from ``previous`` is news worth posting to Discord.

    A tier event only makes sense when the standing it is compared against still described
    the player recently: the first refresh after the worker was down for days, after a
    legacy import, or right after a player was added to the roster would otherwise announce
    a promotion that happened months ago. Placements after a season reset are skipped for
    the same reason (the old snapshot is last season's rank).
    """
    if not summoner.is_tracked:
        return False
    if previous.taken_at < season_start <= now:
        return False
    return now - previous.taken_at <= TIER_EVENT_MAX_AGE


async def _record_ranks(
    ctx: IngestContext,
    session: AsyncSession,
    summoner: Summoner,
    entries: Sequence[LeagueEntryDto],
    now: datetime,
) -> None:
    for entry in entries:
        state = rank_state(entry)
        if state is None:
            continue
        previous = await ranks_repo.latest_snapshot(session, summoner.puuid, state.queue_type)
        action = snapshot_action(previous, state, now)
        if action is None:
            continue
        await ranks_repo.insert_snapshot(
            session,
            puuid=summoner.puuid,
            queue_type=state.queue_type,
            tier=state.tier,
            rank=state.rank,
            lp=state.lp,
            wins=state.wins,
            losses=state.losses,
            rank_value=state.rank_value,
            taken_at=now,
            is_heartbeat=action == "heartbeat",
        )
        if previous is None or previous.tier == state.tier:
            continue
        if not announces_tier_change(previous, summoner, now, ctx.settings.season_start):
            if summoner.is_tracked:
                logger.info(
                    "%s %s %s -> %s not announced: last standing is from %s",
                    summoner.riot_id,
                    state.queue_type,
                    previous.tier,
                    state.tier,
                    previous.taken_at.isoformat(timespec="seconds"),
                )
            continue
        kind: events.EventKind = (
            "tier_up" if compare_tiers(state.tier, previous.tier) > 0 else "tier_down"
        )
        await events.enqueue_event(
            session,
            kind,
            events.tier_event_payload(
                puuid=summoner.puuid,
                game_name=summoner.game_name,
                tag_line=summoner.tag_line,
                platform=summoner.platform,
                profile_icon_id=summoner.profile_icon_id,
                queue_type=state.queue_type,
                old_tier=previous.tier,
                old_rank=previous.rank,
                old_lp=previous.lp,
                new_tier=state.tier,
                new_rank=state.rank,
                new_lp=state.lp,
                wins=state.wins,
                losses=state.losses,
                rank_value=state.rank_value,
                previous_taken_at=previous.taken_at,
            ),
        )


async def _lock_summoner(session: AsyncSession, puuid: str) -> None:
    """Transaction-scoped lock serialising refreshes of one summoner across processes."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:puuid))"),
        {"ns": _REFRESH_LOCK_NAMESPACE, "puuid": puuid},
    )


async def refresh_summoner(
    ctx: IngestContext, session: AsyncSession, puuid: str, *, verify_identity: bool = False
) -> Summoner:
    """summoner-v4 + league-v4 for ``puuid``; upsert the Summoner row (creating it via
    account-v1 when unknown), insert a rank snapshot per queue only on change or as a 24h
    heartbeat, enqueue ``tier_up`` / ``tier_down`` events on tier change for tracked players,
    and set ``last_refreshed_at``. Raises RiotError subclasses unchanged.

    ``verify_identity=True`` also re-reads the Riot ID through account-v1 for a known
    player (the Update button uses it so renames are picked up).
    """
    riot = ctx.riot
    existing = await summoners_repo.get_by_puuid(session, puuid)
    profile = await riot.summoner_by_puuid(puuid)
    account = None
    if verify_identity or existing is None or not existing.game_name or not existing.tag_line:
        account = await riot.account_by_puuid(puuid)
        if not account.game_name or not account.tag_line:
            raise RiotBadResponse(f"account {puuid} has no Riot ID")
    entries = await riot.league_entries_by_puuid(puuid)

    now = _utcnow()
    await _lock_summoner(session, puuid)
    if account is not None:
        summoner = await store_identity(
            ctx,
            session,
            puuid=puuid,
            game_name=account.game_name or "",
            tag_line=account.tag_line or "",
            platform=existing.platform if existing is not None else None,
            profile_icon_id=profile.profile_icon_id,
            summoner_level=profile.summoner_level,
        )
    else:
        assert existing is not None
        summoner = existing
        summoner.profile_icon_id = profile.profile_icon_id
        summoner.summoner_level = profile.summoner_level
    summoner.last_refreshed_at = now
    await session.flush([summoner])
    await _record_ranks(ctx, session, summoner, entries, now)
    return summoner


# --- match discovery -----------------------------------------------------------------------


def _unique(ids: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(ids))


#: How discovery picked the range it listed (see :func:`discover`).
DiscoveryMode = Literal["season", "since", "window"]


@dataclass(slots=True)
class Discovery:
    """What Riot listed for one player and what of it is still missing."""

    puuid: str
    mode: DiscoveryMode
    #: Every listed id, newest first (Riot's own order).
    listed: list[str]
    #: The listed ids that are not stored yet, newest first.
    missing: list[str]
    #: The listing reached the bottom of its range (Riot returned a short page); False
    #: means it stopped at ``max_ids`` and older games were never looked at.
    complete: bool
    #: ``startTime`` sent to Riot (None: no lower bound).
    start_time: datetime | None


async def discover(
    ctx: IngestContext,
    session: AsyncSession,
    puuid: str,
    *,
    backfill: bool,
    max_ids: int | None = None,
) -> Discovery:
    """List ranked match ids for ``puuid`` (newest first) and say which are not stored.

    Every listing is anchored at a point below which history is known to be complete, and
    covers everything from there to now. That is what makes a partly ingested gap safe: the
    part that was not fetched is simply listed again next time.

    * ``synced_through`` set (mode ``since``): from the watermark (minus
      :data:`SYNC_OVERLAP`), paged to the end. Normally one page.
    * no watermark yet, but a season backfill was asked for or games are already stored
      (mode ``season``): the whole season from ``season_start``. This is the first pass for
      a newly tracked player, and the one pass that anchors the watermark for rows that
      predate it (a legacy import, a lookup that was interrupted).
    * nothing stored and no backfill (mode ``window``): one page of the newest
      ``poll_match_count`` ids, the "recent games" a first lookup shows.

    Paging stops after ``max_ids`` ids (:data:`MAX_BACKFILL_IDS` by default); an on-demand
    request passes a smaller value so one click cannot page through a whole season.
    Ranked queues only (``type=ranked``). Stored ids are filtered out with one ``= ANY()``
    query.
    """
    settings = ctx.settings
    limit = max_ids if max_ids is not None else MAX_BACKFILL_IDS
    synced = await summoners_repo.get_synced_through(session, puuid)
    start_time: datetime | None
    if synced is not None:
        mode: DiscoveryMode = "since"
        start_time = max(synced - SYNC_OVERLAP, settings.season_start)
    elif backfill or await matches_repo.has_games(session, puuid):
        mode, start_time = "season", settings.season_start
    else:
        mode, start_time = "window", None
    if start_time is not None:
        ids, complete = await _paged_ids(
            ctx, puuid, count=settings.backfill_count, start_time=start_time, limit=limit
        )
    else:
        page = await ctx.riot.match_ids_by_puuid(
            puuid, start=0, count=settings.poll_match_count, type_=MATCH_TYPE
        )
        ids, complete = _unique(page), len(page) < settings.poll_match_count
    existing = await matches_repo.existing_match_ids(session, ids)
    return Discovery(
        puuid=puuid,
        mode=mode,
        listed=ids,
        missing=[match_id for match_id in ids if match_id not in existing],
        complete=complete,
        start_time=start_time,
    )


async def discover_matches(
    ctx: IngestContext, session: AsyncSession, puuid: str, *, backfill: bool
) -> list[str]:
    """The not-yet-stored ids of :func:`discover`, newest first."""
    return (await discover(ctx, session, puuid, backfill=backfill)).missing


async def _paged_ids(
    ctx: IngestContext,
    puuid: str,
    *,
    count: int,
    start_time: datetime,
    limit: int,
) -> tuple[list[str], bool]:
    """Page ranked match ids newer than ``start_time``; returns (ids, complete).

    Paging ends at a short page (complete) or at ``limit`` ids (incomplete: older games
    exist that this listing did not look at). It deliberately does **not** stop at the
    first page that happens to contain a stored id: stored history is only contiguous
    below the watermark, and stopping early is how games in a half-filled gap were lost.
    """
    collected: list[str] = []
    start = 0
    complete = False
    while len(collected) < limit:
        page = await ctx.riot.match_ids_by_puuid(
            puuid, start=start, count=count, type_=MATCH_TYPE, start_time=start_time
        )
        collected.extend(page)
        if len(page) < count:
            complete = True
            break
        start += count
    return _unique(collected)[:limit], complete


async def advance_sync(
    session: AsyncSession, discovery: Discovery, resolved: Collection[str]
) -> datetime | None:
    """Move ``summoners.synced_through`` up over the stored prefix of ``discovery``.

    ``resolved`` are the ids this run dealt with: stored, or answered by Riot with nothing
    usable (404 / corrupt payload), which no amount of retrying would change. Walking the
    listing from its oldest id, the watermark stops at the first id that is neither, so a
    partial ingest, a rate limit or one failing match simply leaves the rest to the next
    pass. Returns the new watermark, or None when it did not move.
    """
    if not discovery.complete:
        # The listing stopped at ``max_ids``: older games exist that it never looked at, so
        # nothing about them is settled.
        return None
    starts = await matches_repo.match_starts(session, discovery.listed)
    watermark: datetime | None = None
    for match_id in reversed(discovery.listed):
        start = starts.get(match_id)
        if start is not None:
            watermark = start if watermark is None or start > watermark else watermark
        elif match_id not in resolved:
            break
    if watermark is None:
        if discovery.start_time is None or discovery.listed:
            return None
        # Nothing to list in this range at all (a player with no ranked games this season):
        # the range itself is synced.
        watermark = discovery.start_time
    return await summoners_repo.advance_synced_through(session, discovery.puuid, watermark)


# --- match ingestion -----------------------------------------------------------------------


async def ingest_match(
    ctx: IngestContext, session: AsyncSession, match_id: str
) -> IngestResult | None:
    """Fetch, validate and store one match. Returns None if Riot says 404 or the payload
    is invalid (nothing is written in that case); other RiotErrors propagate.

    An already stored match is not fetched again (``created=False``, ``scored=False``).
    """
    stored = await matches_repo.stored_match(session, match_id)
    if stored is not None:
        return IngestResult(
            match_id=match_id, created=False, scored=False, participants=stored.participants
        )
    try:
        raw = await ctx.riot.match(match_id)
    except RiotNotFound:
        logger.info("match %s not found at Riot; skipped", match_id)
        return None
    except RiotBadResponse as exc:
        logger.warning("match %s: invalid response from Riot (%s); skipped", match_id, exc)
        return None
    payload_id = _payload_match_id(raw)
    if payload_id != match_id:
        logger.warning("match %s: payload is for %r; skipped", match_id, payload_id)
        return None
    try:
        return await ingest_match_json(ctx, session, raw)
    except InvalidMatchPayload as exc:
        logger.warning("match %s: invalid payload (%s); skipped", match_id, exc)
        return None


def _payload_match_id(raw: object) -> str | None:
    if not isinstance(raw, Mapping):
        return None
    metadata = raw.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get("matchId")
    return value if isinstance(value, str) else None


def _score(ctx: IngestContext, mapped: MappedMatch) -> dict[str, float] | None:
    """AI scores for every participant, or None (no model, not scorable, or a model
    error / incomplete output: the match is then stored unscored for a later rescore)."""
    scorer = ctx.scorer
    if scorer is None or not is_scorable(mapped.match):
        return None
    scores: dict[str, float] = {}
    try:
        raw_scores = scorer.score_match(int(mapped.match["game_duration"]), mapped.participants)
        for participant in mapped.participants:
            value = raw_scores.get(participant["puuid"])
            if value is None:
                continue
            score = float(value)
            if math.isfinite(score):
                scores[participant["puuid"]] = min(max(score, 0.0), 1.0)
    except Exception:
        logger.exception("AI scoring failed for %s; stored unscored", mapped.match_id)
        return None
    if len(scores) != len(mapped.participants):
        logger.warning(
            "AI model returned %d/%d valid scores for %s; stored unscored",
            len(scores),
            len(mapped.participants),
            mapped.match_id,
        )
        return None
    return scores


async def _adopt_riot_ids(
    session: AsyncSession, known: Mapping[str, Summoner], mapped: MappedMatch
) -> None:
    """Renames: when this match is a known player's newest game and they used a different
    Riot ID in it, store that Riot ID. Skipped when another stored row holds the new Riot ID
    (the next account-v1 lookup of either player sorts that out)."""
    game_start: datetime = mapped.match["game_start"]
    for participant in mapped.participants:
        summoner = known.get(participant["puuid"])
        name, tag = participant["riot_id_game_name"], participant["riot_id_tagline"]
        if summoner is None or not name or not tag:
            continue
        if summoner.last_seen is not None and summoner.last_seen > game_start:
            continue
        if riot_id_key(name, tag) == riot_id_key(summoner.game_name, summoner.tag_line):
            continue
        holder = await summoners_repo.find_riot_id_holder(
            session, name, tag, summoner.platform, exclude_puuid=summoner.puuid
        )
        if holder is not None:
            logger.info(
                "summoner %s played as %s#%s, which %s holds; name not updated",
                summoner.puuid,
                name,
                tag,
                holder.puuid,
            )
            continue
        logger.info("summoner %s renamed %s -> %s#%s", summoner.puuid, summoner.riot_id, name, tag)
        summoner.game_name = normalize_game_name(name)
        summoner.tag_line = normalize_tag_line(tag)
        await session.flush([summoner])


async def _enqueue_game_events(
    session: AsyncSession,
    tracked: Mapping[str, Summoner],
    mapped: MappedMatch,
    scores: Mapping[str, float] | None,
    model_version: str | None,
) -> None:
    match = mapped.match
    for participant in mapped.participants:
        summoner = tracked.get(participant["puuid"])
        if summoner is None:
            continue
        kills, deaths, assists = participant["kills"], participant["deaths"], participant["assists"]
        ai_score = scores.get(participant["puuid"]) if scores else None
        payload = events.game_event_payload(
            puuid=summoner.puuid,
            game_name=summoner.game_name or participant["riot_id_game_name"],
            tag_line=summoner.tag_line or participant["riot_id_tagline"],
            profile_icon_id=(
                participant["profile_icon_id"]
                if participant["profile_icon_id"] is not None
                else summoner.profile_icon_id
            ),
            match_id=mapped.match_id,
            queue_id=match["queue_id"],
            champion_id=participant["champion_id"],
            champion_name=participant["champion_name"],
            team_position=participant["team_position"],
            win=participant["win"],
            remake=match["remake"],
            kills=kills,
            deaths=deaths,
            assists=assists,
            ai_score=ai_score,
            model_version=model_version if ai_score is not None else None,
            game_start=match["game_start"],
            game_duration=match["game_duration"],
        )
        await events.enqueue_event(session, "new_match", payload)
        if match["remake"]:
            continue
        if events.is_great_game(kills, deaths, assists):
            await events.enqueue_event(session, "great_game", payload)
        elif events.is_bad_game(kills, deaths, assists):
            await events.enqueue_event(session, "bad_game", payload)


async def ingest_match_json(
    ctx: IngestContext,
    session: AsyncSession,
    raw: dict[str, Any],
    *,
    enqueue_events: bool = True,
) -> IngestResult:
    """Store an already-fetched payload (also used by the legacy importer and demo seed).

    Maps via ``hextrack.ingest.mapping.map_match`` (raises ``InvalidMatchPayload`` before
    anything is written), upserts the match and participants with ON CONFLICT DO NOTHING,
    scores all participants when ``ctx.scorer`` is set and the match ``is_scorable``,
    advances ``Summoner.last_seen`` (adopting the Riot ID used in the game when it is the
    player's newest) and, when ``enqueue_events`` and the match is new, enqueues
    ``new_match`` / ``great_game`` / ``bad_game`` events for tracked players whose game ended
    within :data:`hextrack.ingest.events.GAME_EVENT_MAX_AGE`.
    """
    mapped = map_match(raw)
    match = mapped.match
    match_id = mapped.match_id
    created = await matches_repo.insert_match(session, match)
    scores: dict[str, float] | None = None
    model_version: str | None = None
    if created:
        await matches_repo.insert_participants(session, mapped.participants)
        scores = _score(ctx, mapped)
        if scores is not None and ctx.scorer is not None:
            model_version = str(ctx.scorer.version)
            await matches_repo.write_scores(
                session,
                match_id,
                scores,
                model_version=model_version,
                scored_at=_utcnow(),
                complete=True,
            )

    puuids = [p["puuid"] for p in mapped.participants]
    known = await summoners_repo.known_among(session, puuids)
    if known:
        await _adopt_riot_ids(session, known, mapped)
        await summoners_repo.touch_last_seen(session, list(known), match["game_start"])

    if created and enqueue_events:
        tracked = {puuid: s for puuid, s in known.items() if s.is_tracked}
        game_end = match["game_start"] + timedelta(seconds=match["game_duration"])
        if tracked and _utcnow() - game_end <= events.GAME_EVENT_MAX_AGE:
            await _enqueue_game_events(session, tracked, mapped, scores, model_version)

    return IngestResult(
        match_id=match_id,
        created=created,
        scored=scores is not None,
        participants=len(mapped.participants),
    )
