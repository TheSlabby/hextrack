"""Read side of the API: every SQL query the HTTP routes run lives in this package.

* :mod:`hextrack.stats.queries`: lookups and row fetches (summoners, ranks, match pages,
  match detail, AI score history, search, roster), the opaque match-history cursor and the
  "which model version counts" rule.
* :mod:`hextrack.stats.aggregate`: set-based aggregates (season profile stats, champion and
  role splits, the roster leaderboard with best ally and LP delta).
* :mod:`hextrack.stats.present`: pure conversion of rows into the response models of
  :mod:`hextrack.api.schemas` (no database access).
* :mod:`hextrack.stats.metrics`: the numeric rules (KDA, winrate, kill participation,
  per-minute rates, remake threshold) shared by all of the above.

Conventions shared by every aggregate:

* "Ranked" means queues 420 (Solo/Duo) and 440 (Flex).
* "Season" means ``game_start >= settings.season_start``.
* Remakes (``matches.remake`` or a game shorter than 300 s) never count towards stats.
* AI Score averages only use scores from a single model version (see
  :func:`hextrack.stats.queries.resolve_model_version`); scores from different model
  versions are not comparable.
"""
