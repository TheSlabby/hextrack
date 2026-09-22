"""The fictional people in the demo dataset (owner: B6).

* :data:`ROSTER`: the eight tracked friends, each with a main and secondary role, a champion
  pool, a skill level (so the leaderboard has spread), a starting rank and a few habits.
* :func:`make_opponents`: a deterministic pool of strangers with varied Riot IDs (spaces,
  numbers, a hyphen, two with non-ASCII letters) who fill the other slots in each game.

Every demo puuid starts with :data:`DEMO_PUUID_PREFIX` so ``seed-demo --reset`` can remove the
demo data without touching real accounts.
"""

from __future__ import annotations

import base64
import hashlib
import random
from dataclasses import dataclass
from typing import Final

from hextrack.demo.matchgen import CHAMPIONS_BY_KEY, CHAMPIONS_BY_ROLE, ROLES, Role
from hextrack.riotid import MAX_GAME_NAME_LENGTH, riot_id_key

DEMO_PUUID_PREFIX: Final = "demo-"
#: Real puuids are 78 characters of base64url.
PUUID_LENGTH: Final = 78
#: Profile icons that exist for every account (the defaults and the classic set).
PROFILE_ICONS: Final[tuple[int, ...]] = (*range(0, 29), *range(588, 601))


def demo_puuid(game_name: str, tag_line: str) -> str:
    """Stable, realistic-looking puuid for a demo Riot ID (same name -> same puuid)."""
    key = "#".join(riot_id_key(game_name, tag_line)).encode()
    digest = hashlib.sha512(key).digest() + hashlib.sha256(key).digest()
    body = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return (DEMO_PUUID_PREFIX + body)[:PUUID_LENGTH]


@dataclass(frozen=True, slots=True)
class RosterPlayer:
    """A tracked friend. Champion pools are Data Dragon keys with pick weights."""

    game_name: str
    tag_line: str
    main_role: Role
    secondary_role: Role
    main_pool: tuple[tuple[str, float], ...]
    secondary_pool: tuple[tuple[str, float], ...]
    #: -1 .. 1. Drives win rate, individual stat lines and so the LP journey.
    skill: float
    start_tier: str
    #: None for apex tiers.
    start_rank: str | None
    start_lp: int
    #: Relative share of the group's games.
    activity: float
    profile_icon_id: int
    summoner_level: int
    aggression: float = 1.0
    vision: float = 1.0
    pings: float = 1.0
    flash_on_d: bool = True
    #: Plays ranked flex with the group.
    plays_flex: bool = True

    @property
    def riot_id(self) -> str:
        return f"{self.game_name}#{self.tag_line}"

    @property
    def puuid(self) -> str:
        return demo_puuid(self.game_name, self.tag_line)

    def pool_for(self, role: Role) -> tuple[tuple[str, float], ...]:
        if role == self.main_role:
            return self.main_pool
        if role == self.secondary_role:
            return self.secondary_pool
        return ()


