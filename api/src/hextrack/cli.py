"""``hextrack`` command line (typer).

Heavy modules (torch, discord, the web app) are imported lazily inside each command so
``hextrack --help`` and simple commands stay fast.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from hextrack.config import API_DIR, Settings, get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from hextrack.ingest.context import IngestContext

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="hextrack",
    help="HexTrack v2: League of Legends stats with an AI Score.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
model_app = typer.Typer(help="Manage trained AI Score models.", no_args_is_help=True)
roster_app = typer.Typer(help="Manage the tracked friends roster.", no_args_is_help=True)
db_app = typer.Typer(help="Database migrations.", no_args_is_help=True)
app.add_typer(model_app, name="model")
app.add_typer(roster_app, name="roster")
app.add_typer(db_app, name="db")


# --- helpers ---------------------------------------------------------------------------------


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=err_console, rich_tracebacks=True, show_path=False)],
        force=True,
    )


def _fail(message: str, code: int = 1) -> typer.Exit:
    err_console.print(f"[bold red]error:[/] {message}")
    return typer.Exit(code)


type ExpectedErrors = tuple[type[BaseException], ...]


def _riot_errors() -> ExpectedErrors:
    from hextrack.riot.errors import RiotError

    return (RiotError,)


def _run[T](
    coro: Coroutine[Any, Any, T], *, expected: ExpectedErrors = (), expected_code: int = 1
) -> T:
    """Run a coroutine; turn Ctrl-C and the ``expected`` user-facing errors into clean exits.

    ``expected`` lists exceptions whose message is meant for the operator (missing model,
    bad Riot ID, missing token, ...): they are printed as one line instead of a traceback.
    """
    try:
        return asyncio.run(coro)
    except NotImplementedError as exc:
        raise _fail(f"not implemented yet: {exc}", 2) from exc
    except KeyboardInterrupt as exc:
        raise typer.Exit(130) from exc
    except expected as exc:
        raise _fail(str(exc) or type(exc).__name__, expected_code) from exc


def _call[T](fn: Callable[..., T], *args: Any, _expected: ExpectedErrors = (), **kwargs: Any) -> T:
    """Call ``fn``; print ``_expected`` errors as one clean line (see :func:`_run`)."""
    try:
        return fn(*args, **kwargs)
    except NotImplementedError as exc:
        raise _fail(f"not implemented yet: {exc}", 2) from exc
    except _expected as exc:
        raise _fail(str(exc) or type(exc).__name__) from exc


def _parse_since(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        if len(value) == 10:
            d = date.fromisoformat(value)
            return datetime(d.year, d.month, d.day, tzinfo=UTC)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter("use YYYY-MM-DD or an ISO-8601 datetime") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _parse_queues(value: str) -> list[int]:
    try:
        queues = [int(q) for q in value.split(",") if q.strip()]
    except ValueError as exc:
        raise typer.BadParameter("comma-separated queue ids, e.g. 420,440") from exc
    if not queues:
        raise typer.BadParameter("at least one queue id is required")
    return queues


def _print_dataclass(title: str, obj: Any) -> None:
    from dataclasses import fields, is_dataclass

    table = Table(title=title, show_header=False, title_justify="left")
    table.add_column("field", style="bold cyan")
    table.add_column("value")
    if is_dataclass(obj) and not isinstance(obj, type):
        for f in fields(obj):
            value = getattr(obj, f.name)
            if isinstance(value, list) and len(value) > 10:
                value = f"{len(value)} items (first: {value[:3]})"
            table.add_row(f.name, str(value))
    else:
        table.add_row("result", str(obj))
    console.print(table)


async def _with_ingest_ctx[T](
    settings: Settings, fn: Callable[[IngestContext, AsyncSession], Awaitable[T]]
) -> T:
    """Build a DB session + RiotClient context, run ``fn``, commit, dispose everything."""
    from hextrack.db.engine import make_async_engine, make_session_factory
    from hextrack.ingest.context import IngestContext
    from hextrack.riot.client import RiotClient

    engine = make_async_engine(settings, pool_size=2, max_overflow=0)
    try:
        factory = make_session_factory(engine)
        async with RiotClient(settings) as riot:
            ctx = IngestContext(settings=settings, session_factory=factory, riot=riot, scorer=None)
            async with factory() as session:
                result = await fn(ctx, session)
                await session.commit()
                return result
    finally:
        await engine.dispose()


# --- servers ---------------------------------------------------------------------------------


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", help="Auto-reload on code changes.")] = False,
    with_worker: Annotated[
        bool, typer.Option("--with-worker", help="Run the roster poller in-process.")
    ] = False,
) -> None:
    """Run the API (and the built frontend from HEXTRACK_WEB_DIST, if present)."""
    import uvicorn

    if with_worker:
        # Exported so uvicorn's reload subprocess builds the same settings.
        os.environ["HEXTRACK_RUN_WORKER_IN_PROCESS"] = "1"
        get_settings.cache_clear()
    setup_logging()
    uvicorn.run(
        "hextrack.main:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(API_DIR / "src")] if reload else None,
        log_config=None,
    )


@app.command()
def worker() -> None:
    """Run the roster poller (one per deployment: it owns the Riot rate-limit budget)."""
    from hextrack.ingest.poller import run_worker

    setup_logging()
    _run(run_worker(get_settings()))


@app.command()
def bot() -> None:
    """Run the Discord bot."""
    from hextrack.bot.client import BotNotConfigured, run_bot

    setup_logging()
    _run(run_bot(get_settings()), expected=(BotNotConfigured,), expected_code=2)


# --- AI --------------------------------------------------------------------------------------


@app.command()
def train(
    since: Annotated[
        str | None, typer.Option(help="Only matches on/after this date (YYYY-MM-DD or ISO).")
    ] = None,
    queues: Annotated[str, typer.Option(help="Comma-separated queue ids.")] = "420,440",
    epochs: Annotated[int, typer.Option(min=1, help="Training epochs.")] = 100,
    activate: Annotated[
        bool, typer.Option("--activate/--no-activate", help="Make the new model active.")
    ] = True,
    rescore: Annotated[
        bool,
        typer.Option(
            "--rescore/--no-rescore",
            help="Re-score stored games with the new model when activating it.",
        ),
    ] = True,
) -> None:
    """Train a new AI Score model from stored matches.

    Activating re-scores the stored games, because averages, trends and leaderboards only
    count rows scored by the active model. Restart the API and the worker afterwards so they
    serve it too.
    """
    from hextrack.hextrack_ai.inference import ModelLoadError
    from hextrack.hextrack_ai.registry import NoActiveModel, UnknownModelVersion
    from hextrack.hextrack_ai.train import NotEnoughData
    from hextrack.hextrack_ai.train import train as run_train

    setup_logging()
    report = _call(
        run_train,
        get_settings(),
        _expected=(NotEnoughData, UnknownModelVersion, NoActiveModel, ModelLoadError),
        since=_parse_since(since),
        queues=_parse_queues(queues),
        epochs=epochs,
        activate=activate,
        rescore=rescore,
    )
    _print_dataclass("Training report", report)


@model_app.command("activate")
def model_activate(
    version: Annotated[str, typer.Argument(help="Model version.")],
    rescore: Annotated[
        bool,
        typer.Option("--rescore/--no-rescore", help="Re-score stored games with the new model."),
    ] = True,
) -> None:
    """Make VERSION the active model and re-score the stored games with it.

    Averages, trends and leaderboards only count rows scored by the active model, so
    --no-rescore leaves the AI Score surfaces empty until `hextrack model rescore` runs. The
    API and the worker pick the new model up within a minute; restarting them is not needed.
    """
    from hextrack.hextrack_ai.inference import ModelLoadError
    from hextrack.hextrack_ai.registry import NoActiveModel, UnknownModelVersion, activate

    info = _call(
        activate,
        get_settings(),
        version,
        _expected=(UnknownModelVersion, ModelLoadError, NoActiveModel),
        rescore_stored=rescore,
    )
    console.print(f"[green]activated[/] {info.version}")
    _print_dataclass("Model", info)


@model_app.command("rescore")
def model_rescore(
    all_rows: Annotated[
        bool, typer.Option("--all", help="Rescore every row, not just unscored/stale ones.")
    ] = False,
) -> None:
    """Score stored participants with the active model."""
    from hextrack.hextrack_ai.inference import ModelLoadError
    from hextrack.hextrack_ai.registry import NoActiveModel, rescore

    setup_logging()
    n = _call(rescore, get_settings(), all_rows=all_rows, _expected=(NoActiveModel, ModelLoadError))
    console.print(f"[green]rescored[/] {n} participant rows")


@model_app.command("list")
def model_list() -> None:
    """List trained models."""
    from hextrack.hextrack_ai.registry import list_models

    models = _call(list_models, get_settings())
    table = Table(title="AI models")
    for col in ("version", "trained_at", "active", "features", "val_auc"):
        table.add_column(col)
    for m in models:
        auc = m.metrics.get("val_auc")
        table.add_row(
            m.version,
            m.trained_at.isoformat(timespec="minutes"),
            "[green]yes[/]" if m.is_active else "",
            str(m.n_features),
            f"{auc:.4f}" if isinstance(auc, int | float) else "-",
        )
    console.print(table)


# --- data ------------------------------------------------------------------------------------


@app.command()
def backfill(
    since: Annotated[
        str | None,
        typer.Option(help="Anchor date (YYYY-MM-DD or ISO); default: HEXTRACK_SEASON_START."),
    ] = None,
    player: Annotated[
        list[str] | None,
        typer.Option(help='Limit to these tracked players ("Name#TAG"); repeatable.'),
    ] = None,
    max_ticks: Annotated[int, typer.Option(min=1, help="Safety cap on poll rounds.")] = 40,
) -> None:
    """Catch the tracked roster's stored ranked history up to Riot (one-off deep scrape).

    Lists every ranked game each tracked player has played since the anchor date and
    ingests the ones that are missing, at the Riot rate limiter's pace. Safe to interrupt
    and rerun. Stop 'hextrack worker' first: only one poller may run at a time.
    """
    from hextrack.ingest.backfill import run_backfill

    setup_logging()
    report = _run(
        run_backfill(
            get_settings(),
            since=_parse_since(since),
            riot_ids=player or None,
            max_ticks=max_ticks,
        ),
        expected=(*_riot_errors(), ValueError, RuntimeError),
    )
    table = Table(title=f"Backfill since {report.since.date().isoformat()}", title_justify="left")
    for col in ("player", "stored before", "stored now", "gained", "complete"):
        table.add_column(col)
    for p in report.players:
        table.add_row(
            p.riot_id,
            str(p.before),
            str(p.after),
            f"[green]+{p.gained}[/]" if p.gained else "0",
            "[green]yes[/]" if p.complete else "[yellow]no[/]",
        )
    console.print(table)
    console.print(
        f"{report.matches_ingested} matches ingested over {report.ticks} rounds; "
        f"{report.matches_gained} new games across the roster"
    )
    if report.incomplete:
        console.print(f"[yellow]still catching up:[/] {', '.join(report.incomplete)} (rerun)")
    for message in report.errors[:10]:
        err_console.print(f"[yellow]warning:[/] {message}")


@app.command("import-legacy")
def import_legacy(
    sqlite: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False, help="LPBot database.sqlite")
    ] = None,
    neon_url: Annotated[
        str | None, typer.Option(help="Legacy Neon/Postgres URL (Matches table).")
    ] = None,
    players: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False, help="LPBot players.txt")
    ] = None,
) -> None:
    """Import matches, rank history and roster from the legacy apps (idempotent)."""
    from hextrack.legacy_import import run_import

    if sqlite is None and neon_url is None and players is None:
        raise _fail("pass at least one of --sqlite, --neon-url, --players")
    setup_logging()
    report = _run(run_import(get_settings(), sqlite, neon_url, players))
    _print_dataclass("Import report", report)


@app.command("seed-demo")
def seed_demo_cmd(
    reset: Annotated[
        bool, typer.Option("--reset", help="Delete existing demo data first (real data is kept).")
    ] = False,
    players: Annotated[int, typer.Option(min=1, help="Tracked players to create.")] = 8,
    matches: Annotated[int, typer.Option(min=1, help="Matches to generate.")] = 220,
    seed: Annotated[int, typer.Option(help="Random seed.")] = 7,
    force: Annotated[
        bool, typer.Option("--force", help="Seed even when a Riot key is configured.")
    ] = False,
) -> None:
    """Add deterministic demo players and games (no Riot key needed).

    Real data is kept: demo players and matches are added alongside it, and --reset only
    removes previously seeded demo data. Demo players are tracked, so they show up in the
    roster and the leaderboards; the poller skips them (their puuids are synthetic).
    """
    from hextrack.demo.seed import seed_demo

    settings = get_settings()
    if settings.riot_api_key and not force:
        raise _fail(
            "a Riot API key is configured, so this database probably holds real data; "
            "demo players would show up in the roster and the leaderboards. "
            "Pass --force if you really want to seed it."
        )
    setup_logging()
    report = _run(seed_demo(settings, reset=reset, players=players, matches=matches, seed=seed))
    _print_dataclass("Demo seed", report)


@app.command("clear-demo")
def clear_demo_cmd() -> None:
    """Delete all demo data (DEMO_ matches, demo- summoners); real data is kept."""
    from hextrack.demo.seed import clear_demo

    setup_logging()
    deleted = _run(clear_demo(get_settings()))
    console.print(f"Deleted {deleted} demo matches and all demo summoners.")


# --- roster ----------------------------------------------------------------------------------


@roster_app.command("add")
def roster_add(riot_id: Annotated[str, typer.Argument(help='Riot ID, e.g. "Name#TAG".')]) -> None:
    """Track a player."""
    from hextrack.ingest.roster import RosterError, add_to_roster
    from hextrack.riotid import InvalidRiotId

    summoner = _run(
        _with_ingest_ctx(get_settings(), lambda ctx, s: add_to_roster(ctx, s, riot_id)),
        expected=(RosterError, InvalidRiotId, *_riot_errors()),
    )
    console.print(f"[green]tracking[/] {summoner.game_name}#{summoner.tag_line}")


@roster_app.command("rm")
def roster_rm(riot_id: Annotated[str, typer.Argument(help='Riot ID, e.g. "Name#TAG".')]) -> None:
    """Stop tracking a player (data is kept)."""
    from hextrack.ingest.roster import RosterError, remove_from_roster
    from hextrack.riotid import InvalidRiotId

    removed = _run(
        _with_ingest_ctx(get_settings(), lambda _ctx, s: remove_from_roster(s, riot_id)),
        expected=(RosterError, InvalidRiotId),
    )
    if not removed:
        raise _fail(f"{riot_id} is not on the roster")
    console.print(f"[yellow]untracked[/] {riot_id}")


@roster_app.command("list")
def roster_list() -> None:
    """Show tracked players."""
    from hextrack.ingest.roster import list_roster

    summoners = _run(_with_ingest_ctx(get_settings(), lambda _ctx, s: list_roster(s)))
    table = Table(title=f"Roster ({len(summoners)})")
    for col in ("riot id", "level", "tracked since", "last refreshed"):
        table.add_column(col)
    for s in summoners:
        table.add_row(
            f"{s.game_name}#{s.tag_line}",
            str(s.summoner_level or "-"),
            s.tracked_since.isoformat(timespec="minutes") if s.tracked_since else "-",
            s.last_refreshed_at.isoformat(timespec="minutes") if s.last_refreshed_at else "-",
        )
    console.print(table)


# --- tooling ---------------------------------------------------------------------------------


@app.command()
def openapi(
    out: Annotated[Path, typer.Option("--out", help="Output file ('-' for stdout).")],
) -> None:
    """Write the OpenAPI spec without starting the server or touching the database."""
    from hextrack.main import create_app

    spec = create_app(get_settings()).openapi()
    text = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    if str(out) == "-":
        sys.stdout.write(text)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    console.print(f"[green]wrote[/] {out} ({len(spec.get('paths', {}))} paths)")


@db_app.command("upgrade")
def db_upgrade(
    revision: Annotated[str, typer.Argument(help="Target revision.")] = "head",
) -> None:
    """Apply Alembic migrations to DATABASE_URL."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.attributes["database_url"] = get_settings().database_url
    command.upgrade(cfg, revision)
    console.print(f"[green]database at[/] {revision}")


if __name__ == "__main__":  # pragma: no cover
    app()
