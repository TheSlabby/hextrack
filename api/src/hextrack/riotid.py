"""Riot ID parsing and URL slugs.

A Riot ID is ``GameName#TAG``. Game names may contain spaces, unicode and "-", while tag
lines are 3-5 alphanumeric characters, so the URL slug ``Game-Name-TAG`` is split on the
**last** "-" losslessly.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

MAX_GAME_NAME_LENGTH = 16
MIN_GAME_NAME_LENGTH = 3
MAX_TAG_LENGTH = 5
MIN_TAG_LENGTH = 2


class InvalidRiotId(ValueError):
    """The string is not a valid ``Name#TAG`` Riot ID or ``Name-TAG`` slug."""


@dataclass(frozen=True, slots=True)
class RiotId:
    game_name: str
    tag_line: str

    def __str__(self) -> str:
        return f"{self.game_name}#{self.tag_line}"

    @property
    def slug(self) -> str:
        return to_slug(self.game_name, self.tag_line)

    @property
    def key(self) -> tuple[str, str]:
        """Case-insensitive identity, see :func:`riot_id_key`."""
        return riot_id_key(self.game_name, self.tag_line)


def normalize_game_name(game_name: str) -> str:
    """Strip outer whitespace, collapse inner runs and NFC-normalise (display form)."""
    return " ".join(unicodedata.normalize("NFC", game_name).split())


def normalize_tag_line(tag_line: str) -> str:
    return unicodedata.normalize("NFC", tag_line).strip().lstrip("#").strip()


def casefold_name(value: str) -> str:
    """Comparison form of a game name or tag (matches Postgres ``lower()`` for ASCII)."""
    return normalize_game_name(value).casefold()


def riot_id_key(game_name: str, tag_line: str) -> tuple[str, str]:
    """Key for case-insensitive equality of Riot IDs."""
    return casefold_name(game_name), casefold_name(normalize_tag_line(tag_line))


def has_control_characters(value: str) -> bool:
    """True when ``value`` holds a character no Riot ID can contain. A NUL in particular
    reaches Postgres as an invalid UTF-8 byte and fails the query, so these never become
    lookups."""
    return any(ch < " " or ch == "\x7f" for ch in value)


def is_plausible_riot_id(game_name: str, tag_line: str) -> bool:
    """Whether ``game_name#tag_line`` could exist at Riot (3-16 character name, 3-5
    alphanumeric characters of tag).

    Stored players are always served from the database first; this only decides whether an
    unknown Riot ID is worth an account-v1 request, so it follows Riot's own creation rules
    rather than the lenient rules :func:`parse_riot_id` accepts.
    """
    name, tag = normalize_game_name(game_name), normalize_tag_line(tag_line)
    if not (MIN_GAME_NAME_LENGTH <= len(name) <= MAX_GAME_NAME_LENGTH):
        return False
    if not (3 <= len(tag) <= MAX_TAG_LENGTH) or not tag.isalnum():
        return False
    return not has_control_characters(name)


def _validate(game_name: str, tag_line: str, original: str) -> RiotId:
    name, tag = normalize_game_name(game_name), normalize_tag_line(tag_line)
    if not name or not tag:
        raise InvalidRiotId(f"invalid Riot ID {original!r}: name and tag are required")
    if len(name) > MAX_GAME_NAME_LENGTH + 8:  # generous: Riot enforces 3-16 on creation
        raise InvalidRiotId(f"invalid Riot ID {original!r}: game name too long")
    if not (MIN_TAG_LENGTH <= len(tag) <= MAX_TAG_LENGTH) or "#" in tag:
        raise InvalidRiotId(f"invalid Riot ID {original!r}: tag must be 2-5 characters")
    if "#" in name:
        raise InvalidRiotId(f"invalid Riot ID {original!r}: game name cannot contain '#'")
    if has_control_characters(name) or has_control_characters(tag):
        raise InvalidRiotId(f"invalid Riot ID {original!r}: control characters are not allowed")
    return RiotId(name, tag)


def parse_riot_id(value: str) -> RiotId:
    """Parse ``"Name#TAG"``. Splits on the last "#"; raises :class:`InvalidRiotId`."""
    name, sep, tag = value.strip().rpartition("#")
    if not sep:
        raise InvalidRiotId(f"invalid Riot ID {value!r}: expected 'Name#TAG'")
    return _validate(name, tag, value)


def parse_slug(slug: str) -> RiotId:
    """Parse a URL slug ``"Game-Name-TAG"`` by splitting on the last "-"."""
    name, sep, tag = slug.strip().rpartition("-")
    if not sep:
        raise InvalidRiotId(f"invalid Riot ID slug {slug!r}: expected 'Name-TAG'")
    return _validate(name, tag, slug)


def parse_any(value: str) -> RiotId:
    """Accept either ``Name#TAG`` or a ``Name-TAG`` slug (``#`` wins when present)."""
    return parse_riot_id(value) if "#" in value else parse_slug(value)


def to_slug(game_name: str, tag_line: str) -> str:
    """``("Faker Fan", "NA1")`` -> ``"Faker Fan-NA1"`` (URL-encode separately)."""
    return f"{normalize_game_name(game_name)}-{normalize_tag_line(tag_line)}"


def format_riot_id(game_name: str, tag_line: str) -> str:
    return f"{normalize_game_name(game_name)}#{normalize_tag_line(tag_line)}"
