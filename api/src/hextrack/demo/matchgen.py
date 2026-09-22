"""Synthetic match-v5 payloads for the demo dataset (owner: B6).

:func:`generate_match` turns a :class:`MatchPlan` (who played what, who won, when and for how
long; decided by :mod:`hextrack.demo.seed`) into a dict with the exact shape Riot's
``GET /lol/match/v5/matches/{matchId}`` returns: metadata, info, ten participants with every
stat :mod:`hextrack.ingest.mapping` reads (plus the usual extras such as ``challenges``,
``perks`` and ping counters) and two teams with bans, feats and objectives.

The game is simulated rather than sampled stat by stat, so the numbers agree with each other:

* kills come from a timeline of fights. Every kill has a killer, a victim and assisters on the
  killer's team, which makes team kills equal the sum of participant kills, deaths equal the
  enemy's kills and kill participation at most 100%. Multikills, killing sprees, first blood,
  time spent dead and longest time alive are read off the same timeline.
* gold is passive income plus minion, monster, kill, assist, tower and objective gold; items
  are bought from that budget, so richer players carry fuller builds.
* team objectives (towers, inhibitors, dragons, barons, grubs, herald, Atakhan) are credited
  to individual players, so per-player dragon/baron/turret kills add up to the team totals.
* role and champion class shape everything: supports farm little and ward a lot, junglers
  kill monsters, carries deal damage and earn gold; the winning side kills more, farms more and
  takes the objectives.

Everything is driven by the ``random.Random`` passed in, so a plan plus a seed always yields
the same payload. All item, champion, rune and summoner spell ids exist in Data Dragon 16.x.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

Role = Literal["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
ROLES: Final[tuple[Role, ...]] = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")

ChampClass = Literal["marksman", "mage", "assassin", "fighter", "tank", "enchanter", "catcher"]
DamageType = Literal["AD", "AP", "MIXED"]
Build = Literal[
    "adc_crit",
    "adc_onhit",
    "adc_caster",
    "lethality",
    "crit_melee",
    "bruiser",
    "ap_bruiser",
    "ap_burst",
    "ap_battle",
    "tank",
    "tank_support",
    "enchanter",
    "ap_support",
    "lethality_support",
]

BLUE: Final = 100
RED: Final = 200
DEMO_MATCH_PREFIX: Final = "DEMO_"
PLATFORM_ID: Final = "NA1"
#: endOfGameResult written for remakes (never scorable).
REMAKE_RESULT: Final = "Abort_Unexpected"
MAX_GAME_SECONDS: Final = 42 * 60
MIN_GAME_SECONDS: Final = 18 * 60


@dataclass(frozen=True, slots=True)
class Champion:
    id: int
    #: Data Dragon key, e.g. "MonkeyKing" for Wukong.
    key: str
    roles: tuple[Role, ...]
    cls: ChampClass
    damage: DamageType
    build: Build


def _c(
    cid: int, key: str, roles: str, cls: ChampClass, damage: DamageType, build: Build
) -> Champion:
    parsed = tuple(r for r in roles.split(","))
    return Champion(cid, key, parsed, cls, damage, build)  # type: ignore[arg-type]


#: 125 champions with their real ids and Data Dragon keys, grouped by main role.
CHAMPIONS: Final[tuple[Champion, ...]] = (
    # --- top ---
    _c(266, "Aatrox", "TOP", "fighter", "AD", "bruiser"),
    _c(122, "Darius", "TOP", "fighter", "AD", "bruiser"),
    _c(86, "Garen", "TOP", "fighter", "AD", "bruiser"),
    _c(114, "Fiora", "TOP", "fighter", "AD", "bruiser"),
    _c(92, "Riven", "TOP,MIDDLE", "fighter", "AD", "bruiser"),
    _c(58, "Renekton", "TOP", "fighter", "AD", "bruiser"),
    _c(54, "Malphite", "TOP,UTILITY", "tank", "AP", "tank"),
    _c(516, "Ornn", "TOP", "tank", "MIXED", "tank"),
    _c(887, "Gwen", "TOP", "fighter", "AP", "ap_bruiser"),
    _c(164, "Camille", "TOP", "fighter", "AD", "bruiser"),
    _c(420, "Illaoi", "TOP", "fighter", "AD", "bruiser"),
    _c(24, "Jax", "TOP,JUNGLE", "fighter", "MIXED", "bruiser"),
    _c(75, "Nasus", "TOP", "fighter", "AD", "bruiser"),
    _c(36, "DrMundo", "TOP", "tank", "MIXED", "tank"),
    _c(85, "Kennen", "TOP", "mage", "AP", "ap_burst"),
    _c(126, "Jayce", "TOP,MIDDLE", "fighter", "AD", "lethality"),
    _c(875, "Sett", "TOP,UTILITY", "fighter", "AD", "bruiser"),
    _c(150, "Gnar", "TOP", "fighter", "AD", "bruiser"),
    _c(39, "Irelia", "TOP,MIDDLE", "fighter", "AD", "bruiser"),
    _c(98, "Shen", "TOP", "tank", "MIXED", "tank"),
    _c(17, "Teemo", "TOP", "mage", "AP", "ap_battle"),
    _c(897, "KSante", "TOP", "tank", "AD", "tank"),
    _c(799, "Ambessa", "TOP", "fighter", "AD", "bruiser"),
    # --- jungle ---
    _c(64, "LeeSin", "JUNGLE", "fighter", "AD", "bruiser"),
    _c(62, "MonkeyKing", "JUNGLE,TOP", "fighter", "AD", "bruiser"),
    _c(121, "Khazix", "JUNGLE", "assassin", "AD", "lethality"),
    _c(107, "Rengar", "JUNGLE,TOP", "assassin", "AD", "lethality"),
    _c(76, "Nidalee", "JUNGLE", "assassin", "AP", "ap_burst"),
    _c(254, "Vi", "JUNGLE", "fighter", "AD", "bruiser"),
    _c(104, "Graves", "JUNGLE", "marksman", "AD", "adc_crit"),
    _c(11, "MasterYi", "JUNGLE", "fighter", "AD", "crit_melee"),
    _c(5, "XinZhao", "JUNGLE", "fighter", "AD", "bruiser"),
    _c(59, "JarvanIV", "JUNGLE", "fighter", "AD", "bruiser"),
    _c(20, "Nunu", "JUNGLE", "tank", "AP", "tank"),
    _c(32, "Amumu", "JUNGLE,UTILITY", "tank", "AP", "tank"),
    _c(120, "Hecarim", "JUNGLE", "fighter", "AD", "bruiser"),
    _c(141, "Kayn", "JUNGLE", "assassin", "AD", "lethality"),
    _c(234, "Viego", "JUNGLE", "fighter", "AD", "crit_melee"),
    _c(876, "Lillia", "JUNGLE", "mage", "AP", "ap_battle"),
    _c(113, "Sejuani", "JUNGLE", "tank", "MIXED", "tank"),
    _c(79, "Gragas", "JUNGLE,TOP", "tank", "AP", "ap_battle"),
    _c(28, "Evelynn", "JUNGLE", "assassin", "AP", "ap_burst"),
    _c(60, "Elise", "JUNGLE", "mage", "AP", "ap_burst"),
    _c(203, "Kindred", "JUNGLE", "marksman", "AD", "adc_crit"),
    _c(19, "Warwick", "JUNGLE,TOP", "fighter", "MIXED", "bruiser"),
    _c(56, "Nocturne", "JUNGLE", "assassin", "AD", "bruiser"),
    _c(200, "Belveth", "JUNGLE", "fighter", "AD", "adc_onhit"),
    _c(33, "Rammus", "JUNGLE", "tank", "MIXED", "tank"),
    _c(233, "Briar", "JUNGLE", "fighter", "AD", "bruiser"),
    _c(421, "RekSai", "JUNGLE", "fighter", "AD", "bruiser"),
    _c(9, "Fiddlesticks", "JUNGLE", "mage", "AP", "ap_burst"),
    # --- mid ---
    _c(103, "Ahri", "MIDDLE", "mage", "AP", "ap_burst"),
    _c(157, "Yasuo", "MIDDLE,TOP", "fighter", "AD", "crit_melee"),
    _c(777, "Yone", "MIDDLE,TOP", "fighter", "MIXED", "crit_melee"),
    _c(238, "Zed", "MIDDLE", "assassin", "AD", "lethality"),
    _c(61, "Orianna", "MIDDLE", "mage", "AP", "ap_burst"),
    _c(7, "Leblanc", "MIDDLE", "assassin", "AP", "ap_burst"),
    _c(134, "Syndra", "MIDDLE", "mage", "AP", "ap_burst"),
    _c(99, "Lux", "MIDDLE,UTILITY", "mage", "AP", "ap_burst"),
    _c(1, "Annie", "MIDDLE", "mage", "AP", "ap_burst"),
    _c(4, "TwistedFate", "MIDDLE", "mage", "AP", "ap_burst"),
    _c(91, "Talon", "MIDDLE,JUNGLE", "assassin", "AD", "lethality"),
    _c(84, "Akali", "MIDDLE,TOP", "assassin", "AP", "ap_bruiser"),
    _c(105, "Fizz", "MIDDLE", "assassin", "AP", "ap_burst"),
    _c(245, "Ekko", "MIDDLE,JUNGLE", "assassin", "AP", "ap_bruiser"),
    _c(268, "Azir", "MIDDLE", "mage", "AP", "ap_battle"),
    _c(517, "Sylas", "MIDDLE,JUNGLE", "fighter", "AP", "ap_bruiser"),
    _c(112, "Viktor", "MIDDLE", "mage", "AP", "ap_burst"),
    _c(69, "Cassiopeia", "MIDDLE", "mage", "AP", "ap_battle"),
    _c(131, "Diana", "MIDDLE,JUNGLE", "assassin", "AP", "ap_bruiser"),
    _c(55, "Katarina", "MIDDLE", "assassin", "AP", "ap_bruiser"),
    _c(8, "Vladimir", "MIDDLE,TOP", "mage", "AP", "ap_battle"),
    _c(127, "Lissandra", "MIDDLE", "mage", "AP", "ap_burst"),
    _c(90, "Malzahar", "MIDDLE", "mage", "AP", "ap_battle"),
    _c(13, "Ryze", "MIDDLE", "mage", "AP", "ap_battle"),
    _c(101, "Xerath", "MIDDLE,UTILITY", "mage", "AP", "ap_burst"),
    _c(38, "Kassadin", "MIDDLE", "assassin", "AP", "ap_burst"),
    _c(163, "Taliyah", "MIDDLE,JUNGLE", "mage", "AP", "ap_burst"),
    _c(711, "Vex", "MIDDLE", "mage", "AP", "ap_burst"),
    _c(142, "Zoe", "MIDDLE", "mage", "AP", "ap_burst"),
    _c(910, "Hwei", "MIDDLE", "mage", "AP", "ap_burst"),
    _c(893, "Aurora", "MIDDLE,TOP", "mage", "AP", "ap_burst"),
    _c(166, "Akshan", "MIDDLE", "marksman", "AD", "adc_crit"),
    _c(42, "Corki", "MIDDLE", "marksman", "MIXED", "adc_caster"),
    _c(950, "Naafiri", "MIDDLE", "assassin", "AD", "lethality"),
    # --- bot ---
    _c(222, "Jinx", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(51, "Caitlyn", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(81, "Ezreal", "BOTTOM", "marksman", "AD", "adc_caster"),
    _c(236, "Lucian", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(67, "Vayne", "BOTTOM,TOP", "marksman", "AD", "adc_onhit"),
    _c(145, "Kaisa", "BOTTOM", "marksman", "MIXED", "adc_onhit"),
    _c(202, "Jhin", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(21, "MissFortune", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(22, "Ashe", "BOTTOM,UTILITY", "marksman", "AD", "adc_crit"),
    _c(498, "Xayah", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(119, "Draven", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(18, "Tristana", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(15, "Sivir", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(29, "Twitch", "BOTTOM", "marksman", "AD", "adc_onhit"),
    _c(96, "KogMaw", "BOTTOM", "marksman", "MIXED", "adc_onhit"),
    _c(110, "Varus", "BOTTOM", "marksman", "AD", "adc_onhit"),
    _c(523, "Aphelios", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(221, "Zeri", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(360, "Samira", "BOTTOM", "marksman", "AD", "adc_crit"),
    _c(901, "Smolder", "BOTTOM", "marksman", "MIXED", "adc_caster"),
    _c(895, "Nilah", "BOTTOM", "marksman", "AD", "adc_crit"),
    # --- support ---
    _c(412, "Thresh", "UTILITY", "catcher", "MIXED", "tank_support"),
    _c(117, "Lulu", "UTILITY", "enchanter", "AP", "enchanter"),
    _c(267, "Nami", "UTILITY", "enchanter", "AP", "enchanter"),
    _c(40, "Janna", "UTILITY", "enchanter", "AP", "enchanter"),
    _c(53, "Blitzcrank", "UTILITY", "catcher", "AP", "tank_support"),
    _c(111, "Nautilus", "UTILITY", "catcher", "AP", "tank_support"),
    _c(89, "Leona", "UTILITY", "catcher", "AP", "tank_support"),
    _c(497, "Rakan", "UTILITY", "catcher", "AP", "enchanter"),
    _c(350, "Yuumi", "UTILITY", "enchanter", "AP", "enchanter"),
    _c(555, "Pyke", "UTILITY", "assassin", "AD", "lethality_support"),
    _c(43, "Karma", "UTILITY", "enchanter", "AP", "enchanter"),
    _c(37, "Sona", "UTILITY", "enchanter", "AP", "enchanter"),
    _c(16, "Soraka", "UTILITY", "enchanter", "AP", "enchanter"),
    _c(201, "Braum", "UTILITY", "catcher", "MIXED", "tank_support"),
    _c(25, "Morgana", "UTILITY", "catcher", "AP", "ap_support"),
    _c(147, "Seraphine", "UTILITY,BOTTOM", "enchanter", "AP", "enchanter"),
    _c(526, "Rell", "UTILITY", "catcher", "AP", "tank_support"),
    _c(235, "Senna", "UTILITY", "marksman", "AD", "lethality_support"),
    _c(44, "Taric", "UTILITY", "enchanter", "MIXED", "tank_support"),
    _c(12, "Alistar", "UTILITY", "catcher", "AP", "tank_support"),
    _c(143, "Zyra", "UTILITY", "mage", "AP", "ap_support"),
    _c(63, "Brand", "UTILITY", "mage", "AP", "ap_support"),
    _c(902, "Milio", "UTILITY", "enchanter", "AP", "enchanter"),
    _c(888, "Renata", "UTILITY", "enchanter", "AP", "enchanter"),
    _c(432, "Bard", "UTILITY", "catcher", "AP", "enchanter"),
)
CHAMPIONS_BY_ID: Final[dict[int, Champion]] = {c.id: c for c in CHAMPIONS}
CHAMPIONS_BY_KEY: Final[dict[str, Champion]] = {c.key: c for c in CHAMPIONS}
CHAMPIONS_BY_ROLE: Final[dict[Role, tuple[Champion, ...]]] = {
    role: tuple(c for c in CHAMPIONS if role in c.roles) for role in ROLES
}

#: Champions whose kit heals allies / shields allies (drives the teammate heal/shield stats).
HEALERS: Final[frozenset[int]] = frozenset({16, 267, 37, 350, 902, 147, 235, 44, 432, 888})
SHIELDERS: Final[frozenset[int]] = frozenset({117, 40, 43, 147, 902, 44, 497, 99, 61, 412})

# --- summoner spells -----------------------------------------------------------------------

FLASH: Final = 4
SMITE: Final = 11
IGNITE: Final = 14
TELEPORT: Final = 12
HEAL: Final = 7
EXHAUST: Final = 3
BARRIER: Final = 21
GHOST: Final = 6
CLEANSE: Final = 1

#: (spell pair, weight) per role; the first spell is the one paired with Flash when present.
SPELLS_BY_ROLE: Final[dict[Role, tuple[tuple[tuple[int, int], float], ...]]] = {
    "TOP": (
        ((FLASH, TELEPORT), 0.55),
        ((FLASH, IGNITE), 0.25),
        ((GHOST, TELEPORT), 0.08),
        ((FLASH, GHOST), 0.07),
        ((FLASH, EXHAUST), 0.05),
    ),
    "JUNGLE": (((FLASH, SMITE), 0.9), ((GHOST, SMITE), 0.08), ((IGNITE, SMITE), 0.02)),
    "MIDDLE": (
        ((FLASH, IGNITE), 0.4),
        ((FLASH, TELEPORT), 0.35),
        ((FLASH, BARRIER), 0.12),
        ((FLASH, CLEANSE), 0.08),
        ((FLASH, GHOST), 0.05),
    ),
    "BOTTOM": (
        ((FLASH, HEAL), 0.7),
        ((FLASH, BARRIER), 0.12),
        ((FLASH, CLEANSE), 0.1),
        ((GHOST, HEAL), 0.05),
        ((FLASH, EXHAUST), 0.03),
    ),
    "UTILITY": (
        ((FLASH, IGNITE), 0.4),
        ((FLASH, EXHAUST), 0.35),
        ((FLASH, HEAL), 0.12),
        ((FLASH, TELEPORT), 0.05),
        ((FLASH, BARRIER), 0.03),
        ((FLASH, CLEANSE), 0.05),
    ),
}

# --- items -----------------------------------------------------------------------------------

STEALTH_WARD: Final = 3340
ORACLE_LENS: Final = 3364
FARSIGHT: Final = 3363
CONTROL_WARD: Final = 2055
HEALTH_POTION: Final = 2003
JUNGLE_PETS: Final[tuple[int, ...]] = (1101, 1102, 1103)
#: Upgraded support quest items (Bounty of Worlds upgrades).
SUPPORT_ITEMS: Final[tuple[int, ...]] = (3869, 3870, 3871, 3876, 3877)
WORLD_ATLAS: Final = 3865

#: Gold cost of every item the generator can place (Data Dragon 16.18 prices).
ITEM_COST: Final[dict[int, int]] = {
    # boots
    3006: 1100, 3020: 1100, 3047: 1200, 3111: 1250, 3158: 900, 3009: 1000,
    # marksman / crit
    3031: 3500, 3094: 2650, 3036: 3300, 3072: 3400, 3046: 2650, 3085: 2650, 6672: 3000,
    3153: 3200, 6675: 2650, 3033: 3000, 3026: 3200, 3032: 3000, 3508: 3050, 6676: 3000,
    3087: 3000, 3124: 3000, 3091: 2800, 3139: 3200, 6673: 3000, 3004: 2900, 3078: 3333,
    6694: 3000, 3161: 3100, 6333: 3300, 3302: 3000,
    # lethality
    6692: 2900, 3142: 2800, 6697: 2800, 6698: 2850, 3814: 3000, 3179: 2800,
    # fighter
    3071: 3000, 3074: 3300, 3053: 3200, 6610: 3100, 6631: 3300, 3748: 3300, 3181: 3000,
    3065: 2700, 3073: 3000, 2501: 3300,
    # mage
    3089: 3500, 3135: 3000, 3157: 3250, 3165: 2850, 3102: 3000, 3116: 2600, 3100: 2900,
    3115: 2900, 4633: 3100, 6653: 3000, 4645: 3200, 3041: 1500, 6655: 2750, 4646: 2800,
    3118: 2700, 4628: 2700, 4629: 3000, 6657: 2600, 3003: 2900, 3137: 3000, 3152: 2650,
    # tank
    3068: 2800, 3075: 2450, 3143: 2700, 3742: 2900, 3084: 3000, 3083: 3100, 3110: 2500,
    4401: 2800, 6665: 3200, 8020: 2650, 2504: 2900, 2502: 2800,
    # support
    3190: 2200, 3050: 2200, 3109: 2300, 3107: 2300, 3504: 2200, 2065: 2200, 6617: 2200,
    6620: 2200, 6621: 2500, 3222: 2300,
    # components
    1038: 1300, 1037: 875, 1018: 600, 1042: 250, 1036: 350, 1043: 700, 1058: 1200,
    1026: 850, 1052: 400, 3802: 1200, 3108: 850, 3916: 800, 1011: 900, 1031: 800,
    1057: 850, 1028: 400, 1029: 300, 1033: 400, 3133: 1050, 3077: 1200, 1082: 350,
    # starters / wards
    1054: 450, 1055: 450, 1056: 400, 1083: 450, 2003: 50, 2055: 75, 3865: 400,
    1101: 450, 1102: 450, 1103: 450, 3869: 400, 3870: 400, 3871: 400, 3876: 400, 3877: 400,
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class BuildPlan:
    #: Items one of which is bought first (the "mythic-like" core).
    first: tuple[int, ...]
    #: Pool for later completed items.
    core: tuple[int, ...]
    boots: tuple[tuple[int, float], ...]
    components: tuple[int, ...]
    #: (primary style, keystone, weight).
    keystones: tuple[tuple[int, int, float], ...]
    secondary_styles: tuple[int, ...]
    #: Stat shard (offense) preference.
    offense_shard: int


BUILDS: Final[dict[Build, BuildPlan]] = {
    "adc_crit": BuildPlan(
        first=(6672, 3032, 3508, 6676, 3087),
        core=(3031, 3094, 3036, 3072, 3046, 3085, 6675, 3033, 3026, 3139, 6673),
        boots=((3006, 0.8), (3009, 0.1), (3111, 0.1)),
        components=(1038, 1037, 1018, 1036, 1043),
        keystones=((8000, 8008, 0.45), (8000, 8005, 0.25), (8000, 8021, 0.15), (8100, 9923, 0.15)),
        secondary_styles=(8300, 8100, 8400, 8200),
        offense_shard=5005,
    ),
    "adc_onhit": BuildPlan(
        first=(3153, 6672, 3124),
        core=(3091, 3085, 3046, 3115, 3026, 3036, 3139, 3302, 6673),
        boots=((3006, 0.85), (3111, 0.15)),
        components=(1043, 1037, 1042, 1018, 1036),
        keystones=((8000, 8008, 0.6), (8000, 8005, 0.2), (8100, 9923, 0.2)),
        secondary_styles=(8300, 8100, 8400, 8200),
        offense_shard=5005,
    ),
    "adc_caster": BuildPlan(
        first=(3004, 3078, 3508),
        core=(6694, 3161, 6333, 3026, 3036, 3071, 3072),
        boots=((3158, 0.7), (3006, 0.2), (3047, 0.1)),
        components=(3133, 1037, 1036, 1038),
        keystones=((8000, 8010, 0.45), (8200, 8229, 0.25), (8300, 8369, 0.3)),
        secondary_styles=(8300, 8200, 8400),
        offense_shard=5008,
    ),
    "lethality": BuildPlan(
        first=(6692, 3142, 6698, 6697),
        core=(3814, 6694, 3179, 6676, 3036, 6333, 3071, 3026),
        boots=((3047, 0.35), (3111, 0.3), (3158, 0.25), (3009, 0.1)),
        components=(3133, 1036, 1037, 3077),
        keystones=((8100, 8112, 0.55), (8300, 8369, 0.25), (8100, 8128, 0.2)),
        secondary_styles=(8000, 8300, 8200),
        offense_shard=5008,
    ),
    "crit_melee": BuildPlan(
        first=(3153, 6675, 3087),
        core=(3031, 6673, 3072, 3026, 3046, 3036, 3139, 3124),
        boots=((3006, 0.5), (3047, 0.3), (3111, 0.2)),
        components=(1038, 1037, 1018, 1042),
        keystones=((8000, 8010, 0.55), (8000, 8008, 0.45)),
        secondary_styles=(8400, 8100, 8300),
        offense_shard=5005,
    ),
    "bruiser": BuildPlan(
        first=(6610, 3078, 3074, 6631, 3071, 2501, 3073),
        core=(3161, 6333, 3053, 3748, 3181, 3065, 3026, 3075, 3143, 3071),
        boots=((3047, 0.5), (3111, 0.35), (3158, 0.15)),
        components=(3133, 1037, 3077, 1028, 1031),
        keystones=((8000, 8010, 0.6), (8400, 8437, 0.25), (8200, 8230, 0.15)),
        secondary_styles=(8400, 8000, 8300, 8100),
        offense_shard=5008,
    ),
    "ap_bruiser": BuildPlan(
        first=(4633, 3115, 3152, 3100),
        core=(3157, 3089, 3135, 6653, 4645, 3137, 3102, 4629),
        boots=((3020, 0.5), (3111, 0.3), (3047, 0.2)),
        components=(1058, 1026, 1052, 3108),
        keystones=((8000, 8010, 0.4), (8100, 8112, 0.35), (8100, 8128, 0.25)),
        secondary_styles=(8400, 8000, 8300, 8200),
        offense_shard=5008,
    ),
    "ap_burst": BuildPlan(
        first=(6655, 4646, 3118, 3100, 6657, 3003),
        core=(4645, 3089, 3135, 3157, 3165, 3102, 3137, 4628, 3041),
        boots=((3020, 0.75), (3158, 0.15), (3111, 0.1)),
        components=(1058, 1026, 1052, 3802, 3108, 3916),
        keystones=(
            (8200, 8229, 0.3),
            (8100, 8112, 0.3),
            (8200, 8214, 0.1),
            (8200, 8230, 0.1),
            (8100, 8128, 0.1),
            (8300, 8369, 0.1),
        ),
        secondary_styles=(8300, 8200, 8100, 8400),
        offense_shard=5008,
    ),
    "ap_battle": BuildPlan(
        first=(6653, 6657, 3003, 4629, 3115),
        core=(3116, 3157, 3089, 3135, 3165, 3102, 4645),
        boots=((3020, 0.6), (3158, 0.25), (3111, 0.15)),
        components=(1058, 1026, 1052, 1011, 3802),
        keystones=((8000, 8010, 0.35), (8200, 8214, 0.2), (8200, 8230, 0.25), (8000, 8008, 0.2)),
        secondary_styles=(8200, 8300, 8400),
        offense_shard=5008,
    ),
    "tank": BuildPlan(
        first=(3068, 3084, 6665, 2502),
        core=(3075, 3143, 3742, 3065, 3083, 3110, 4401, 8020, 2504),
        boots=((3047, 0.55), (3111, 0.45)),
        components=(1011, 1031, 1057, 1028, 1029, 1033),
        keystones=((8400, 8437, 0.45), (8400, 8439, 0.35), (8300, 8351, 0.1), (8000, 8010, 0.1)),
        secondary_styles=(8300, 8000, 8200, 8400),
        offense_shard=5007,
    ),
    "tank_support": BuildPlan(
        first=(3190, 3050, 3109),
        core=(3143, 3075, 2504, 3065, 3742, 8020, 3110, 3222, 3107),
        boots=((3047, 0.4), (3111, 0.35), (3009, 0.25)),
        components=(1029, 1033, 1028, 1031, 1057),
        keystones=((8400, 8439, 0.5), (8400, 8465, 0.2), (8300, 8351, 0.15), (8100, 9923, 0.15)),
        secondary_styles=(8300, 8400, 8200),
        offense_shard=5007,
    ),
    "enchanter": BuildPlan(
        first=(6617, 2065, 6620, 6621),
        core=(3504, 3107, 3222, 3190, 3109, 3050, 6617, 2065),
        boots=((3158, 0.6), (3009, 0.2), (3020, 0.2)),
        components=(1052, 1028, 1029, 1033),
        keystones=((8200, 8214, 0.6), (8400, 8465, 0.2), (8300, 8360, 0.1), (8200, 8229, 0.1)),
        secondary_styles=(8400, 8300, 8200),
        offense_shard=5007,
    ),
    "ap_support": BuildPlan(
        first=(6653, 3118, 6655),
        core=(3116, 3165, 3157, 4645, 3135, 3089, 4628),
        boots=((3020, 0.65), (3158, 0.35)),
        components=(1026, 1052, 1058, 3916),
        keystones=((8200, 8229, 0.45), (8100, 8112, 0.25), (8100, 8128, 0.15), (8200, 8214, 0.15)),
        secondary_styles=(8300, 8200, 8400, 8100),
        offense_shard=5008,
    ),
    "lethality_support": BuildPlan(
        first=(3179, 3142, 6676),
        core=(6697, 3814, 6694, 3036, 6692, 3031),
        boots=((3047, 0.4), (3111, 0.3), (3009, 0.3)),
        components=(1036, 3133, 1037),
        keystones=((8100, 9923, 0.45), (8000, 8021, 0.25), (8300, 8369, 0.15), (8100, 8112, 0.15)),
        secondary_styles=(8400, 8300, 8200),
        offense_shard=5008,
    ),
}

#: Runes per style: rows 1-3 (after the keystone row), ids from Data Dragon runesReforged.
RUNE_ROWS: Final[dict[int, tuple[tuple[int, ...], ...]]] = {
    8000: ((9101, 9111, 8009), (9104, 9105, 9103), (8014, 8017, 8299)),
    8100: ((8126, 8139, 8143), (8137, 8140, 8141), (8135, 8105, 8106)),
    8200: ((8224, 8226, 8275), (8210, 8234, 8233), (8237, 8232, 8236)),
    8300: ((8306, 8304, 8321), (8313, 8352, 8345), (8347, 8410, 8316)),
    8400: ((8446, 8463, 8401), (8429, 8444, 8473), (8451, 8453, 8242)),
}
FLEX_SHARDS: Final[tuple[int, ...]] = (5008, 5010, 5001)
DEFENSE_SHARDS: Final[tuple[int, ...]] = (5011, 5013, 5001)

# --- role / class tuning -------------------------------------------------------------------

ROLE_KILL_W: Final[dict[Role, float]] = {
    "TOP": 1.0, "JUNGLE": 1.0, "MIDDLE": 1.25, "BOTTOM": 1.35, "UTILITY": 0.35,
}  # fmt: skip
ROLE_DEATH_W: Final[dict[Role, float]] = {
    "TOP": 1.0, "JUNGLE": 0.95, "MIDDLE": 1.0, "BOTTOM": 1.05, "UTILITY": 1.05,
}  # fmt: skip
ROLE_ASSIST_P: Final[dict[Role, float]] = {
    "TOP": 0.55, "JUNGLE": 0.75, "MIDDLE": 0.64, "BOTTOM": 0.66, "UTILITY": 0.85,
}  # fmt: skip
ROLE_FIGHT_W: Final[dict[Role, float]] = {
    "TOP": 0.75, "JUNGLE": 1.3, "MIDDLE": 1.1, "BOTTOM": 1.1, "UTILITY": 1.25,
}  # fmt: skip
CLASS_KILL: Final[dict[ChampClass, float]] = {
    "marksman": 1.1, "mage": 1.0, "assassin": 1.3, "fighter": 1.05,
    "tank": 0.6, "enchanter": 0.35, "catcher": 0.55,
}  # fmt: skip
CLASS_DEATH: Final[dict[ChampClass, float]] = {
    "marksman": 1.0, "mage": 0.95, "assassin": 1.1, "fighter": 1.0,
    "tank": 0.9, "enchanter": 0.95, "catcher": 1.15,
}  # fmt: skip
#: Damage to champions per minute at an average gold income.
CLASS_DPM: Final[dict[ChampClass, float]] = {
    "marksman": 820, "mage": 800, "assassin": 700, "fighter": 680,
    "tank": 430, "enchanter": 380, "catcher": 330,
}  # fmt: skip
ROLE_DPM: Final[dict[Role, float]] = {
    "TOP": 0.95, "JUNGLE": 0.72, "MIDDLE": 1.0, "BOTTOM": 1.0, "UTILITY": 0.8,
}  # fmt: skip
CLASS_TAKEN: Final[dict[ChampClass, float]] = {
    "marksman": 650, "mage": 700, "assassin": 800, "fighter": 1150,
    "tank": 1350, "enchanter": 580, "catcher": 950,
}  # fmt: skip
CLASS_MITIGATION: Final[dict[ChampClass, float]] = {
    "marksman": 0.22, "mage": 0.3, "assassin": 0.35, "fighter": 0.65,
    "tank": 1.05, "enchanter": 0.35, "catcher": 0.9,
}  # fmt: skip
CLASS_CC: Final[dict[ChampClass, float]] = {
    "marksman": 0.4, "mage": 1.0, "assassin": 0.45, "fighter": 0.9,
    "tank": 1.7, "enchanter": 1.1, "catcher": 1.9,
}  # fmt: skip
CLASS_HEAL: Final[dict[ChampClass, float]] = {
    "marksman": 190, "mage": 110, "assassin": 160, "fighter": 330,
    "tank": 260, "enchanter": 320, "catcher": 180,
}  # fmt: skip
#: Damage dealt to non-champions per minion kill.
CLASS_MINION_DMG: Final[dict[ChampClass, float]] = {
    "marksman": 520, "mage": 420, "assassin": 400, "fighter": 480,
    "tank": 330, "enchanter": 150, "catcher": 150,
}  # fmt: skip
#: Lane minions per minute at average play.
ROLE_CS: Final[dict[Role, float]] = {
    "TOP": 7.1, "JUNGLE": 0.9, "MIDDLE": 7.5, "BOTTOM": 8.0, "UTILITY": 1.1,
}  # fmt: skip
#: Typical gold per minute (normalises damage by how fed a player is).
ROLE_GPM: Final[dict[Role, float]] = {
    "TOP": 400, "JUNGLE": 385, "MIDDLE": 410, "BOTTOM": 430, "UTILITY": 275,
}  # fmt: skip
#: (base level, levels per minute) for the final champion level.
ROLE_LEVEL: Final[dict[Role, tuple[float, float]]] = {
    "TOP": (6.2, 0.37), "JUNGLE": (5.6, 0.345), "MIDDLE": (6.2, 0.37),
    "BOTTOM": (5.2, 0.35), "UTILITY": (4.3, 0.315),
}  # fmt: skip
#: Base respawn timer by level 1..18 (seconds, Riot's BRW table).
_RESPAWN: Final[tuple[float, ...]] = (
    10, 10, 12, 12, 14, 16, 20, 25, 28, 32.5, 35, 37.5, 40, 42.5, 45, 47.5, 50, 52.5,
)  # fmt: skip
_FIGHT_SIZES: Final[tuple[tuple[int, float], ...]] = (
    (1, 0.42), (2, 0.24), (3, 0.15), (4, 0.1), (5, 0.06), (6, 0.02), (7, 0.01),
)  # fmt: skip
_PING_KEYS: Final[tuple[tuple[str, float], ...]] = (
    ("holdPings", 0.1),
    ("getBackPings", 0.07),
    ("onMyWayPings", 0.24),
    ("needVisionPings", 0.05),
    ("enemyMissingPings", 0.24),
    ("enemyVisionPings", 0.07),
    ("commandPings", 0.1),
    ("allInPings", 0.02),
    ("assistMePings", 0.05),
    ("pushPings", 0.03),
    ("visionClearedPings", 0.02),
    ("basicPings", 0.01),
)


# --- plan ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Slot:
    """One player in a planned game."""

    puuid: str
    game_name: str
    tag_line: str
    profile_icon_id: int
    summoner_level: int
    team_id: int
    role: Role
    champion_id: int
    #: -1 (struggling) .. 1 (smurfing); shifts this player's individual performance.
    skill: float = 0.0
    #: >1 fights more (more kills and deaths).
    aggression: float = 1.0
    #: Multiplier on warding.
    vision: float = 1.0
    #: Multiplier on pings.
    pings: float = 1.0
    #: Flash on D (summoner1) rather than F.
    flash_on_d: bool = True


@dataclass(frozen=True, slots=True)
class MatchPlan:
    match_id: str
    game_id: int
    queue_id: int
    #: Game start (UTC).
    start: datetime
    #: Seconds.
    duration_s: int
    winning_team: int
    remake: bool
    #: 10 slots, blue team first; each team has one of every role.
    slots: tuple[Slot, ...]
    #: 0 (Iron) .. 1 (Master+): lower elo games are bloodier and farm worse.
    lobby_elo: float = 0.5
    #: info.platformId, e.g. "NA1".
    platform_id: str = PLATFORM_ID


def game_version_for(start: datetime) -> str:
    """Patch live at ``start`` in Riot's cadence (season N = year - 2010, a patch every two
    weeks from early January), formatted like ``"16.17.712.5021"``."""
    day = start.astimezone(UTC).timetuple().tm_yday
    major = start.year - 2010
    if day < 15:
        major, minor = major - 1, 24
    else:
        minor = min(24, 1 + (day - 15) // 14)
    build = 700 + minor * 2
    revision = 1000 + (major * 7919 + minor * 104729) % 9000
    return f"{major}.{minor}.{build}.{revision}"


# --- simulation state ----------------------------------------------------------------------


@dataclass(slots=True)
class _Player:
    index: int
    slot: Slot
    champion: Champion
    win: bool
    perf: float
    final_level: int
    kill_w: float
    death_w: float
    kill_times: list[float] = field(default_factory=list)
    deaths: list[tuple[float, float]] = field(default_factory=list)  # (died, respawned)
    assists: int = 0
    solo_kills: int = 0
    first_blood_kill: bool = False
    first_blood_assist: bool = False
    kill_gold: float = 0.0
    assist_gold: float = 0.0
    streak: int = 0
    death_streak: int = 0
    largest_spree: int = 0
    sprees: int = 0
    respawn_at: float = 0.0
    # objectives
    dragon_kills: int = 0
    baron_kills: int = 0
    turret_kills: int = 0
    turret_takedowns: int = 0
    inhibitor_kills: int = 0
    inhibitor_takedowns: int = 0
    first_tower_kill: bool = False
    first_tower_assist: bool = False
    nexus_kills: int = 0
    nexus_takedowns: int = 0
    plates: int = 0
    objectives_stolen: int = 0
    dragon_takedowns: int = 0
    baron_takedowns: int = 0
    herald_takedowns: int = 0

    @property
    def team(self) -> int:
        return self.slot.team_id

    @property
    def role(self) -> Role:
        return self.slot.role

    def alive(self, t: float) -> bool:
        return t >= self.respawn_at


def _weighted[T](rng: random.Random, options: Sequence[tuple[T, float]]) -> T:
    total = sum(w for _, w in options)
    pick = rng.random() * total
    for value, weight in options:
        pick -= weight
        if pick <= 0:
            return value
    return options[-1][0]


def _pick_weighted(rng: random.Random, items: Sequence[_Player], weights: Sequence[float]) -> int:
    total = sum(weights)
    pick = rng.random() * total
    for i, w in enumerate(weights):
        pick -= w
        if pick <= 0:
            return i
    return len(items) - 1


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _level_at(p: _Player, t: float, duration: float) -> int:
    frac = _clamp(t / duration, 0.0, 1.0) if duration > 0 else 1.0
    return max(1, min(18, int(1 + (p.final_level - 1) * frac**0.75)))


def _respawn_seconds(level: int, t: float) -> float:
    base = _RESPAWN[level - 1]
    minutes = t / 60
    impact = _clamp((minutes - 15) * 0.0213, 0.0, 0.5)
    return base * (1 + impact)


def _final_level(rng: random.Random, role: Role, minutes: float, win: bool, perf: float) -> int:
    base, per_minute = ROLE_LEVEL[role]
    value = base + per_minute * minutes + (0.3 if win else -0.2) + 0.5 * perf
    value += rng.uniform(-0.6, 0.6)
    return int(_clamp(round(value), 1, 18))


def _experience_for(rng: random.Random, level: int) -> int:
    def cumulative(lv: int) -> int:
        return 180 * (lv - 1) + 50 * lv * (lv - 1)

    if level >= 18:
        return cumulative(18) + rng.randint(0, 6000)
    return cumulative(level) + rng.randint(0, 180 + 100 * level - 1)


# --- fights ----------------------------------------------------------------------------------


def _kill_bounty(victim: _Player) -> float:
    """Gold for killing ``victim``: shutdowns on streaks, reduced bounty when feeding."""
    if victim.streak >= 3:
        return 300 + min(700, 150 * (victim.streak - 2))
    if victim.death_streak >= 2:
        return max(100, 300 * (0.85 ** (victim.death_streak - 1)))
    return 300


def _simulate_fights(
    rng: random.Random,
    players: list[_Player],
    duration: float,
    winner: int,
    kills_w: int,
    kills_l: int,
) -> None:
    loser = RED if winner == BLUE else BLUE
    labels = [winner] * kills_w + [loser] * kills_l
    rng.shuffle(labels)
    fights: list[list[int]] = []
    i = 0
    while i < len(labels):
        size = _weighted(rng, _FIGHT_SIZES)
        fights.append(labels[i : i + size])
        i += size
    if not fights:
        return

    first = rng.uniform(110, 400)
    first = min(first, max(60.0, duration * 0.5))
    times = [first]
    if len(fights) > 1:
        rest = sorted(
            first + 20 + (duration - first - 40) * rng.random() ** 0.85
            for _ in range(len(fights) - 1)
        )
        times.extend(rest)
    # A fight lasts up to ~8 s per kill; the next one starts at least 15 s after it ends.
    # Required gaps are kept; the random slack between fights shrinks if the game is short.
    required = [len(fights[k - 1]) * 8.0 + 15.0 for k in range(1, len(times))]
    slack = [max(0.0, times[k] - times[k - 1] - required[k - 1]) for k in range(1, len(times))]
    available = (duration - 10) - first - sum(required)
    scale = min(1.0, available / sum(slack)) if available > 0 and sum(slack) > 0 else 0.0
    for k in range(1, len(times)):
        times[k] = times[k - 1] + required[k - 1] + slack[k - 1] * scale

    by_team = {team: [p for p in players if p.team == team] for team in (BLUE, RED)}
    first_blood_done = False
    for fight_labels, start in zip(fights, times, strict=True):
        size = len(fight_labels)
        early = start < 14 * 60
        if size == 1:
            per_side = 1 if rng.random() < 0.55 else 2
        elif size == 2:
            per_side = rng.randint(2, 3)
        else:
            per_side = rng.randint(3, 5) if not early else rng.randint(2, 4)
        fighters: dict[int, list[_Player]] = {}
        for team, members in by_team.items():
            alive = [p for p in members if p.alive(start)]
            pool = alive or members
            chosen: list[_Player] = []
            candidates = list(pool)
            for _ in range(min(per_side, len(candidates))):
                weights = [ROLE_FIGHT_W[p.role] * p.slot.aggression for p in candidates]
                idx = _pick_weighted(rng, candidates, weights)
                chosen.append(candidates.pop(idx))
            fighters[team] = chosen
        # One player sometimes takes over a big fight (where pentakills come from).
        carries: dict[int, _Player | None] = {BLUE: None, RED: None}
        for team in (BLUE, RED):
            team_kills = sum(1 for lab in fight_labels if lab == team)
            if team_kills >= 4 and fighters[team] and rng.random() < 0.06:
                carries[team] = max(fighters[team], key=lambda p: p.kill_w * rng.uniform(0.6, 1.4))

        fight_kills: dict[int, int] = {}
        t = start
        for label in fight_labels:
            t += rng.uniform(2.0, 8.0)
            if t >= duration - 1:
                break
            killing = [p for p in fighters[label] if p.alive(t)]
            if not killing:
                killing = [p for p in by_team[label] if p.alive(t)]
            enemy_team = RED if label == BLUE else BLUE
            victims = [p for p in fighters[enemy_team] if p.alive(t)]
            if not victims:
                victims = [p for p in by_team[enemy_team] if p.alive(t)]
            if not killing or not victims:
                continue
            carry = carries[label]
            if carry is not None and carry.alive(t) and rng.random() < 0.8:
                killer = carry
            else:
                # Last hits spread out within a fight: long chains (and pentas) stay rare.
                weights = [p.kill_w * 0.45 ** fight_kills.get(p.index, 0) for p in killing]
                killer = killing[_pick_weighted(rng, killing, weights)]
            victim = victims[_pick_weighted(rng, victims, [p.death_w for p in victims])]
            solo = size == 1 and len(fighters[label]) == 1
            assisters: list[_Player] = []
            if not solo:
                for p in by_team[label]:
                    if p is killer or not p.alive(t):
                        continue
                    if p in killing:
                        chance = ROLE_ASSIST_P[p.role] + (0.1 if size >= 3 else 0.0)
                    else:
                        chance = 0.08  # a teammate collapsing late on the fight
                    if rng.random() < chance:
                        assisters.append(p)
            elif rng.random() < 0.25:
                # A jungler or support arriving for the last hit on a "solo" fight.
                helpers = [p for p in by_team[label] if p.alive(t) and p is not killer]
                if helpers:
                    assisters.append(rng.choice(helpers))

            bounty = _kill_bounty(victim)
            if not first_blood_done:
                bounty += 100
                killer.first_blood_kill = True
                for a in assisters:
                    a.first_blood_assist = True
                first_blood_done = True
            killer.kill_times.append(t)
            fight_kills[killer.index] = fight_kills.get(killer.index, 0) + 1
            killer.kill_gold += bounty
            killer.streak += 1
            killer.death_streak = 0
            if not assisters:
                killer.solo_kills += 1 if solo else 0
            else:
                share = bounty * 0.5 / len(assisters)
                for a in assisters:
                    a.assists += 1
                    a.assist_gold += share
            # Victim dies.
            if victim.streak >= 2:
                victim.largest_spree = max(victim.largest_spree, victim.streak)
                victim.sprees += 1
            victim.streak = 0
            victim.death_streak += 1
            level = _level_at(victim, t, duration)
            respawn = t + _respawn_seconds(level, t)
            victim.deaths.append((t, respawn))
            victim.respawn_at = respawn

    for p in players:
        if p.streak >= 2:
            p.largest_spree = max(p.largest_spree, p.streak)
            p.sprees += 1


def _multikills(kill_times: Sequence[float]) -> tuple[int, int, int, int, int]:
    """(double, triple, quadra, penta, largest) from kill timestamps (10 s window, 30 s for
    the penta). A triple also counts as a double, as in Riot's data."""
    counts = [0, 0, 0, 0]  # double..penta
    largest = 1 if kill_times else 0
    chain = 0
    last = -1e9
    for t in sorted(kill_times):
        window = 30.0 if chain == 4 else 10.0
        chain = chain + 1 if t - last <= window else 1
        last = t
        if chain >= 2:
            level = min(chain, 5)
            if chain <= 5:
                counts[level - 2] += 1
            largest = max(largest, level)
    return counts[0], counts[1], counts[2], counts[3], largest


