"""FastAPI application factory.

``create_app()`` wires settings, the async engine, the Riot client, Data Dragon, the AI
Scorer and (optionally) the in-process poller into ``app.state``:

* ``app.state.settings``        Settings
* ``app.state.engine``          AsyncEngine
* ``app.state.session_factory`` async_sessionmaker[AsyncSession]
* ``app.state.riot``            RiotClient
* ``app.state.ddragon``         DDragon
* ``app.state.scorer``          Scorer | None
* ``app.state.ingest_ctx``      IngestContext
* ``app.state.poller_task``     asyncio.Task | None (only with run_worker_in_process; that
  poller runs on its own RiotClient, with the worker's share of the rate limit)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from hextrack import __version__
from hextrack.api.deps import ApiError
from hextrack.api.schemas import ErrorResponse
from hextrack.api.v1.router import build_router
from hextrack.config import Settings, get_settings
from hextrack.db.engine import make_async_engine, make_session_factory
from hextrack.hextrack_ai.inference import Scorer, read_active_version
from hextrack.ingest.context import IngestContext
from hextrack.riot.client import RiotClient
from hextrack.riot.ddragon import DDragon
from hextrack.riot.errors import (
    RiotBadResponse,
    RiotError,
    RiotForbidden,
    RiotKeyMissing,
    RiotNotFound,
    RiotRateLimited,
    RiotUnavailable,
)

logger = logging.getLogger(__name__)

POLLER_SHUTDOWN_TIMEOUT_SECONDS = 10.0
#: How often the process checks whether another one activated a different AI model.
MODEL_WATCH_INTERVAL_SECONDS = 30.0


def load_scorer(model_dir: Path) -> Scorer | None:
    """``Scorer.load`` that never raises: any failure is logged and yields None."""
    try:
        scorer = Scorer.load(model_dir)
    except Exception:
        logger.exception("failed to load AI model from %s; AI scores disabled", model_dir)
        return None
    if scorer is None:
        logger.info("no AI model found in %s; AI scores disabled", model_dir)
    else:
        logger.info("loaded AI model %s", scorer.version)
    return scorer


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    """Wait ``seconds``; True when ``stop`` was set in the meantime."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(seconds, 0.0))
    except TimeoutError:
        return False
    return True


async def reload_active_model(current: Scorer | None, model_dir: Path) -> Scorer | None:
    """The newly activated model, or None when the active version has not changed.

    ``hextrack train`` / ``hextrack model activate`` rewrite ``model_dir/ACTIVE`` while the
    API is running; without this the process would keep scoring and explaining with the model
    it started with while the stored scores come from the new one.
    """
    active = await asyncio.to_thread(read_active_version, model_dir)
    if active is None or (current is not None and active == current.version):
        return None
    scorer = await asyncio.to_thread(load_scorer, model_dir)
    if scorer is None or (current is not None and scorer.version == current.version):
        return None
    return scorer


async def watch_active_model(
    app: FastAPI,
    contexts: Sequence[IngestContext],
    settings: Settings,
    stop: asyncio.Event,
    *,
    interval: float | None = None,
) -> None:
    """Swap ``app.state.scorer`` (and every ingest context) when the active model changes."""
    every = interval if interval is not None else MODEL_WATCH_INTERVAL_SECONDS
    while not stop.is_set():
        if await _sleep_or_stop(stop, every):
            return
        try:
            current: Scorer | None = getattr(app.state, "scorer", None)
            scorer = await reload_active_model(current, settings.model_dir)
        except Exception:  # never let the watcher kill itself
            logger.exception("could not check for a new AI model")
            continue
        if scorer is None:
            continue
        logger.info(
            "AI model changed: now scoring with %s (was %s)",
            scorer.version,
            current.version if current is not None else "none",
        )
        app.state.scorer = scorer
        for context in contexts:
            context.scorer = scorer


def _first_validation_error(exc: RequestValidationError) -> str:
    """The first pydantic error as one line, e.g. ``query.limit: Input should be <= 50``."""
    errors = exc.errors()
    if not errors:
        return "Invalid request"
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "request"
    return f"{location}: {first.get('msg', 'invalid value')}"


