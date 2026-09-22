"""Queue id -> label map (https://static.developer.riotgames.com/docs/lol/queues.json)."""

from __future__ import annotations

from typing import Final

RANKED_SOLO: Final = 420
RANKED_FLEX: Final = 440
RANKED_QUEUES: Final[frozenset[int]] = frozenset({RANKED_SOLO, RANKED_FLEX})

QUEUE_LABELS: Final[dict[int, str]] = {
    0: "Custom",
    400: "Normal Draft",
    420: "Ranked Solo/Duo",
    430: "Normal Blind",
    440: "Ranked Flex",
    450: "ARAM",
    480: "Swiftplay",
    490: "Quickplay",
    700: "Clash",
    720: "ARAM Clash",
    830: "Co-op vs AI Intro",
    840: "Co-op vs AI Beginner",
    850: "Co-op vs AI Intermediate",
    870: "Co-op vs AI Intro",
    880: "Co-op vs AI Beginner",
    890: "Co-op vs AI Intermediate",
    900: "ARURF",
    1020: "One for All",
    1300: "Nexus Blitz",
    1400: "Ultimate Spellbook",
    1700: "Arena",
    1710: "Arena",
    1810: "Swarm",
    1820: "Swarm",
    1830: "Swarm",
    1840: "Swarm",
    1900: "URF",
    2300: "Brawl",
    2400: "ARAM: Mayhem",
    3100: "Custom",
}


def queue_label(queue_id: int) -> str:
    """Label for a queue id; unknown ids render as "Queue <id>"."""
    return QUEUE_LABELS.get(queue_id, f"Queue {queue_id}")


def is_ranked(queue_id: int) -> bool:
    return queue_id in RANKED_QUEUES


def queue_labels_json() -> dict[str, str]:
    """``{"420": "Ranked Solo/Duo", ...}`` for the /meta endpoint (JSON keys are strings)."""
    return {str(k): v for k, v in sorted(QUEUE_LABELS.items())}