# --- objectives ------------------------------------------------------------------------------


@dataclass(slots=True)
class _TeamObjectives:
    towers: int = 0
    inhibitors: int = 0
    dragons: int = 0
    barons: int = 0
    heralds: int = 0
    grubs: int = 0
    atakhan: int = 0
    first: dict[str, bool] = field(default_factory=dict)


def _credit(
    rng: random.Random, members: Sequence[_Player], weights: Mapping[Role, float]
) -> _Player:
    ws = [weights[p.role] * math.exp(0.3 * p.perf) for p in members]
    return members[_pick_weighted(rng, members, ws)]


_TOWER_W: Final[dict[Role, float]] = {
    "TOP": 1.4, "JUNGLE": 0.6, "MIDDLE": 1.2, "BOTTOM": 1.5, "UTILITY": 0.45,
}  # fmt: skip
_EPIC_W: Final[dict[Role, float]] = {
    "TOP": 0.05, "JUNGLE": 0.78, "MIDDLE": 0.06, "BOTTOM": 0.08, "UTILITY": 0.03,
}  # fmt: skip


def _objectives(
    rng: random.Random,
    players: list[_Player],
    duration: float,
    winner: int,
    dominance: float,
    surrender: bool,
) -> dict[int, _TeamObjectives]:
    minutes = duration / 60
    loser = RED if winner == BLUE else BLUE
    teams = {BLUE: _TeamObjectives(), RED: _TeamObjectives()}
    members = {t: [p for p in players if p.team == t] for t in (BLUE, RED)}
    w, lo = teams[winner], teams[loser]
    p_win_obj = _clamp(0.5 + (dominance - 0.5) * 1.3 + 0.08, 0.4, 0.88)

    def side() -> int:
        return winner if rng.random() < p_win_obj else loser

    # towers / inhibitors / nexus
    if surrender:
        w.towers = rng.randint(5, 9)
        w.inhibitors = _weighted(rng, ((0, 0.35), (1, 0.45), (2, 0.2)))
    else:
        w.towers = rng.randint(8, 11)
        w.inhibitors = rng.randint(1, 3) + (1 if minutes > 35 and rng.random() < 0.3 else 0)
    comeback = dominance < 0.55
    lo.towers = min(8, rng.randint(1, 5) + (rng.randint(1, 3) if comeback else 0))
    if surrender:
        lo.towers = min(lo.towers, rng.randint(1, 4))
    lo.inhibitors = 1 if (comeback and rng.random() < 0.3) or rng.random() < 0.04 else 0
    first_tower_team = winner if rng.random() < p_win_obj else loser
    if teams[first_tower_team].towers == 0:
        first_tower_team = winner
    teams[first_tower_team].first["tower"] = True
    inhib_first = winner if lo.inhibitors == 0 or rng.random() < 0.7 else loser
    if teams[inhib_first].inhibitors > 0:
        teams[inhib_first].first["inhibitor"] = True

    # dragons (first spawn 5:00, respawn 5:00 after a kill)
    max_dragons = max(0, 1 + int((minutes - 5.5) / 5.3)) if minutes > 5.5 else 0
    n_dragons = rng.randint(max(0, max_dragons - 2), max_dragons) if max_dragons else 0
    for k in range(n_dragons):
        team = side()
        other = RED if team == BLUE else BLUE
        # Once a team has the soul (4 drakes) only elders remain; the other side can't pass 3.
        if teams[other].dragons >= 4 and teams[team].dragons >= 3:
            team = other
        teams[team].dragons += 1
        if k == 0:
            teams[team].first["dragon"] = True
    # voidgrubs: two camps of three
    grub_first: int | None = None
    if minutes > 6:
        for _camp in range(2 if minutes > 10 else 1):
            if rng.random() < 0.85:
                team = side()
                got = 3 if rng.random() < 0.75 else 2
                teams[team].grubs += got
                other = RED if team == BLUE else BLUE
                teams[other].grubs += 3 - got
                if grub_first is None:
                    grub_first = team
    if grub_first is not None:
        teams[grub_first].first["horde"] = True
    # herald (14:00) / baron and atakhan (20:00)
    if minutes > 15 and rng.random() < 0.85:
        team = side()
        teams[team].heralds = 1
        teams[team].first["riftHerald"] = True
    if minutes > 21:
        if rng.random() < 0.75:
            team = side()
            teams[team].atakhan = 1
            teams[team].first["atakhan"] = True
        barons: list[int] = []
        if not surrender or minutes > 25:
            if rng.random() < 0.7:
                barons.append(winner)
            if minutes > 32 and rng.random() < 0.3:
                barons.append(side())
            if comeback and rng.random() < 0.25:
                barons.insert(0, loser)
        for k, team in enumerate(barons):
            teams[team].barons += 1
            if k == 0:
                teams[team].first["baron"] = True

    # per-player credit
    for team_id, obj in teams.items():
        roster = members[team_id]
        for _ in range(obj.dragons):
            p = _credit(rng, roster, _EPIC_W)
            p.dragon_kills += 1
            for q in roster:
                if q is p or rng.random() < 0.55:
                    q.dragon_takedowns += 1
        for _ in range(obj.barons):
            p = _credit(rng, roster, _EPIC_W)
            p.baron_kills += 1
            for q in roster:
                if q is p or rng.random() < 0.8:
                    q.baron_takedowns += 1
        if obj.heralds:
            for q in roster:
                if q.role == "JUNGLE" or rng.random() < 0.4:
                    q.herald_takedowns += 1
        for k in range(obj.towers):
            killer: _Player | None = _credit(rng, roster, _TOWER_W) if rng.random() < 0.72 else None
            helpers = rng.sample(roster, rng.randint(1, 3))
            involved = {id(h): h for h in helpers}
            if killer is not None:
                killer.turret_kills += 1
                involved[id(killer)] = killer
            for h in involved.values():
                h.turret_takedowns += 1
            if k == 0 and obj.first.get("tower"):
                if killer is not None:
                    killer.first_tower_kill = True
                for h in involved.values():
                    if h is not killer:
                        h.first_tower_assist = True
        for _ in range(obj.inhibitors):
            killer = _credit(rng, roster, _TOWER_W) if rng.random() < 0.8 else None
            involved = {id(h): h for h in rng.sample(roster, rng.randint(1, 4))}
            if killer is not None:
                killer.inhibitor_kills += 1
                involved[id(killer)] = killer
            for h in involved.values():
                h.inhibitor_takedowns += 1
        # turret plates (fall at 14:00) for laners
        for q in roster:
            if q.role in ("TOP", "MIDDLE", "BOTTOM"):
                q.plates = rng.randint(0, 3) + (rng.randint(0, 2) if team_id == winner else 0)
            elif q.role == "UTILITY":
                q.plates = rng.randint(0, 2)
    if not surrender:
        roster = members[winner]
        closer = _credit(rng, roster, _TOWER_W)
        closer.nexus_kills = 1
        for q in roster:
            if q is closer or rng.random() < 0.7:
                q.nexus_takedowns = 1
    return teams