ROSTER: Final[tuple[RosterPlayer, ...]] = (
    RosterPlayer(
        "Hexwalker", "NA1", "MIDDLE", "JUNGLE",
        (("Ahri", 3.0), ("Orianna", 2.0), ("Viktor", 2.0), ("Sylas", 1.5), ("Hwei", 1.0)),
        (("Viego", 2.0), ("Graves", 1.5), ("Kindred", 1.0)),
        skill=0.3, start_tier="EMERALD", start_rank="III", start_lp=40, activity=1.3,
        profile_icon_id=588, summoner_level=347, vision=1.05,
    ),
    RosterPlayer(
        "Baron Stealer", "GG", "JUNGLE", "TOP",
        (("Khazix", 3.0), ("Nidalee", 2.0), ("Elise", 1.5), ("Kindred", 1.5)),
        (("Jax", 2.0), ("Camille", 1.5)),
        skill=0.0, start_tier="GOLD", start_rank="I", start_lp=55, activity=0.95,
        profile_icon_id=23, summoner_level=211, aggression=1.1,
    ),
    RosterPlayer(
        "Ward Bot 9000", "SUP", "UTILITY", "BOTTOM",
        (("Thresh", 3.0), ("Nautilus", 2.0), ("Lulu", 2.0), ("Rakan", 1.5), ("Bard", 1.0)),
        (("Ashe", 2.0), ("MissFortune", 1.5)),
        skill=0.2, start_tier="PLATINUM", start_rank="II", start_lp=20, activity=1.1,
        profile_icon_id=596, summoner_level=402, vision=1.4, pings=1.3,
    ),
    RosterPlayer(
        "Jungle Diff", "JGL", "JUNGLE", "MIDDLE",
        (
            ("LeeSin", 3.0), ("MonkeyKing", 2.0), ("Viego", 2.0),
            ("JarvanIV", 1.5), ("Graves", 1.5),
        ),
        (("Syndra", 2.0), ("Taliyah", 1.5)),
        skill=0.65, start_tier="DIAMOND", start_rank="III", start_lp=35, activity=1.15,
        profile_icon_id=599, summoner_level=563, aggression=1.05, pings=1.2,
    ),
    RosterPlayer(
        "Mid Or Feed", "MID", "MIDDLE", "TOP",
        (("Yasuo", 3.5), ("Yone", 2.5), ("Zed", 2.0), ("Katarina", 1.5)),
        (("Riven", 2.0), ("Irelia", 1.5)),
        skill=-0.5, start_tier="SILVER", start_rank="I", start_lp=45, activity=1.0,
        profile_icon_id=7, summoner_level=158, aggression=1.45, vision=0.7, pings=1.5,
        flash_on_d=False,
    ),
    RosterPlayer(
        "Kite Theory", "ADC", "BOTTOM", "MIDDLE",
        (("Jinx", 3.0), ("Kaisa", 2.5), ("Jhin", 2.0), ("Vayne", 1.5), ("Ashe", 1.0)),
        (("Corki", 2.0), ("Akshan", 1.5)),
        skill=0.4, start_tier="EMERALD", start_rank="IV", start_lp=10, activity=1.1,
        profile_icon_id=592, summoner_level=289,
    ),
    RosterPlayer(
        "Top Island", "TOP", "TOP", "JUNGLE",
        (("Darius", 3.0), ("Garen", 2.0), ("Malphite", 2.0), ("Ornn", 1.5), ("Sett", 1.5)),
        (("Warwick", 2.0), ("Amumu", 1.5)),
        skill=-0.15, start_tier="GOLD", start_rank="II", start_lp=30, activity=0.8,
        profile_icon_id=14, summoner_level=176, vision=0.8, pings=0.35,
    ),
    RosterPlayer(
        "Dragon Soul", "EZ", "BOTTOM", "UTILITY",
        (("Ezreal", 4.0), ("Caitlyn", 2.0), ("Lucian", 1.5), ("Xayah", 1.0)),
        (("Karma", 2.0), ("Seraphine", 1.5)),
        skill=-0.05, start_tier="PLATINUM", start_rank="IV", start_lp=15, activity=0.75,
        profile_icon_id=600, summoner_level=233, flash_on_d=False,
    ),
)  # fmt: skip

#: Pairs of roster indices that like to queue together (weight multiplier for duos/stacks).
DUO_AFFINITY: Final[dict[frozenset[int], float]] = {
    frozenset({5, 2}): 6.0,  # Kite Theory + Ward Bot 9000: the bot lane duo
    frozenset({3, 4}): 3.0,  # Jungle Diff babysitting Mid Or Feed
    frozenset({0, 3}): 3.0,  # Hexwalker + Jungle Diff
    frozenset({1, 6}): 3.0,  # Baron Stealer + Top Island
    frozenset({7, 2}): 2.0,  # Dragon Soul + Ward Bot 9000
    frozenset({0, 5}): 2.0,  # Hexwalker + Kite Theory
}

# --- extra roster members (players > 8) ------------------------------------------------------

_EXTRA_TIERS: Final[tuple[tuple[str, str | None], ...]] = (
    ("SILVER", "II"),
    ("GOLD", "III"),
    ("GOLD", "I"),
    ("PLATINUM", "III"),
    ("EMERALD", "II"),
    ("DIAMOND", "IV"),
)


def extra_roster_player(rng: random.Random, game_name: str, tag_line: str) -> RosterPlayer:
    """A generated tracked player for ``players`` beyond the eight hand-written ones."""
    main, secondary = rng.sample(ROLES, 2)
    main_pool = rng.sample(CHAMPIONS_BY_ROLE[main], 4)
    secondary_pool = rng.sample([c for c in CHAMPIONS_BY_ROLE[secondary] if c not in main_pool], 2)
    tier, rank = rng.choice(_EXTRA_TIERS)
    return RosterPlayer(
        game_name,
        tag_line,
        main,
        secondary,
        tuple((c.key, round(rng.uniform(1.0, 3.0), 2)) for c in main_pool),
        tuple((c.key, round(rng.uniform(1.0, 2.0), 2)) for c in secondary_pool),
        skill=round(rng.uniform(-0.5, 0.5), 3),
        start_tier=tier,
        start_rank=rank,
        start_lp=rng.randint(0, 90),
        activity=round(rng.uniform(0.6, 1.1), 3),
        profile_icon_id=rng.choice(PROFILE_ICONS),
        summoner_level=rng.randint(60, 500),
        aggression=round(rng.uniform(0.85, 1.2), 3),
        vision=round(rng.uniform(0.8, 1.2), 3),
        pings=round(rng.uniform(0.5, 1.4), 3),
        flash_on_d=rng.random() < 0.7,
    )


