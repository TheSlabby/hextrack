"""Data crawler: keep adding ranked games of players HexTrack doesn't track, for training.

Runs inside the worker next to the roster poller and only ever uses Riot budget the poller,
live games and the website leave over (see :func:`run_crawler`). Games are stored like any
other (raw JSON, participants, AI scores) with ``matches.source = "crawl"``; no bot events.
The frontier of players to crawl lives in ``crawl_players``.
"""

from __future__ import annotations

import asyncio

from hextrack.ingest.context import IngestContext

#: app_state key for the crawler's heartbeat (counters, last error, paused reason).
STATE_KEY = "crawler"


async def run_crawler(ctx: IngestContext, stop: asyncio.Event, poll_active: asyncio.Event) -> None:
    """Crawl until ``stop`` is set. Pauses while ``poll_active`` is set (a roster poll tick is
    running) and whenever the Riot budget left over is below what the next poll needs."""
    raise NotImplementedError