# --- per-player stat lines -----------------------------------------------------------------


def _items(
    rng: random.Random, p: _Player, gold_spent: int, minutes: float
) -> tuple[list[int], int]:
    """Final inventory (item0..item6) bought from ``gold_spent``; also items purchased."""
    plan = BUILDS[p.champion.build]
    budget = gold_spent - 250 - int(minutes * 12)  # consumables, wards
    slots: list[int] = []
    purchased = 2
    if p.role == "JUNGLE":
        slots.append(rng.choice(JUNGLE_PETS))
        budget -= 450
        purchased += 1
    elif p.role == "UTILITY":
        slots.append(rng.choice(SUPPORT_ITEMS))
        budget -= 400
        purchased += 1
    boots = _weighted(rng, plan.boots)
    first = rng.choice(plan.first)
    later = [i for i in plan.core if i != first]
    rng.shuffle(later)
    order = [first, boots, *later]
    for item in order:
        if len(slots) >= 6:
            break
        cost = ITEM_COST[item]
        if budget >= cost:
            slots.append(item)
            budget -= cost
            purchased += 3 if item != boots else 2
        else:
            if budget >= 250:
                affordable = [c for c in plan.components if ITEM_COST[c] <= budget]
                if affordable and len(slots) < 6:
                    comp = max(affordable, key=lambda c: (ITEM_COST[c], c))
                    slots.append(comp)
                    purchased += 1
            break
    if len(slots) < 6 and p.role in ("UTILITY", "JUNGLE") and rng.random() < 0.45:
        slots.append(CONTROL_WARD)
    # A few players keep items in odd slots; keep purchase order but rotate the boots.
    if len(slots) >= 3 and rng.random() < 0.3:
        a, b = rng.sample(range(len(slots)), 2)
        slots[a], slots[b] = slots[b], slots[a]
    while len(slots) < 6:
        slots.append(0)
    if p.role in ("UTILITY",) or (p.role == "JUNGLE" and minutes > 12 and rng.random() < 0.8):
        trinket = ORACLE_LENS
    elif p.role == "BOTTOM" and minutes > 15 and rng.random() < 0.3:
        trinket = FARSIGHT
    elif minutes > 20 and rng.random() < 0.2:
        trinket = ORACLE_LENS
    else:
        trinket = STEALTH_WARD
    return [*slots, trinket], purchased


