"""Match timelines: which games get one, and what is kept of it.

Only the extracted sequences are stored (``match_timeline_players``), never the timeline
itself (about 1 MB of JSON per game). Pure functions; the crawler's backlog step
(:mod:`hextrack.ingest.crawler`) fetches and stores.

Sampling (:func:`timeline_sampled`, the same rule as migration 0004's UPDATE): with
``settings.timelines`` on, a ranked solo / flex game (420 / 440) that is not a remake and
started at or after the season start gets a timeline when it is a roster game, or when the
number after the last "_" of its match id is a multiple of ``settings.timeline_sample``.
Demo games (``DEMO_`` ids) never do.

Extraction (:func:`extract_timeline`), per participant, events of every frame in timestamp
order (ms in the payload, whole seconds stored):

* ``ITEM_PURCHASED``: ``(itemId, second)`` appended;
* ``ITEM_UNDO`` with ``beforeId != 0``: the last purchase of ``beforeId`` removed (an undone
  sell has ``beforeId == 0`` and is ignored);
* ``ITEM_SOLD`` / ``ITEM_DESTROYED``: ignored (the final inventory is stored with the match);
* ``SKILL_LEVEL_UP`` with ``levelUpType == "NORMAL"``: ``skillSlot`` (1-4) appended
  ("EVOLVE" level-ups, e.g. Kha'Zix, are not skill points).

Timeline participant ids are matched to the stored rows through ``info.participants[].puuid``
(or ``metadata.participants`` by position when a payload has no puuids there); a timeline
whose players are not exactly the stored match's raises :class:`TimelineMismatch`. Anything
malformed raises :class:`InvalidTimeline`, so an error body is never stored as a timeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from hextrack.config import Settings

#: Queues whose games get a timeline (ranked solo / flex; the champion pages' queues).
TIMELINE_QUEUES: Final = frozenset({420, 440})
#: Timeline states (``matches.timeline_state``; NULL = not sampled).
STATE_PENDING: Final = "pending"
STATE_OK: Final = "ok"
STATE_MISSING: Final = "missing"
STATE_FAILED: Final = "failed"
#: Failed fetches (other than rate limits) before a game is given up as "failed".
TIMELINE_MAX_ATTEMPTS: Final = 3
#: ``purchase_s`` is a smallint.
_MAX_SECONDS: Final = 32_767
_DEMO_MATCH_PREFIX: Final = "DEMO_"

EVENT_ITEM_PURCHASED: Final = "ITEM_PURCHASED"
EVENT_ITEM_UNDO: Final = "ITEM_UNDO"
EVENT_SKILL_LEVEL_UP: Final = "SKILL_LEVEL_UP"
LEVEL_UP_NORMAL: Final = "NORMAL"


class InvalidTimeline(ValueError):
    """The timeline payload is not a usable match-v5 timeline (nothing is stored)."""


class TimelineMismatch(InvalidTimeline):
    """The timeline's players are not the stored match's players."""


# --- sampling ----------------------------------------------------------------------------------


def match_number(match_id: str) -> int | None:
    """The number after the last "_" of a match id ("NA1_5123" -> 5123), or None."""
    _, sep, tail = match_id.rpartition("_")
    if not sep or not tail.isdigit():
        return None
    return int(tail)


def timeline_sampled(
    match_id: str,
    source: str,
    queue_id: int | None,
    remake: bool,
    game_start: datetime,
    settings: Settings,
) -> bool:
    """Whether a game should get its timeline fetched (see the module docstring)."""
    if not settings.timelines:
        return False
    if queue_id not in TIMELINE_QUEUES or remake or game_start < settings.season_start:
        return False
    if match_id.startswith(_DEMO_MATCH_PREFIX):
        return False
    if source == "roster":
        return True
    number = match_number(match_id)
    return number is not None and number % settings.timeline_sample == 0


# --- extraction --------------------------------------------------------------------------------


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_int(event: Mapping[str, Any], key: str, where: str) -> int:
    value = event.get(key)
    if not _is_int(value):
        raise InvalidTimeline(f"{where}: {key} is not an integer")
    return int(value)


def _participant_puuids(root: Mapping[str, Any], info: Mapping[str, Any]) -> dict[int, str]:
    """Timeline participantId -> puuid."""
    mapping: dict[int, str] = {}
    participants = info.get("participants")
    if isinstance(participants, list) and participants:
        for entry in participants:
            if not isinstance(entry, Mapping):
                raise InvalidTimeline("info.participants holds a non-object")
            pid, puuid = entry.get("participantId"), entry.get("puuid")
            if not _is_int(pid) or not isinstance(puuid, str) or not puuid:
                raise InvalidTimeline("info.participants entry without participantId / puuid")
            if pid in mapping:
                raise InvalidTimeline(f"participantId {pid} appears twice")
            mapping[int(pid)] = puuid
        return mapping
    metadata = root.get("metadata")
    listed = metadata.get("participants") if isinstance(metadata, Mapping) else None
    if not isinstance(listed, list) or not listed:
        raise InvalidTimeline("timeline has no participants")
    for index, puuid in enumerate(listed):
        if not isinstance(puuid, str) or not puuid:
            raise InvalidTimeline("metadata.participants holds a non-string")
        mapping[index + 1] = puuid
    return mapping


def _events(info: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    frames = info.get("frames")
    if not isinstance(frames, list) or not frames:
        raise InvalidTimeline("timeline has no frames")
    events: list[Mapping[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, Mapping):
            raise InvalidTimeline("a frame is not an object")
        frame_events = frame.get("events", [])
        if not isinstance(frame_events, list):
            raise InvalidTimeline("frame events is not a list")
        for event in frame_events:
            if not isinstance(event, Mapping):
                raise InvalidTimeline("an event is not an object")
            events.append(event)
    for event in events:
        if not _is_int(event.get("timestamp")) or event["timestamp"] < 0:
            raise InvalidTimeline(f"{event.get('type')} event without a valid timestamp")
    # Stable: events sharing a timestamp keep payload order (a purchase before its undo).
    events.sort(key=lambda event: int(event["timestamp"]))
    return events


def extract_timeline(
    timeline_json: Any,
    match_participants: Mapping[str, int],
    *,
    match_id: str | None = None,
) -> list[dict[str, Any]]:
    """``match_timeline_players`` rows (one per stored participant) from a raw timeline.

    ``match_participants`` maps each stored participant's puuid to its ``participant_id``;
    ``match_id`` (default: the payload's ``metadata.matchId``) must match the payload.
    Raises :class:`TimelineMismatch` when the players differ and :class:`InvalidTimeline`
    for anything malformed.
    """
    if not isinstance(timeline_json, Mapping):
        raise InvalidTimeline("timeline is not a JSON object")
    metadata = timeline_json.get("metadata")
    info = timeline_json.get("info")
    if not isinstance(metadata, Mapping) or not isinstance(info, Mapping):
        raise InvalidTimeline("timeline without metadata / info (an error body?)")
    payload_id = metadata.get("matchId")
    if not isinstance(payload_id, str) or not payload_id:
        raise InvalidTimeline("timeline without metadata.matchId")
    if match_id is not None and payload_id.casefold() != match_id.casefold():
        raise TimelineMismatch(f"timeline is for {payload_id}, not {match_id}")
    match_id = match_id or payload_id

    by_timeline_id = _participant_puuids(timeline_json, info)
    if set(by_timeline_id.values()) != set(match_participants) or len(by_timeline_id) != len(
        match_participants
    ):
        raise TimelineMismatch(f"timeline players of {match_id} differ from the stored match")
    # timeline participantId -> stored participant_id
    ids = {tid: int(match_participants[puuid]) for tid, puuid in by_timeline_id.items()}

    purchases: dict[int, list[tuple[int, int]]] = {pid: [] for pid in ids.values()}
    skills: dict[int, list[int]] = {pid: [] for pid in ids.values()}
    for event in _events(info):
        kind = event.get("type")
        if kind not in (EVENT_ITEM_PURCHASED, EVENT_ITEM_UNDO, EVENT_SKILL_LEVEL_UP):
            continue
        timeline_pid = _require_int(event, "participantId", kind)
        pid = ids.get(timeline_pid)
        if pid is None:
            # participantId 0 is the game itself; anything else is a malformed payload.
            if timeline_pid == 0:
                continue
            raise InvalidTimeline(f"{kind} for unknown participant {timeline_pid}")
        if kind == EVENT_ITEM_PURCHASED:
            item = _require_int(event, "itemId", kind)
            second = min(int(event["timestamp"]) // 1000, _MAX_SECONDS)
            purchases[pid].append((item, second))
        elif kind == EVENT_ITEM_UNDO:
            before = _require_int(event, "beforeId", kind)
            if before == 0:
                continue  # undoing a sell
            bought = purchases[pid]
            for index in range(len(bought) - 1, -1, -1):
                if bought[index][0] == before:
                    del bought[index]
                    break
        else:
            if event.get("levelUpType") != LEVEL_UP_NORMAL:
                continue
            slot = _require_int(event, "skillSlot", kind)
            if not 1 <= slot <= 4:
                raise InvalidTimeline(f"skillSlot {slot} out of range")
            skills[pid].append(slot)

    return [
        {
            "match_id": match_id,
            "participant_id": pid,
            "purchases": [item for item, _ in purchases[pid]],
            "purchase_s": [second for _, second in purchases[pid]],
            "skill_order": skills[pid],
        }
        for pid in sorted(ids.values())
    ]
