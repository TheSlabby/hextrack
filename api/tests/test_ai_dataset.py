"""``hextrack model export-dataset``: gzipped CSV of every scorable participant."""

from __future__ import annotations

import csv
import gzip
import io

from hextrack.db.engine import make_sync_engine
from hextrack.hextrack_ai.dataset import EXPORT_CHALLENGES, export_dataset, stat_columns
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
        other_queue = io.BytesIO()
        export_dataset(engine, other_queue, queues=[450])
    finally:
        engine.dispose()

    rows = _read(buf.getvalue())
    assert size > 0
    assert len(rows) == 30
    assert len(_read(limited.getvalue())) == 10
    assert _read(other_queue.getvalue()) == []
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