# --- opponents -------------------------------------------------------------------------------

_ADJECTIVES: Final[tuple[str, ...]] = (
    "Silent", "Tilted", "Salty", "Frozen", "Crimson", "Lucky", "Sleepy", "Feral", "Hidden",
    "Golden", "Void", "Shadow", "Broken", "Lonely", "Swift", "Wild", "Humble", "Angry",
    "Cursed", "Clutch", "Lowkey", "Mystic", "Rogue", "Savage", "Spicy", "Cozy", "Gentle",
    "Elder", "Arcane", "Chaos", "Stellar", "Solar", "Lunar", "Iron", "Tiny", "Mad", "Sad",
    "Hungry", "Sneaky", "Dark", "Hyper", "Ultra", "Night", "Storm", "Neon", "Pixel", "Retro",
    "Ghost", "Frost", "Ember", "Rift", "Blue", "Red", "Quiet", "Loud", "Brave", "Grumpy",
    "Jolly", "Rusty", "Shiny", "Wicked", "Noble", "Feisty", "Chill", "Toasty", "Stormy",
)  # fmt: skip
_NOUNS: Final[tuple[str, ...]] = (
    "Penguin", "Poro", "Blade", "Fox", "Wolf", "Tiger", "Dragon", "Minion", "Scuttle",
    "Raptor", "Krug", "Gromp", "Herald", "Ward", "Tower", "Nexus", "Knight", "Wizard", "Monk",
    "Ninja", "Samurai", "Viking", "Pirate", "Goblin", "Yordle", "Enjoyer", "Gamer", "Potato",
    "Waffle", "Noodle", "Pancake", "Taco", "Muffin", "Pickle", "Bean", "Otter", "Panda",
    "Koala", "Sloth", "Duck", "Goose", "Crow", "Raven", "Hawk", "Falcon", "Shark", "Whale",
    "Kraken", "Hydra", "Phoenix", "Golem", "Titan", "Specter", "Wraith", "Spirit", "Sage",
    "Oracle", "Nomad", "Drifter", "Wanderer", "Comet", "Meteor", "Echo", "Cipher", "Glitch",
    "Lantern", "Anchor", "Badger", "Moose", "Walrus", "Lynx", "Bard",
)  # fmt: skip
_PLACES: Final[tuple[str, ...]] = (
    "Ionia", "Demacia", "Noxus", "Piltover", "Zaun", "Freljord", "Shurima", "Bilgewater",
    "Targon", "Ixtal", "the Void", "the Rift",
)  # fmt: skip
_CHAMP_NAMES: Final[tuple[str, ...]] = (
    "Teemo", "Yasuo", "Yone", "Zed", "Lux", "Jinx", "Thresh", "Garen", "Darius", "Ezreal",
    "Ahri", "Riven", "Vayne", "Draven", "Lee Sin", "Blitz", "Nami", "Soraka", "Shaco", "Singed",
    "Kaisa", "Sett", "Ornn", "Pyke", "Viego", "Rell", "Sona", "Rammus", "Zoe", "Nasus",
)  # fmt: skip
_TAG_WORDS: Final[tuple[str, ...]] = (
    "GG", "LUL", "FF15", "BOT", "GOAT", "RIP", "OTP", "1v9", "KEK", "TTV", "COPE", "EUW",
    "NA", "XD", "WIN", "LOSS", "TILT", "MAIN", "UWU", "404", "PENTA", "SOLO", "DUO", "ACE",
)  # fmt: skip
#: Fixed names so the demo always has a hyphenated and two non-ASCII Riot IDs.
_FIXED_OPPONENTS: Final[tuple[tuple[str, str], ...]] = (
    ("Señor Gank", "MX1"),
    ("Ōkami", "JP1"),
    ("Pre-Nerf Poro", "NA1"),
)