def _error(status_code: int, detail: str, code: str | None, **headers: str) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(detail=detail, code=code).model_dump(),
        status_code=status_code,
        headers=headers or None,
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RiotKeyMissing)
    async def _riot_key_missing(_: Request, exc: RiotKeyMissing) -> JSONResponse:
        return _error(503, "Riot API key is not configured", "riot_key")

    @app.exception_handler(RiotForbidden)
    async def _riot_forbidden(_: Request, exc: RiotForbidden) -> JSONResponse:
        return _error(503, "Riot API key was rejected (expired or invalid)", "riot_key")

    @app.exception_handler(RiotRateLimited)
    async def _riot_rate_limited(_: Request, exc: RiotRateLimited) -> JSONResponse:
        retry_after = max(1, int(round(exc.retry_after)))
        return _error(
            429,
            f"Riot API rate limit reached; retry in {retry_after}s",
            "riot_rate_limited",
            **{"Retry-After": str(retry_after)},
        )

    @app.exception_handler(RiotUnavailable)
    async def _riot_unavailable(_: Request, exc: RiotUnavailable) -> JSONResponse:
        return _error(502, "Riot API is unavailable", "riot_unavailable")

    @app.exception_handler(RiotBadResponse)
    async def _riot_bad_response(_: Request, exc: RiotBadResponse) -> JSONResponse:
        return _error(502, "Riot API returned an unexpected response", "riot_unavailable")

    @app.exception_handler(RiotNotFound)
    async def _riot_not_found(_: Request, exc: RiotNotFound) -> JSONResponse:
        return _error(404, str(exc) or "Not found", "not_found")

    @app.exception_handler(RiotError)
    async def _riot_error(_: Request, exc: RiotError) -> JSONResponse:
        logger.error("unhandled Riot error: %s", exc)
        return _error(502, "Riot API error", "riot_unavailable")


def mount_spa(app: FastAPI, web_dist: Path) -> None:
    """Serve the built frontend: ``/assets`` statically, other files as-is, and
    ``index.html`` for every other non-/api path (client-side routing)."""
    index = web_dist / "index.html"
    if not index.is_file():
        logger.info("web dist %s has no index.html; not serving the frontend", web_dist)
        return
    assets = web_dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    root = web_dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise ApiError(404, "Not found", "not_found")
        if full_path:
            candidate = (root / full_path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def _log_poller_exit(task: asyncio.Task[None]) -> None:
    """Surface an in-process poller crash immediately instead of at shutdown."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("in-process poller stopped", exc_info=exc)


def _operation_id(route: APIRoute) -> str:
    """Operation ids are the endpoint function names (stable, readable client methods)."""
    return route.name


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_async_engine(settings)
        session_factory = make_session_factory(engine)
        # Requests never queue behind the worker's backfill: they fail fast with 429, and
        # the on-demand budget caps what unauthenticated traffic can take from the key.
        riot = RiotClient(
            settings,
            max_wait=settings.riot_ondemand_max_wait_seconds,
            budget=settings.ondemand_rate_limits or None,
        )
        ddragon = DDragon()
        scorer = load_scorer(settings.model_dir)
        ctx = IngestContext(
            settings=settings, session_factory=session_factory, riot=riot, scorer=scorer
        )
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.riot = riot
        app.state.ddragon = ddragon
        app.state.scorer = scorer
        app.state.ingest_ctx = ctx
        app.state.poller_task = None

        stop = asyncio.Event()
        contexts = [ctx]
        poller_riot: RiotClient | None = None
        if settings.run_worker_in_process:
            from hextrack.ingest.poller import poll_forever

            # The in-process poller gets its own client: it may queue on the limiter and it
            # spends the worker's share of the key, leaving the on-demand budget alone.
            poller_riot = RiotClient(settings, app_limits=settings.worker_app_rate_limits)
            poller_ctx = replace(ctx, riot=poller_riot)
            contexts.append(poller_ctx)
            poller_task = asyncio.create_task(
                poll_forever(poller_ctx, stop), name="hextrack-poller"
            )
            poller_task.add_done_callback(_log_poller_exit)
            app.state.poller_task = poller_task
            logger.info("started in-process poller")
        watcher = asyncio.create_task(
            watch_active_model(app, contexts, settings, stop), name="hextrack-model-watch"
        )
        try:
            yield
        finally:
            stop.set()
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await watcher
            task: asyncio.Task[None] | None = app.state.poller_task
            if task is not None:
                try:
                    await asyncio.wait_for(task, timeout=POLLER_SHUTDOWN_TIMEOUT_SECONDS)
                except TimeoutError:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                except asyncio.CancelledError:
                    pass
                except Exception:  # already logged by _log_poller_exit
                    pass
            # Tests may swap app.state.riot; close whatever is installed now as well.
            current_riot = getattr(app.state, "riot", riot)
            clients = [riot, current_riot]
            if poller_riot is not None:
                clients.append(poller_riot)
            for client in {id(c): c for c in clients}.values():
                with contextlib.suppress(Exception):
                    await client.aclose()
            with contextlib.suppress(Exception):
                await ddragon.aclose()
            await engine.dispose()

    app = FastAPI(
        title="HexTrack API",
        version=__version__,
        description="League of Legends stats with an AI Score.",
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        generate_unique_id_function=_operation_id,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Retry-After"],
    )
    install_exception_handlers(app)
    app.include_router(build_router())

    # Every HTTP error body follows ErrorResponse ({"detail", "code"}).
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            ErrorResponse(detail=detail, code=None).model_dump(),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, _first_validation_error(exc), "invalid_request")

    # Last resort: an unexpected error still answers ErrorResponse JSON rather than a
    # plain-text 500 the frontend cannot parse. Starlette re-raises it for the logs.
    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        return _error(500, "Internal server error", "internal_error")

    mount_spa(app, settings.web_dist)
    return app
