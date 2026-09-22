"""``python -m hextrack.bot``: run the Discord bot (same as ``hextrack bot``)."""

from __future__ import annotations

import asyncio
import sys

from hextrack.bot.client import BotNotConfigured, run_bot
from hextrack.cli import setup_logging
from hextrack.config import get_settings


def main() -> int:
    setup_logging()
    try:
        asyncio.run(run_bot(get_settings()))
    except BotNotConfigured as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
