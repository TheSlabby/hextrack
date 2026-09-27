from datetime import UTC, datetime, timedelta

from hextrack.api.v1.health import bot_status, crawler_status, poller_status
from hextrack.db.models import AppState
from hextrack.riot.errors import RiotForbidden
from tests.fakes import install_fakes


class _StubScorer:
    version = "20260920-1200"
    feature_names = [f"f{i}" for i in range(30)]
    meta: dict = {}

    @property
    def trained_at(self):
        return datetime(2026, 9, 20, 12, tzinfo=UTC)


async def test_health_basic(client, fake_riot):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db_ok"] is True
    assert body["version"]
    assert body["model"] == {
        "loaded": False,
        "version": None,
        "trained_at": None,
        "n_features": None,
    }
    assert body["riot"] == {"key_configured": True, "key_ok": None, "last_error": None}
    assert body["poller"] == {"last_run_at": None, "last_error": None, "running": False}
    assert body["bot"] == {
        "configured": False,
        "running": False,
        "connected": False,
        "heartbeat_at": None,
        "last_error": None,
    }
    assert body["status"] == "ok"


async def test_health_reports_model_and_rejected_key(app, client, fake_riot):
    install_fakes(app, scorer=_StubScorer())
    fake_riot.fail("summoner_by_puuid", RiotForbidden("Forbidden", status=403))
    try:
        await fake_riot.summoner_by_puuid("x")
    except RiotForbidden:
        pass
    body = (await client.get("/api/v1/health")).json()
    assert body["model"]["loaded"] is True
    assert body["model"]["version"] == "20260920-1200"
    assert body["model"]["n_features"] == 30
    assert body["model"]["trained_at"].startswith("2026-09-20T12:00:00")
    assert body["riot"]["key_ok"] is False
    assert body["riot"]["last_error"] == "Forbidden"
    assert body["status"] == "degraded"


async def test_health_without_riot_key_uses_real_client(app, client, settings):
    from hextrack.riot.client import RiotClient

    install_fakes(app, riot=RiotClient(settings))
    body = (await client.get("/api/v1/health")).json()
    assert body["riot"]["key_configured"] is False
    assert body["status"] == "degraded"


async def test_health_reads_poller_heartbeat(app, client, session_factory):
    now = datetime.now(UTC)
    async with session_factory() as s:
        s.add(
            AppState(
                key="poller",
                value={"last_run_at": now.isoformat(), "last_error": "boom", "running": True},
            )
        )
        await s.commit()
    body = (await client.get("/api/v1/health")).json()
    assert body["poller"]["running"] is True
    assert body["poller"]["last_error"] == "boom"
    assert body["poller"]["last_run_at"] is not None


def test_poller_status_staleness(settings):
    now = datetime(2026, 9, 21, 12, tzinfo=UTC)
    fresh = {"last_run_at": (now - timedelta(seconds=30)).isoformat(), "running": True}
    assert poller_status(fresh, settings, now=now).running is True
    stale = {"last_run_at": (now - timedelta(hours=2)).isoformat(), "running": True}
    assert poller_status(stale, settings, now=now).running is False
    stopped = {"last_run_at": now.isoformat(), "running": False}
    assert poller_status(stopped, settings, now=now).running is False
    assert poller_status(None, settings, now=now).running is False
    naive = {"last_run_at": "2026-09-21T11:59:00"}
    assert poller_status(naive, settings, now=now).last_run_at.tzinfo is not None


async def test_unknown_api_path_is_json_404(client):
    resp = await client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]


async def test_openapi_served(client):
    resp = await client.get("/api/openapi.json")
    assert resp.status_code == 200
    assert "/api/v1/health" in resp.json()["paths"]


async def test_health_reads_bot_heartbeat(app, client, session_factory):
    now = datetime.now(UTC)
    async with session_factory() as s:
        s.add(
            AppState(
                key="bot",
                value={
                    "running": True,
                    "heartbeat_at": now.isoformat(),
                    "connected": True,
                    "user": "HexTrack#0001",
                    "last_error": None,
                },
            )
        )
        await s.commit()
    body = (await client.get("/api/v1/health")).json()
    assert body["bot"]["running"] is True
    assert body["bot"]["connected"] is True
    assert body["bot"]["heartbeat_at"] is not None


def test_bot_status_staleness_and_config(settings):
    now = datetime(2026, 9, 21, 12, tzinfo=UTC)
    fresh = {"heartbeat_at": (now - timedelta(seconds=20)).isoformat(), "connected": True}
    assert bot_status(fresh, settings, now=now).running is True
    stale = {"heartbeat_at": (now - timedelta(minutes=5)).isoformat(), "connected": True}
    status = bot_status(stale, settings, now=now)
    assert status.running is False and status.connected is False
    stopped = {"heartbeat_at": now.isoformat(), "running": False, "last_error": "gone"}
    status = bot_status(stopped, settings, now=now)
    assert status.running is False and status.last_error == "gone"
    configured = settings.model_copy(
        update={"discord_token": "t", "discord_broadcast_channel_id": 123}
    )
    assert bot_status(None, configured, now=now).configured is True
    assert bot_status(None, settings, now=now).configured is False


