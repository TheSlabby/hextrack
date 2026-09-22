"""Discord bot (discord.py 2.x) reading the shared database; never calls Riot.

Modules:

* :mod:`hextrack.bot.client`: ``HexTrackBot``, the ``/lp`` command and :func:`run_bot`;
* :mod:`hextrack.bot.consumer`: the ``bot_events`` outbox consumer and the daily
  leaderboard poster;
* :mod:`hextrack.bot.embeds`: pure embed builders ported from LPBot;
* :mod:`hextrack.bot.queries`: the database reads behind all of the above.

Run it with ``hextrack bot`` or ``python -m hextrack.bot``.
"""
