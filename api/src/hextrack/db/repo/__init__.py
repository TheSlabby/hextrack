"""Query helpers shared by ingestion, the worker and the CLI.

Each module is a set of small async functions taking an open ``AsyncSession``. None of them
commit: the caller owns the transaction boundary.

* :mod:`~hextrack.db.repo.summoners`: Riot ID lookups, upserts, roster listing, last_seen.
* :mod:`~hextrack.db.repo.matches`: existence checks, idempotent inserts, AI score writes.
* :mod:`~hextrack.db.repo.ranks`: latest rank snapshots and snapshot inserts.
* :mod:`~hextrack.db.repo.events`: bot outbox inserts and counts.
* :mod:`~hextrack.db.repo.app_state`: JSON key/value heartbeats.
"""

from __future__ import annotations

from hextrack.db.repo import app_state, events, matches, ranks, summoners

__all__ = ["app_state", "events", "matches", "ranks", "summoners"]