def _perks(rng: random.Random, p: _Player) -> dict[str, Any]:
    plan = BUILDS[p.champion.build]
    style, keystone = _weighted(rng, [((s, k), wt) for s, k, wt in plan.keystones])
    rows = RUNE_ROWS[style]
    primary = [keystone] + [rng.choice(row) for row in rows]
    secondary_style = rng.choice([s for s in plan.secondary_styles if s != style])
    sec_rows = rng.sample(RUNE_ROWS[secondary_style], 2)
    secondary = [rng.choice(row) for row in sec_rows]

    def sel(perk: int) -> dict[str, int]:
        return {"perk": perk, "var1": rng.randint(0, 2500), "var2": rng.randint(0, 40), "var3": 0}

    return {
        "statPerks": {
            "defense": rng.choice(DEFENSE_SHARDS),
            "flex": rng.choice(FLEX_SHARDS),
            "offense": plan.offense_shard,
        },
        "styles": [
            {
                "description": "primaryStyle",
                "selections": [sel(x) for x in primary],
                "style": style,
            },
            {
                "description": "subStyle",
                "selections": [sel(x) for x in secondary],
                "style": secondary_style,
            },
        ],
    }


def _spells(rng: random.Random, p: _Player) -> tuple[int, int]:
    first, second = _weighted(rng, SPELLS_BY_ROLE[p.role])
    # Flash (or the first spell) on D or F per the player's habit.
    return (first, second) if p.slot.flash_on_d else (second, first)


