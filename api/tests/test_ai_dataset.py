"""``hextrack model export-dataset``: gzipped CSV of every scorable participant."""

from __future__ import annotations

import asyncio
import csv
import gzip
import io
import threading

from hextrack.db.engine import make_sync_engine
from hextrack.hextrack_ai.dataset import (
    EXPORT_CHALLENGES,
    cancel_running_exports,
    export_dataset,
    stat_columns,
)
from tests.test_ai_support import insert_matches, signal_matches


def _read(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(gzip.decompress(data).decode())))


async def test_export_dataset_rows_and_columns(clean_db, session_factory, settings):
    raws = signal_matches(3, seed=7)
    await insert_matches(session_factory, raws)
    engine = make_sync_engine(settings)
    try:
        buf = io.BytesIO()
        size = export_dataset(engine, buf)
        limited = io.BytesIO()
        export_dataset(engine, limited, max_matches=1)
        chunked = io.BytesIO()
        export_dataset(engine, chunked, chunk_matches=2)
        other_queue = io.BytesIO()
        export_dataset(engine, other_queue, queues=[450])
    finally:
        engine.dispose()

    rows = _read(buf.getvalue())
    assert size > 0
    assert len(rows) == 30
    assert len(_read(limited.getvalue())) == 10
    assert _read(other_queue.getvalue()) == []
    # chunked COPYs give the same rows (one header) in the same order: oldest game first
    assert _read(chunked.getvalue()) == rows
    starts = [r["game_start"] for r in rows]
    assert starts == sorted(starts)
    header = set(rows[0])
    assert {"match_id", "game_duration", "player", "tracked", "win", "team_position"} <= header
    assert set(stat_columns()) <= header
    assert {f"c_{name}" for name in EXPORT_CHALLENGES} <= header
    # identities stay out: hashed player key, no PUUID / Riot ID
    assert not {"puuid", "riot_id_game_name", "riot_id_tagline"} & header
    puuids = {p["puuid"] for raw in raws for p in raw["info"]["participants"]}
    assert not any(r["player"] in puuids for r in rows)
    assert all(len(r["player"]) == 16 for r in rows)
    assert len({r["player"] for r in rows}) == len(puuids)
    # each row reads its own participant's stats
    by_match = {raw["metadata"]["matchId"]: raw for raw in raws}
    for r in rows:
        p = by_match[r["match_id"]]["info"]["participants"][int(r["participant_id"]) - 1]
        assert int(r["kills"]) == p["kills"]


#: A COPY like the export's: the marker comes after some SQL, well inside the first 1 kB.
EXPORT_LIKE = (
    "COPY (WITH ch AS (SELECT pg_sleep(30) AS slept, '{}'::jsonb AS p) "
    "SELECT slept, p->'challenges' AS c FROM ch) TO STDOUT"
)


async def test_cancel_running_exports_only_cancels_exports(clean_db, settings):
    engine = make_sync_engine(settings)
    errors: list[BaseException] = []

    def run(sql: str) -> None:
        try:
            with engine.connect() as conn:
                cur = conn.connection.driver_connection.cursor()
                with cur.copy(sql) as copy:
                    for _ in copy:
                        pass
        except BaseException as exc:  # noqa: BLE001 - the cancellation is what we expect
            errors.append(exc)

    try:
        # nothing running: nothing cancelled (and this test's own connection is never a target)
        assert cancel_running_exports(engine) == []
        export = threading.Thread(target=run, args=(EXPORT_LIKE,))
        other = threading.Thread(target=run, args=("COPY (SELECT pg_sleep(1) AS x) TO STDOUT",))
        export.start()
        other.start()
        for _ in range(100):
            await asyncio.sleep(0.1)
            cancelled = cancel_running_exports(engine)
            if cancelled:
                break
        export.join(10)
        other.join(10)
        assert len(cancelled) == 1
        assert not export.is_alive()
        assert len(errors) == 1 and "cancel" in str(errors[0]).lower()  # only the export
    finally:
        engine.dispose()
