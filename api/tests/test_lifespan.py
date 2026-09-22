"""Lifespan: in-process poller start/stop and state wiring."""

import asyncio

from asgi_lifespan import LifespanManager

from hextrack.ingest.context import IngestContext
from hextrack.main import create_app, reload_active_model
from hextrack.riot.ratelimit import RateLimit


async def test_state_is_wired(settings):
    app = create_app(settings)
    async with LifespanManager(app):
        s = app.state
        assert s.settings is settings
        assert isinstance(s.ingest_ctx, IngestContext)
        assert s.ingest_ctx.riot is s.riot
        assert s.ingest_ctx.session_factory is s.session_factory
        assert s.scorer is None and s.ingest_ctx.scorer is None
        assert s.poller_task is None


async def test_in_process_poller_started_and_stopped(settings, monkeypatch):
    started = asyncio.Event()
    seen: dict = {}

    async def fake_poll_forever(ctx, stop=None):
        seen["ctx"] = ctx
        started.set()
        await stop.wait()
        seen["stopped"] = True

    monkeypatch.setattr("hextrack.ingest.poller.poll_forever", fake_poll_forever)
    app = create_app(settings.model_copy(update={"run_worker_in_process": True}))
    async with LifespanManager(app):
        await asyncio.wait_for(started.wait(), 2)
        ctx = seen["ctx"]
        assert isinstance(ctx, IngestContext)
        assert ctx.session_factory is app.state.session_factory
        # The poller gets its own Riot client: it queues on the rate limiter and spends the
        # worker's share of the key, while requests fail fast within the on-demand budget.
        assert ctx.riot is not app.state.riot
        assert ctx.riot.rate_limiter("regional").app_limits == tuple(
            sorted(
                (RateLimit(count, window) for count, window in settings.worker_app_rate_limits),
                key=lambda limit: (limit.window_seconds, limit.max_requests),
            )
        )
    assert seen["stopped"] is True
    assert app.state.poller_task.done()


class _Scorer:
    def __init__(self, version: str) -> None:
        self.version = version
        self.feature_names: list[str] = []
        self.meta: dict = {}


async def test_reload_active_model_only_when_the_version_changes(monkeypatch, tmp_path):
    loads: list[str] = []
    active = {"version": "v1"}

    def fake_active(model_dir):
        return active["version"]

    def fake_load(model_dir):
        loads.append(active["version"])
        return _Scorer(active["version"])

    monkeypatch.setattr("hextrack.main.read_active_version", fake_active)
    monkeypatch.setattr("hextrack.main.load_scorer", fake_load)

    current = _Scorer("v1")
    assert await reload_active_model(current, tmp_path) is None
    assert loads == []

    active["version"] = "v2"
    reloaded = await reload_active_model(current, tmp_path)
    assert reloaded is not None and reloaded.version == "v2"
    assert loads == ["v2"]


async def test_the_api_picks_up_a_model_activated_while_it_runs(settings, monkeypatch):
    """``hextrack train`` / ``model activate`` rewrite ACTIVE while the API is running; the
    process must not keep explaining scores with the model it started with."""
    active = {"version": None}
    monkeypatch.setattr("hextrack.main.read_active_version", lambda _dir: active["version"])
    monkeypatch.setattr(
        "hextrack.main.load_scorer",
        lambda _dir: _Scorer(active["version"]) if active["version"] else None,
    )
    monkeypatch.setattr("hextrack.main.MODEL_WATCH_INTERVAL_SECONDS", 0.01)

    app = create_app(settings)
    async with LifespanManager(app):
        assert app.state.scorer is None
        active["version"] = "20260922-170745"
        for _ in range(200):
            if app.state.scorer is not None:
                break
            await asyncio.sleep(0.01)
        assert app.state.scorer is not None
        assert app.state.scorer.version == "20260922-170745"
        assert app.state.ingest_ctx.scorer is app.state.scorer
