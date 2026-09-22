"""app_state keys the bot owns; import-light so the API can read them without discord.py."""

from __future__ import annotations

from typing import Final

#: Heartbeat written every consumer tick:
#: ``{"running", "heartbeat_at" ISO, "connected", "user", "last_error"}``.
BOT_STATE_KEY: Final = "bot"