def _random_name(rng: random.Random) -> str:
    adj, noun = rng.choice(_ADJECTIVES), rng.choice(_NOUNS)
    pattern = rng.randrange(12)
    if pattern == 0:
        return f"{adj}{noun}"
    if pattern == 1:
        return f"{adj} {noun}"
    if pattern == 2:
        return f"{noun}{rng.choice((rng.randint(1, 99), rng.randint(100, 9999), 420, 1337, 69))}"
    if pattern == 3:
        return f"{adj.lower()}{noun.lower()}"
    if pattern == 4:
        return f"x{adj}{noun}x"
    if pattern == 5:
        return f"{rng.choice(_CHAMP_NAMES)} {rng.choice(('Main', 'OTP', 'Enjoyer', 'Abuser'))}"
    if pattern == 6:
        return f"The {adj} {noun}"
    if pattern == 7:
        return f"{noun} of {rng.choice(_PLACES)}"
    if pattern == 8:
        return f"{adj}{noun}{rng.randint(10, 99)}"
    if pattern == 9:
        return f"not {rng.choice(('a', 'your', 'the'))} {noun.lower()}"
    if pattern == 10:
        return f"{noun}{rng.choice(('Gaming', 'Plays', 'TV', 'Diff', 'Gap'))}"
    return f"{noun}{rng.choice(_NOUNS)}"


def _random_tag(rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.55:
        return "NA1"
    if roll < 0.75:
        return str(rng.randint(1000, 9999))
    if roll < 0.95:
        return rng.choice(_TAG_WORDS)
    return f"{rng.choice('ABCDEFGHJKMNPQRSTUVWXYZ')}{rng.randint(10, 999)}"


@dataclass(frozen=True, slots=True)
class Opponent:
    game_name: str
    tag_line: str
    main_role: Role
    #: Three favourite champions (Data Dragon keys) for the main role.
    favorites: tuple[str, ...]
    #: ``hextrack.rank.rank_value`` of their solo queue standing; matchmaking pulls
    #: opponents close to the lobby's average.
    rank_value: int
    profile_icon_id: int
    summoner_level: int
    skill: float
    aggression: float
    vision: float
    pings: float
    flash_on_d: bool

    @property
    def puuid(self) -> str:
        return demo_puuid(self.game_name, self.tag_line)


def make_opponents(
    rng: random.Random,
    count: int,
    *,
    rank_range: tuple[int, int],
    taken: set[tuple[str, str]],
) -> list[Opponent]:
    """``count`` opponents with unique Riot IDs (case-insensitive, never in ``taken``) whose
    rank values are spread evenly over ``rank_range``. ``taken`` is updated with the new
    keys."""
    names: list[tuple[str, str]] = []
    for name, tag in _FIXED_OPPONENTS[: min(count, len(_FIXED_OPPONENTS))]:
        if riot_id_key(name, tag) not in taken:
            taken.add(riot_id_key(name, tag))
            names.append((name, tag))
    attempts = 0
    while len(names) < count:
        attempts += 1
        if attempts > count * 200:
            raise RuntimeError("could not generate enough unique opponent names")
        name = _random_name(rng)
        if not 3 <= len(name) <= MAX_GAME_NAME_LENGTH:
            continue
        tag = _random_tag(rng)
        key = riot_id_key(name, tag)
        if key in taken:
            continue
        taken.add(key)
        names.append((name, tag))

    lo, hi = rank_range
    fixed = set(names[: len(_FIXED_OPPONENTS)])
    order = list(range(len(names)))
    rng.shuffle(order)
    opponents: list[Opponent] = []
    for i, (name, tag) in zip(order, names, strict=True):
        role = rng.choice(ROLES)
        favorites = tuple(c.key for c in rng.sample(CHAMPIONS_BY_ROLE[role], 3))
        # Even spread plus jitter so every lobby has candidates close to its rank; the fixed
        # names sit mid-range so they actually show up in games.
        position = (i + rng.random()) / max(1, len(names))
        if (name, tag) in fixed:
            position = 0.4 + 0.2 * rng.random()
        value = int(lo + (hi - lo) * position)
        opponents.append(
            Opponent(
                game_name=name,
                tag_line=tag,
                main_role=role,
                favorites=favorites,
                rank_value=value,
                profile_icon_id=rng.choice(PROFILE_ICONS),
                summoner_level=rng.randint(32, 650),
                skill=round(rng.gauss(0.0, 0.25), 3),
                aggression=round(rng.uniform(0.8, 1.3), 3),
                vision=round(rng.uniform(0.7, 1.25), 3),
                pings=round(rng.uniform(0.3, 1.6), 3),
                flash_on_d=rng.random() < 0.72,
            )
        )
    rng.shuffle(opponents)
    return opponents


def validate_roster() -> None:
    """Raise ValueError if a roster champion pool names an unknown or off-role champion."""
    for player in ROSTER:
        for role, pool in (
            (player.main_role, player.main_pool),
            (player.secondary_role, player.secondary_pool),
        ):
            for key, _ in pool:
                champ = CHAMPIONS_BY_KEY.get(key)
                if champ is None:
                    raise ValueError(f"{player.riot_id}: unknown champion {key!r}")
                if role not in champ.roles:
                    raise ValueError(f"{player.riot_id}: {key} is not a {role} champion")
