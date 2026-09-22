"""The ``hextrack train`` / ``hextrack model ...`` commands against the test database."""

from __future__ import annotations

import logging
import re

import pytest
from typer.testing import CliRunner

from hextrack.cli import app
from hextrack.config import get_settings
from hextrack.hextrack_ai.inference import ACTIVE_FILE
from tests.test_ai_support import insert_matches, signal_matches

runner = CliRunner()


@pytest.fixture
def cli_env(settings, monkeypatch):
    """Point the CLI's cached settings at the test DB and tmp model dir."""
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("HEXTRACK_MODEL_DIR", str(settings.model_dir))
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    get_settings.cache_clear()
    try:
        yield settings
    finally:
        get_settings.cache_clear()
        root.handlers[:] = handlers
        root.setLevel(level)


async def test_train_list_activate_rescore(clean_db, session_factory, cli_env):
    settings = cli_env
    await insert_matches(session_factory, signal_matches(30, seed=4))

    result = runner.invoke(app, ["train", "--epochs", "2", "--no-activate"])
    assert result.exit_code == 0, result.output
    match = re.search(r"version\s+│?\s*(\d{8}-\d{6}(?:-\d+)?)", result.output)
    assert match, result.output
    version = match.group(1)
    assert (settings.model_dir / version / "model.pth").is_file()
    assert not (settings.model_dir / ACTIVE_FILE).exists()

    result = runner.invoke(app, ["model", "list"])
    assert result.exit_code == 0, result.output
    assert version in result.output

    result = runner.invoke(app, ["model", "activate", version])
    assert result.exit_code == 0, result.output
    assert (settings.model_dir / ACTIVE_FILE).read_text().strip() == version
    # activation scores the stored games with the new model, so averages are not empty
    assert re.search(r"rescored_rows\s+│?\s*300", result.output), result.output

    result = runner.invoke(app, ["model", "rescore"])
    assert result.exit_code == 0, result.output
    assert "rescored 0 participant rows" in result.output  # activation left nothing stale
    result = runner.invoke(app, ["model", "rescore", "--all"])
    assert result.exit_code == 0, result.output
    assert "rescored 300 participant rows" in result.output


async def test_operator_errors_are_one_line_not_tracebacks(clean_db, cli_env):
    """NotEnoughData / NoActiveModel / UnknownModelVersion print a clean message, exit 1."""
    result = runner.invoke(app, ["train", "--epochs", "1"])
    assert result.exit_code == 1, result.output
    assert "error:" in result.output
    assert isinstance(result.exception, SystemExit)

    result = runner.invoke(app, ["model", "rescore"])
    assert result.exit_code == 1, result.output
    assert "error:" in result.output
    assert isinstance(result.exception, SystemExit)

    result = runner.invoke(app, ["model", "activate", "19990101-000000"])
    assert result.exit_code == 1, result.output
    assert "error:" in result.output
    assert isinstance(result.exception, SystemExit)


def test_bot_without_token_exits_cleanly(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "")
    monkeypatch.setenv("DISCORD_BROADCAST_CHANNEL_ID", "")
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["bot"])
    finally:
        get_settings.cache_clear()
        root.handlers[:] = handlers
        root.setLevel(level)
    assert result.exit_code == 2, result.output
    assert isinstance(result.exception, SystemExit)
    assert "DISCORD_TOKEN" in result.output
