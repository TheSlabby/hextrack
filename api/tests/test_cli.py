import json

from typer.testing import CliRunner

from hextrack.cli import app

runner = CliRunner()

EXPECTED_PATHS = {
    ("/api/v1/health", "get"),
    ("/api/v1/meta", "get"),
    ("/api/v1/search", "get"),
    ("/api/v1/summoners/by-riot-id/{game_name}/{tag_line}", "get"),
    ("/api/v1/summoners/by-riot-id/{game_name}/{tag_line}/refresh", "post"),
    ("/api/v1/summoners/{puuid}/matches", "get"),
    ("/api/v1/summoners/{puuid}/ranks", "get"),
    ("/api/v1/summoners/{puuid}/ai-trend", "get"),
    ("/api/v1/summoners/{puuid}/ai-explain", "get"),
    ("/api/v1/matches/{match_id}", "get"),
    ("/api/v1/leaderboard", "get"),
    ("/api/v1/roster", "get"),
    ("/api/v1/roster/{game_name}/{tag_line}", "put"),
    ("/api/v1/roster/{game_name}/{tag_line}", "delete"),
}
EXPECTED_SCHEMAS = {
    "RankEntry",
    "ProfileStats",
    "ChampionStat",
    "RoleStat",
    "SummonerProfile",
    "SummonerSearchResult",
    "RefreshResult",
    "ParticipantSummary",
    "ObjectiveStat",
    "TeamObjectives",
    "TeamSummary",
    "TeamDetail",
    "MatchSummary",
    "MatchPage",
    "MatchDetail",
    "RankPoint",
    "RankHistory",
    "AiTrendPoint",
    "AiTrend",
    "FeatureAttribution",
    "AiExplain",
    "BestAlly",
    "LeaderboardEntry",
    "Leaderboard",
    "RosterEntry",
    "Meta",
    "Health",
    "ErrorResponse",
}


def test_openapi_command_writes_spec(tmp_path, monkeypatch):
    # Must not need a database: point DATABASE_URL at a closed port.
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:1/none")
    from hextrack.config import get_settings

    get_settings.cache_clear()
    try:
        out = tmp_path / "nested" / "openapi.json"
        result = runner.invoke(app, ["openapi", "--out", str(out)])
        assert result.exit_code == 0, result.output
    finally:
        get_settings.cache_clear()
    spec = json.loads(out.read_text())
    paths = {(p, m) for p, ops in spec["paths"].items() for m in ops}
    assert EXPECTED_PATHS <= paths
    assert EXPECTED_SCHEMAS <= set(spec["components"]["schemas"])
    op_ids = [op["operationId"] for ops in spec["paths"].values() for op in ops.values()]
    assert len(op_ids) == len(set(op_ids))
    by_riot = spec["paths"]["/api/v1/summoners/by-riot-id/{game_name}/{tag_line}"]["get"]
    assert {"200", "404", "429", "502", "503"} <= set(by_riot["responses"])
    participant = spec["components"]["schemas"]["ParticipantSummary"]
    assert set(participant["required"]) == set(participant["properties"])


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in (
        "serve",
        "worker",
        "bot",
        "train",
        "model",
        "import-legacy",
        "seed-demo",
        "roster",
        "openapi",
        "db",
    ):
        assert cmd in result.output
