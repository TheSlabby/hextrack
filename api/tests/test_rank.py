import pytest

from hextrack.rank import (
    DIVISION_ORDER,
    MASTER_BASE,
    RANKED_FLEX_SR,
    TIER_ORDER,
    RANKED_SOLO_5x5,
    compare_tiers,
    display_rank,
    is_apex,
    rank_value,
    tier_index,
)


def test_orders():
    assert TIER_ORDER[0] == "IRON" and TIER_ORDER[-1] == "CHALLENGER"
    assert len(TIER_ORDER) == 10
    assert DIVISION_ORDER == ("IV", "III", "II", "I")
    assert RANKED_SOLO_5x5 == "RANKED_SOLO_5x5" and RANKED_FLEX_SR == "RANKED_FLEX_SR"


@pytest.mark.parametrize(
    ("tier", "rank", "lp", "expected"),
    [
        ("IRON", "IV", 0, 0),
        ("IRON", "IV", 57, 57),
        ("IRON", "III", 0, 100),
        ("IRON", "I", 99, 399),
        ("BRONZE", "IV", 0, 400),
        ("GOLD", "II", 45, 3 * 400 + 200 + 45),
        ("EMERALD", "I", 100, 5 * 400 + 300 + 100),
        ("DIAMOND", "I", 99, 2799),
        ("MASTER", None, 0, 2800),
        ("MASTER", "I", 150, 2950),  # Riot sends "I" for apex tiers; ignored
        ("GRANDMASTER", None, 400, 3200),
        ("CHALLENGER", None, 1200, 4000),
        ("gold", "ii", 0, 1400),
    ],
)
def test_rank_value(tier, rank, lp, expected):
    assert rank_value(tier, rank, lp) == expected


def test_rank_value_is_monotonic_across_boundaries():
    values = []
    for tier in TIER_ORDER[:7]:
        for division in DIVISION_ORDER:
            values.append(rank_value(tier, division, 0))
    assert values == sorted(values) and len(set(values)) == len(values)
    assert rank_value("DIAMOND", "I", 99) < rank_value("MASTER", None, 0) == MASTER_BASE


def test_rank_value_errors():
    with pytest.raises(ValueError):
        rank_value("WOOD", "IV", 0)
    with pytest.raises(ValueError):
        rank_value("GOLD", None, 10)
    with pytest.raises(ValueError):
        rank_value("GOLD", "V", 10)


def test_tier_helpers():
    assert tier_index("IRON") == 0
    assert tier_index("challenger") == 9
    assert compare_tiers("GOLD", "SILVER") == 1
    assert compare_tiers("GOLD", "GOLD") == 0
    assert compare_tiers("MASTER", "GRANDMASTER") == -1
    assert is_apex("MASTER") and not is_apex("DIAMOND")


def test_display_rank():
    assert display_rank(None) == "Unranked"
    assert display_rank("GOLD", "II", 45) == "Gold II 45 LP"
    assert display_rank("MASTER", "I", 120) == "Master 120 LP"
    assert display_rank("GRANDMASTER", None) == "Grandmaster"
    assert display_rank("EMERALD", "IV") == "Emerald IV"