_LANE_ROLE: Final[dict[Role, tuple[str, str]]] = {
    "TOP": ("TOP", "SOLO"),
    "JUNGLE": ("JUNGLE", "NONE"),
    "MIDDLE": ("MIDDLE", "SOLO"),
    "BOTTOM": ("BOTTOM", "CARRY"),
    "UTILITY": ("BOTTOM", "SUPPORT"),
}


def _split_damage(rng: random.Random, total: int, damage: DamageType) -> tuple[int, int, int]:
    """(physical, magic, true) summing to ``total``."""
    true_share = rng.uniform(0.02, 0.09)
    if damage == "AD":
        phys_share = rng.uniform(0.78, 0.9)
    elif damage == "AP":
        phys_share = rng.uniform(0.04, 0.14)
    else:
        phys_share = rng.uniform(0.38, 0.55)
    physical = int(total * phys_share)
    true = int(total * true_share)
    magic = total - physical - true
    if magic < 0:
        physical += magic
        magic = 0
    return physical, magic, true


def _participant(
    rng: random.Random,
    p: _Player,
    *,
    duration: int,
    surrender: bool,
    remake: bool,
    team_kills: int,
    team_objs: _TeamObjectives,
    enemy_objs: _TeamObjectives,
    elo: float,
    pace: float,
    farm: float,
) -> dict[str, Any]:
    """One participant dict. ``pace`` scales the whole game's per-minute output (a quiet or
    a frantic game) and ``farm`` how well this player's team farmed, which only loosely
    follows the result (teams farm well and still throw)."""
    slot, champ, role = p.slot, p.champion, p.role
    minutes = duration / 60
    kills = len(p.kill_times)
    deaths = len(p.deaths)
    dead_time = sum(min(respawn, duration) - died for died, respawn in p.deaths)
    alive_frac = _clamp(1 - dead_time / duration, 0.2, 1.0) if duration else 1.0
    perf = p.perf
    lost = not p.win

    # --- farm ---------------------------------------------------------------------------
    farm_minutes = max(0.0, minutes - 1.6)
    cs_rate = ROLE_CS[role] * (0.86 + 0.22 * elo) * math.exp(0.12 * perf) * rng.uniform(0.9, 1.1)
    cs_rate *= farm
    if role == "UTILITY":
        cs_rate = rng.uniform(0.4, 1.8)
    elif role == "JUNGLE":
        cs_rate = rng.uniform(0.4, 1.6)
    cs = int(cs_rate * farm_minutes * alive_frac**0.6)
    if role == "JUNGLE":
        neutral_rate = 5.8 * math.exp(0.1 * perf) * (0.9 + 0.15 * elo) * rng.uniform(0.9, 1.1)
        neutral_rate *= farm
        neutral = int(neutral_rate * max(0.0, minutes - 1.5) * alive_frac**0.5)
        neutral += p.dragon_kills + p.baron_kills + p.herald_takedowns
        enemy_jungle = int(neutral * rng.uniform(0.02, 0.15))
        ally_jungle = max(0, int((neutral - enemy_jungle) * rng.uniform(0.9, 0.98)))
    else:
        late = max(0.0, minutes - 14)
        neutral = int(late * rng.uniform(0.0, 0.45 if role != "UTILITY" else 0.1))
        neutral += p.dragon_kills + p.baron_kills
        ally_jungle = int(neutral * rng.uniform(0.5, 0.9))
        enemy_jungle = max(0, neutral - ally_jungle - p.dragon_kills - p.baron_kills)

    # --- gold ---------------------------------------------------------------------------
    passive = 500 + max(0.0, duration - 65) / 10 * 20.4
    gold = passive + cs * rng.uniform(19.5, 22.0) + neutral * rng.uniform(17.0, 21.0)
    gold += p.kill_gold + p.assist_gold
    gold += p.turret_takedowns * rng.uniform(120, 200) + team_objs.towers * 50
    gold += p.plates * rng.uniform(125, 160)
    gold += team_objs.barons * 300 * alive_frac
    if role == "UTILITY":
        gold += minutes * rng.uniform(45, 65)
    gold_earned = int(gold)
    gold_spent = max(0, gold_earned - rng.randint(80, 1300)) if not remake else gold_earned - 20
    gold_spent = max(0, min(gold_spent, gold_earned))
    gpm = gold_earned / minutes if minutes else 0.0
    gold_factor = _clamp(gpm / ROLE_GPM[role], 0.4, 2.2)

    # --- damage -------------------------------------------------------------------------
    dpm = CLASS_DPM[champ.cls] * ROLE_DPM[role]
    if role == "UTILITY" and champ.cls == "mage":
        dpm = CLASS_DPM["mage"] * 0.95
    dmg_champs = int(
        dpm * pace * minutes * gold_factor**0.7 * math.exp(0.2 * perf) * rng.uniform(0.85, 1.15)
        + 350 * kills
        + 120 * p.assists
    )
    physical, magic, true = _split_damage(rng, dmg_champs, champ.damage)
    # Poking and sieging towers that do not fall counts too, so losers still have some.
    siege = {"TOP": 110.0, "MIDDLE": 90.0, "BOTTOM": 110.0, "JUNGLE": 45.0, "UTILITY": 25.0}[role]
    turret_dmg = int(
        p.turret_takedowns * rng.uniform(900, 2600) * (0.4 if role == "UTILITY" else 1.0)
        + p.plates * rng.uniform(500, 800)
        + siege * minutes * rng.uniform(0.4, 1.6)
    )
    building_dmg = turret_dmg + int(p.inhibitor_takedowns * rng.uniform(900, 2200))
    building_dmg += int(p.nexus_takedowns * rng.uniform(600, 1800))
    epic_dmg = p.dragon_kills * rng.uniform(4500, 7500) + p.baron_kills * rng.uniform(8000, 13000)
    epic_dmg += (p.dragon_takedowns + p.baron_takedowns) * rng.uniform(900, 2500)
    epic_dmg += p.herald_takedowns * rng.uniform(1500, 4000)
    if role == "JUNGLE":
        # Contested and lost objectives still take damage.
        epic_dmg += minutes * rng.uniform(150, 450)
    objective_dmg = int(building_dmg + epic_dmg)
    minion_dmg = cs * CLASS_MINION_DMG[champ.cls] * rng.uniform(0.85, 1.15)
    monster_dmg = neutral * rng.uniform(700, 1100)
    total_dmg = int(dmg_champs + minion_dmg + monster_dmg + building_dmg)
    total_phys, total_magic, total_true = _split_damage(rng, total_dmg, champ.damage)
    # champion damage is a subset of total damage in each type
    total_phys, total_magic, total_true = (
        max(total_phys, physical),
        max(total_magic, magic),
        max(total_true, true),
    )
    total_dmg = total_phys + total_magic + total_true

    taken_rate = CLASS_TAKEN[champ.cls] * (1.15 if role == "JUNGLE" else 1.0)
    taken = int(taken_rate * minutes * rng.uniform(0.85, 1.15) * (1 + 0.04 * deaths))
    taken_phys = int(taken * rng.uniform(0.45, 0.65))
    taken_true = int(taken * rng.uniform(0.03, 0.1))
    taken_magic = taken - taken_phys - taken_true
    mitigated = int(taken * CLASS_MITIGATION[champ.cls] * rng.uniform(0.8, 1.2))

    # --- utility ------------------------------------------------------------------------
    cc = int(CLASS_CC[champ.cls] * minutes * rng.uniform(0.7, 1.3) * math.exp(0.1 * perf))
    cc_total = int(cc * rng.uniform(4, 12) + cs * rng.uniform(0.1, 0.5))
    heal_rate = CLASS_HEAL[champ.cls] + (90 if role == "JUNGLE" else 0)
    if champ.id in HEALERS:
        heal_rate += 250
    total_heal = int(heal_rate * pace * minutes * rng.uniform(0.7, 1.3))
    if champ.id in HEALERS:
        heals_on_team = int(minutes * rng.uniform(200, 420))
    elif champ.cls == "enchanter":
        heals_on_team = int(minutes * rng.uniform(30, 120))
    else:
        heals_on_team = int(minutes * rng.uniform(0, 15)) if rng.random() < 0.3 else 0
    total_heal = max(total_heal, heals_on_team)
    if champ.id in SHIELDERS:
        shields = int(minutes * rng.uniform(250, 550))
    elif champ.cls == "enchanter" or champ.build == "tank_support":
        shields = int(minutes * rng.uniform(50, 150))
    else:
        shields = int(minutes * rng.uniform(0, 30)) if rng.random() < 0.2 else 0

    # --- vision -------------------------------------------------------------------------
    vis = slot.vision * (0.85 + 0.3 * elo) * math.exp(0.15 * perf) * pace**0.5
    ward_rate = {"UTILITY": 1.08, "JUNGLE": 0.45, "TOP": 0.3, "MIDDLE": 0.33, "BOTTOM": 0.35}[role]
    wards_placed = int(ward_rate * minutes * vis * rng.uniform(0.8, 1.2))
    kill_rate = {"UTILITY": 0.33, "JUNGLE": 0.27, "TOP": 0.08, "MIDDLE": 0.1, "BOTTOM": 0.1}[role]
    wards_killed = int(kill_rate * minutes * vis * rng.uniform(0.6, 1.4))
    control_base = {"UTILITY": 8.0, "JUNGLE": 4.5, "TOP": 1.5, "MIDDLE": 1.8, "BOTTOM": 1.4}[role]
    control_bought = max(0, int(round(control_base * minutes / 30 * vis * rng.uniform(0.6, 1.4))))
    if remake:
        control_bought = min(control_bought, 1)
    detector_placed = max(0, control_bought - (1 if rng.random() < 0.3 else 0))
    vision_score = int(
        wards_placed * 1.3 + wards_killed * 1.2 + detector_placed * 1.8 + minutes * 0.12
    )

    # --- level / pings / spells -----------------------------------------------------------
    level = p.final_level
    ping_rate = rng.uniform(0.35, 1.2) * slot.pings * (1.25 if lost else 1.0)
    ping_total = int(ping_rate * minutes)
    pings = dict.fromkeys((k for k, _ in _PING_KEYS), 0)
    for _ in range(ping_total):
        pings[_weighted(rng, _PING_KEYS)] += 1
    spell1, spell2 = _spells(rng, p)
    double, triple, quadra, penta, largest_multi = _multikills(p.kill_times)
    items, purchased = _remake_items(rng, p) if remake else _items(rng, p, gold_spent, minutes)

    # --- time alive -------------------------------------------------------------------------
    longest_alive = 0.0
    alive_since = 0.0
    for died, respawn in sorted(p.deaths):
        longest_alive = max(longest_alive, died - alive_since)
        alive_since = respawn
    if not p.deaths:
        longest_alive = 0.0  # Riot reports 0 for players who never died
    else:
        longest_alive = max(longest_alive, duration - alive_since)

    lane, riot_role = _LANE_ROLE[role]
    kda = (kills + p.assists) / max(deaths, 1)
    participant: dict[str, Any] = {
        "allInPings": pings["allInPings"],
        "assistMePings": pings["assistMePings"],
        "assists": p.assists,
        "baronKills": p.baron_kills,
        "basicPings": pings["basicPings"],
        "bountyLevel": min(p.streak, 5) if p.streak >= 2 else 0,
        "champExperience": _experience_for(rng, level),
        "champLevel": level,
        "championId": champ.id,
        "championName": champ.key,
        "championTransform": 0,
        "commandPings": pings["commandPings"],
        "consumablesPurchased": rng.randint(1, 4) + control_bought,
        "damageDealtToBuildings": building_dmg,
        "damageDealtToObjectives": objective_dmg,
        "damageDealtToTurrets": turret_dmg,
        "damageSelfMitigated": mitigated,
        "deaths": deaths,
        "detectorWardsPlaced": detector_placed,
        "doubleKills": double,
        "dragonKills": p.dragon_kills,
        "eligibleForProgression": True,
        "enemyMissingPings": pings["enemyMissingPings"],
        "enemyVisionPings": pings["enemyVisionPings"],
        "firstBloodAssist": p.first_blood_assist,
        "firstBloodKill": p.first_blood_kill,
        "firstTowerAssist": p.first_tower_assist,
        "firstTowerKill": p.first_tower_kill,
        "gameEndedInEarlySurrender": remake,
        "gameEndedInSurrender": surrender,
        "getBackPings": pings["getBackPings"],
        "goldEarned": gold_earned,
        "goldSpent": gold_spent,
        "holdPings": pings["holdPings"],
        "individualPosition": role,
        "inhibitorKills": p.inhibitor_kills,
        "inhibitorTakedowns": p.inhibitor_takedowns,
        "inhibitorsLost": enemy_objs.inhibitors,
        "item0": items[0],
        "item1": items[1],
        "item2": items[2],
        "item3": items[3],
        "item4": items[4],
        "item5": items[5],
        "item6": items[6],
        "itemsPurchased": purchased,
        "killingSprees": p.sprees,
        "kills": kills,
        "lane": lane,
        "largestCriticalStrike": (
            int(rng.uniform(600, 1800)) if champ.build in ("adc_crit", "crit_melee") else 0
        ),
        "largestKillingSpree": p.largest_spree,
        "largestMultiKill": largest_multi,
        "longestTimeSpentLiving": int(longest_alive),
        "magicDamageDealt": total_magic,
        "magicDamageDealtToChampions": magic,
        "magicDamageTaken": taken_magic,
        "missions": {"playerScore0": 0, "playerScore1": 0, "playerScore2": 0},
        "needVisionPings": pings["needVisionPings"],
        "neutralMinionsKilled": neutral,
        "nexusKills": p.nexus_kills,
        "nexusLost": 1 if (not p.win and not surrender and not remake) else 0,
        "nexusTakedowns": p.nexus_takedowns,
        "objectivesStolen": p.objectives_stolen,
        "objectivesStolenAssists": 0,
        "onMyWayPings": pings["onMyWayPings"],
        "participantId": p.index + 1,
        "pentaKills": penta,
        "perks": _perks(rng, p),
        "physicalDamageDealt": total_phys,
        "physicalDamageDealtToChampions": physical,
        "physicalDamageTaken": taken_phys,
        "placement": 0,
        "playerAugment1": 0,
        "playerAugment2": 0,
        "playerAugment3": 0,
        "playerAugment4": 0,
        "playerSubteamId": 0,
        "profileIcon": slot.profile_icon_id,
        "pushPings": pings["pushPings"],
        "puuid": slot.puuid,
        "quadraKills": quadra,
        "riotIdGameName": slot.game_name,
        "riotIdTagline": slot.tag_line,
        "role": riot_role,
        "sightWardsBoughtInGame": 0,
        "spell1Casts": int(minutes * rng.uniform(4, 9)),
        "spell2Casts": int(minutes * rng.uniform(2, 6)),
        "spell3Casts": int(minutes * rng.uniform(2, 6)),
        "spell4Casts": int(minutes * rng.uniform(0.25, 0.6)),
        "subteamPlacement": 0,
        "summoner1Casts": int(minutes * rng.uniform(0.1, 0.25))
        + (int(neutral / 6) if spell1 == SMITE else 0),
        "summoner1Id": spell1,
        "summoner2Casts": int(minutes * rng.uniform(0.1, 0.25))
        + (int(neutral / 6) if spell2 == SMITE else 0),
        "summoner2Id": spell2,
        "summonerLevel": slot.summoner_level,
        "summonerName": "",
        "teamEarlySurrendered": remake and not p.win,
        "teamId": slot.team_id,
        "teamPosition": role,
        "timeCCingOthers": cc,
        "timePlayed": duration,
        "totalAllyJungleMinionsKilled": ally_jungle,
        "totalDamageDealt": total_dmg,
        "totalDamageDealtToChampions": dmg_champs,
        "totalDamageShieldedOnTeammates": shields,
        "totalDamageTaken": taken,
        "totalEnemyJungleMinionsKilled": enemy_jungle,
        "totalHeal": total_heal,
        "totalHealsOnTeammates": heals_on_team,
        "totalMinionsKilled": cs,
        "totalTimeCCDealt": cc_total,
        "totalTimeSpentDead": int(dead_time),
        "totalUnitsHealed": rng.randint(3, 9) if heals_on_team else 1,
        "tripleKills": triple,
        "trueDamageDealt": total_true,
        "trueDamageDealtToChampions": true,
        "trueDamageTaken": taken_true,
        "turretKills": p.turret_kills,
        "turretTakedowns": p.turret_takedowns,
        "turretsLost": enemy_objs.towers,
        "unrealKills": 0,
        "visionClearedPings": pings["visionClearedPings"],
        "visionScore": vision_score,
        "visionWardsBoughtInGame": control_bought,
        "wardsKilled": wards_killed,
        "wardsPlaced": wards_placed,
        "win": p.win,
        "challenges": {
            "kda": round(kda, 4),
            "killParticipation": round((kills + p.assists) / team_kills, 4) if team_kills else 0.0,
            "takedowns": kills + p.assists,
            "soloKills": p.solo_kills,
            "damagePerMinute": round(dmg_champs / minutes, 3) if minutes else 0.0,
            "goldPerMinute": round(gpm, 3),
            "visionScorePerMinute": round(vision_score / minutes, 4) if minutes else 0.0,
            "controlWardsPlaced": detector_placed,
            "wardTakedowns": wards_killed,
            "turretPlatesTaken": p.plates,
            "dragonTakedowns": p.dragon_takedowns,
            "baronTakedowns": p.baron_takedowns,
            "riftHeraldTakedowns": p.herald_takedowns,
            "effectiveHealAndShielding": float(heals_on_team + shields),
            "multikills": double,
            "firstTurretKilled": 1 if p.first_tower_kill else 0,
            "laneMinionsFirst10Minutes": (
                int(min(cs, 107) * rng.uniform(0.55, 0.8))
                if role not in ("JUNGLE", "UTILITY")
                else rng.randint(0, 8)
            ),
            "perfectGame": 1 if deaths == 0 and p.win and not remake else 0,
            "gameLength": float(duration),
        },
    }
    return participant