async def test_health_surfaces_the_workers_rejected_key(app, client, session_factory, fake_riot):
    """The API only calls Riot when a visitor looks up an unknown player, so after the daily
    development key expires it would keep reporting "Ready" while the worker is already
    backing off on 403s."""
    now = datetime.now(UTC)
    async with session_factory() as s:
        s.add(
            AppState(
                key="poller",
                value={
                    "running": True,
                    "last_run_at": now.isoformat(),
                    "heartbeat_at": now.isoformat(),
                    "last_error": "Alpha#NA1: Riot API key rejected: HTTP 403 Forbidden",
                    "last_report": {
                        "auth_failed": True,
                        "finished_at": now.isoformat(),
                        "errors": ["Alpha#NA1: Riot API key rejected: HTTP 403 Forbidden"],
                    },
                },
            )
        )
        await s.commit()
    # This process last talked to Riot before the worker's failed tick.
    fake_riot.status.key_ok = True
    fake_riot.status.last_ok_at = now - timedelta(minutes=5)

    body = (await client.get("/api/v1/health")).json()

    assert body["riot"]["key_ok"] is False
    assert "403" in body["riot"]["last_error"]
    assert body["status"] == "degraded"


async def test_health_keeps_its_own_riot_status_when_it_is_newer(
    app, client, session_factory, fake_riot
):
    now = datetime.now(UTC)
    async with session_factory() as s:
        s.add(
            AppState(
                key="poller",
                value={
                    "running": True,
                    "last_run_at": (now - timedelta(minutes=30)).isoformat(),
                    "heartbeat_at": now.isoformat(),
                    "last_report": {
                        "auth_failed": True,
                        "finished_at": (now - timedelta(minutes=30)).isoformat(),
                        "errors": ["old failure"],
                    },
                },
            )
        )
        await s.commit()
    fake_riot.status.key_ok = True
    fake_riot.status.last_ok_at = now  # a new key was configured since

    body = (await client.get("/api/v1/health")).json()

    assert body["riot"]["key_ok"] is True
    assert body["status"] == "ok"


def test_crawler_status_staleness_and_counters(settings):
    now = datetime(2026, 9, 26, 12, tzinfo=UTC)
    fresh = {
        "running": True,
        "updated_at": (now - timedelta(seconds=30)).isoformat(),
        "paused_reason": "budget",
        "matches_added_today": 42,
        "day": "2026-09-26",
        "frontier_uncrawled": 80,
        "frontier_total": 100,
    }
    status = crawler_status(fresh, settings, 1234, now=now)
    assert status.enabled is settings.crawl
    assert status.running is True
    assert status.paused_reason == "budget"
    assert status.matches_added_today == 42
    assert status.matches_total_crawled == 1234
    assert (status.frontier_uncrawled, status.frontier_total) == (80, 100)

    # older than 5 minutes: the worker is gone, a paused reason is no longer meaningful
    stale = {**fresh, "updated_at": (now - timedelta(minutes=6)).isoformat()}
    status = crawler_status(stale, settings, None, now=now)
    assert status.running is False and status.paused_reason is None
    assert status.heartbeat_at is not None

    stopped = {**fresh, "running": False, "last_error": "disk full"}
    status = crawler_status(stopped, settings, None, now=now)
    assert status.running is False and status.last_error == "disk full"

    yesterday = {**fresh, "day": "2026-09-25"}
    assert crawler_status(yesterday, settings, None, now=now).matches_added_today == 0

    # every field is optional
    status = crawler_status({"bogus": 1}, settings, None, now=now)
    assert status.running is False and status.matches_added_today is None
    assert crawler_status(None, settings, None, now=now).running is False
    disabled = settings.model_copy(update={"crawl": False})
    assert crawler_status(None, disabled, None, now=now).enabled is False


async def test_health_reads_crawler_heartbeat_and_counts_crawled_games(
    app, client, session_factory
):
    from sqlalchemy import update

    from hextrack.db.models import Match
    from tests.factories import make_match_json
    from tests.test_ai_support import insert_matches

    ids = await insert_matches(
        session_factory, [make_match_json(f"NA1_CRAWLHEALTH{i}") for i in range(3)]
    )
    now = datetime.now(UTC)
    async with session_factory() as s:
        await s.execute(update(Match).where(Match.match_id.in_(ids[:2])).values(source="crawl"))
        s.add(
            AppState(
                key="crawler",
                value={
                    "running": True,
                    "updated_at": now.isoformat(),
                    "started_at": (now - timedelta(hours=1)).isoformat(),
                    "matches_added": 2,
                    "matches_added_today": 2,
                    "day": now.date().isoformat(),
                    "frontier_uncrawled": 7,
                    "frontier_total": 9,
                    "last_error": None,
                    "reserve": {"app": 30},
                },
            )
        )
        await s.commit()

    body = (await client.get("/api/v1/health")).json()
    crawler = body["crawler"]
    assert crawler["running"] is True
    assert crawler["matches_added_today"] == 2
    assert crawler["matches_total_crawled"] == 2
    assert crawler["frontier_uncrawled"] == 7
    assert crawler["frontier_total"] == 9
    assert crawler["last_error"] is None
    assert body["status"] == "ok"


async def test_health_crawler_without_heartbeat(client):
    body = (await client.get("/api/v1/health")).json()
    assert body["crawler"]["running"] is False
    assert body["crawler"]["heartbeat_at"] is None
    assert body["crawler"]["matches_total_crawled"] == 0