def _remake_items(rng: random.Random, p: _Player) -> tuple[list[int], int]:
    starter = {
        "TOP": rng.choice((1054, 1055)),
        "JUNGLE": rng.choice(JUNGLE_PETS),
        "MIDDLE": rng.choice((1056, 1055, 1082)),
        "BOTTOM": rng.choice((1055, 1083)),
        "UTILITY": WORLD_ATLAS,
    }[p.role]
    potions = HEALTH_POTION if rng.random() < 0.6 else 0
    return [starter, potions, 0, 0, 0, 0, STEALTH_WARD], 2 if potions else 1


# --- teams -----------------------------------------------------------------------------------


def _team_dict(
    team_id: int,
    win: bool,
    objs: _TeamObjectives,
    kills: int,
    first_blood: bool,
    bans: Sequence[int],
    epic_first: bool,
) -> dict[str, Any]:
    def obj(name: str, kills_: int) -> dict[str, Any]:
        return {"first": bool(objs.first.get(name)), "kills": kills_}

    pick_offset = 0 if team_id == BLUE else 5
    return {
        "bans": [
            {"championId": champ, "pickTurn": pick_offset + i + 1} for i, champ in enumerate(bans)
        ],
        "feats": {
            "EPIC_MONSTER_KILL": {"featState": 1 if epic_first else 0},
            "FIRST_BLOOD": {"featState": 1 if first_blood else 0},
            "FIRST_TURRET": {"featState": 1 if objs.first.get("tower") else 0},
        },
        "objectives": {
            "atakhan": obj("atakhan", objs.atakhan),
            "baron": obj("baron", objs.barons),
            "champion": {"first": first_blood, "kills": kills},
            "dragon": obj("dragon", objs.dragons),
            "horde": obj("horde", objs.grubs),
            "inhibitor": obj("inhibitor", objs.inhibitors),
            "riftHerald": obj("riftHerald", objs.heralds),
            "tower": obj("tower", objs.towers),
        },
        "teamId": team_id,
        "win": win,
    }


def _bans(rng: random.Random, picked: set[int]) -> tuple[list[int], list[int]]:
    pool = [c.id for c in CHAMPIONS if c.id not in picked]
    chosen = rng.sample(pool, 10)
    bans = [(-1 if rng.random() < 0.04 else c) for c in chosen]
    return bans[:5], bans[5:]


def validate_plan(plan: MatchPlan) -> None:
    """Raise ValueError when ``plan`` cannot describe a real Summoner's Rift game."""
    if len(plan.slots) != 10:
        raise ValueError("a match needs 10 slots")
    for team in (BLUE, RED):
        roles = sorted(s.role for s in plan.slots if s.team_id == team)
        if roles != sorted(ROLES):
            raise ValueError(f"team {team} must have one player per role, got {roles}")
    puuids = [s.puuid for s in plan.slots]
    if len(set(puuids)) != 10:
        raise ValueError("duplicate puuid in plan")
    champs = [s.champion_id for s in plan.slots]
    if len(set(champs)) != 10:
        raise ValueError("duplicate champion in plan")
    unknown = [c for c in champs if c not in CHAMPIONS_BY_ID]
    if unknown:
        raise ValueError(f"unknown champion ids {unknown}")
    if plan.winning_team not in (BLUE, RED):
        raise ValueError("winning_team must be 100 or 200")
    if plan.duration_s <= 0:
        raise ValueError("duration must be positive")


def generate_match(plan: MatchPlan, rng: random.Random) -> dict[str, Any]:
    """Simulate ``plan`` and return a complete match-v5 payload."""
    validate_plan(plan)
    duration = plan.duration_s
    minutes = duration / 60
    winner = plan.winning_team
    remake = plan.remake

    # Blue slots first, each team ordered TOP..UTILITY (participantId order, as Riot does).
    ordered = sorted(plan.slots, key=lambda s: (s.team_id, ROLES.index(s.role)))
    players: list[_Player] = []
    for index, slot in enumerate(ordered):
        champ = CHAMPIONS_BY_ID[slot.champion_id]
        win = slot.team_id == winner
        perf = 0.35 * slot.skill + rng.gauss(0.0, 0.45) + (0.07 if win else -0.07)
        final_level = (
            rng.randint(2, 4) if remake else _final_level(rng, slot.role, minutes, win, perf)
        )
        kill_w = (
            ROLE_KILL_W[slot.role] * CLASS_KILL[champ.cls] * math.exp(0.55 * perf) * slot.aggression
        )
        death_w = (
            ROLE_DEATH_W[slot.role]
            * CLASS_DEATH[champ.cls]
            * math.exp(-0.45 * perf)
            * slot.aggression**0.8
        )
        players.append(
            _Player(
                index=index,
                slot=slot,
                champion=champ,
                win=win,
                perf=perf,
                final_level=final_level,
                kill_w=kill_w,
                death_w=death_w,
            )
        )

    surrender = False
    if remake:
        dominance = 0.5
        kills_w = rng.choice((0, 0, 0, 1))
        kills_l = rng.choice((0, 0, 1))
    else:
        surrender = (minutes < 27 and rng.random() < 0.8) or (minutes < 33 and rng.random() < 0.2)
        dominance = _clamp(rng.gauss(0.6 + (27 - minutes) * 0.012, 0.1), 0.35, 0.86)
        rate = rng.uniform(1.0, 1.7) * (1.12 - 0.3 * plan.lobby_elo)
        total_kills = max(6, round(rate * minutes))
        kills_w = round(total_kills * dominance)
        kills_l = total_kills - kills_w
    _simulate_fights(rng, players, duration, winner, kills_w, kills_l)
    if remake:
        teams = {BLUE: _TeamObjectives(), RED: _TeamObjectives()}
    else:
        teams = _objectives(rng, players, duration, winner, dominance, surrender)
        for p in players:
            if p.role == "JUNGLE" and rng.random() < 0.03:
                p.objectives_stolen = 1

    team_kills = {t: sum(len(p.kill_times) for p in players if p.team == t) for t in (BLUE, RED)}
    elo = _clamp(plan.lobby_elo, 0.0, 1.0)
    pace = _clamp(rng.gauss(1.0, 0.12), 0.7, 1.35)
    farm = {
        team: _clamp(rng.gauss(1.0 + (0.025 if team == winner else -0.025), 0.07), 0.8, 1.2)
        for team in (BLUE, RED)
    }
    participants = [
        _participant(
            rng,
            p,
            duration=duration,
            surrender=surrender,
            remake=remake,
            team_kills=team_kills[p.team],
            team_objs=teams[p.team],
            enemy_objs=teams[RED if p.team == BLUE else BLUE],
            elo=elo,
            pace=pace,
            farm=farm[p.team],
        )
        for p in players
    ]
    # Team shares need every stat line first.
    for team in (BLUE, RED):
        mine = [x for x in participants if x["teamId"] == team]
        dmg = sum(x["totalDamageDealtToChampions"] for x in mine) or 1
        taken = sum(x["totalDamageTaken"] for x in mine) or 1
        for x in mine:
            x["challenges"]["teamDamagePercentage"] = round(
                x["totalDamageDealtToChampions"] / dmg, 4
            )
            x["challenges"]["damageTakenOnTeamPercentage"] = round(x["totalDamageTaken"] / taken, 4)

    first_blood_team: int | None = None
    first_kill_time = math.inf
    for p in players:
        if p.first_blood_kill and p.kill_times and p.kill_times[0] < first_kill_time:
            first_kill_time = p.kill_times[0]
            first_blood_team = p.team
    epic = {t: teams[t].dragons + teams[t].barons + teams[t].heralds for t in (BLUE, RED)}
    epic_first_team: int | None = None
    if any(epic.values()):
        epic_first_team = max((BLUE, RED), key=lambda t: (epic[t], t == winner))
    blue_bans, red_bans = _bans(rng, {s.champion_id for s in plan.slots})

    start_ms = int(plan.start.timestamp() * 1000) + rng.randint(0, 999)
    created_ms = start_ms - rng.randint(25_000, 95_000)
    end_ms = start_ms + duration * 1000 + rng.randint(200, 2500)
    info: dict[str, Any] = {
        "endOfGameResult": REMAKE_RESULT if remake else "GameComplete",
        "gameCreation": created_ms,
        "gameDuration": duration,
        "gameEndTimestamp": end_ms,
        "gameId": plan.game_id,
        "gameMode": "CLASSIC",
        "gameName": f"teambuilder-match-{plan.game_id}",
        "gameStartTimestamp": start_ms,
        "gameType": "MATCHED_GAME",
        "gameVersion": game_version_for(plan.start),
        "mapId": 11,
        "participants": participants,
        "platformId": plan.platform_id,
        "queueId": plan.queue_id,
        "teams": [
            _team_dict(
                team,
                team == winner,
                teams[team],
                team_kills[team],
                first_blood_team == team,
                blue_bans if team == BLUE else red_bans,
                epic_first_team == team,
            )
            for team in (BLUE, RED)
        ],
        "tournamentCode": "",
    }
    return {
        "metadata": {
            "dataVersion": "2",
            "matchId": plan.match_id,
            "participants": [x["puuid"] for x in participants],
        },
        "info": info,
    }


def match_end(plan: MatchPlan) -> datetime:
    """When the planned game ends (start + duration)."""
    return plan.start + timedelta(seconds=plan.duration_s)
