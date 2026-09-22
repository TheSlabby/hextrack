import pytest

from hextrack.riotid import (
    InvalidRiotId,
    RiotId,
    casefold_name,
    format_riot_id,
    parse_any,
    parse_riot_id,
    parse_slug,
    riot_id_key,
    to_slug,
)


def test_parse_riot_id_basic():
    assert parse_riot_id("Hex Walker#NA1") == RiotId("Hex Walker", "NA1")
    assert parse_riot_id("  spaced   out  # tag ") == RiotId("spaced out", "tag")


def test_parse_riot_id_unicode():
    rid = parse_riot_id("Déjà Vu#EUW")
    assert rid.game_name == "Déjà Vu" and rid.tag_line == "EUW"


@pytest.mark.parametrize("bad", ["NoTag", "#NA1", "Name#", "Name#TOOLONG", "Name#A", ""])
def test_parse_riot_id_invalid(bad):
    with pytest.raises(InvalidRiotId):
        parse_riot_id(bad)


def test_parse_slug_splits_on_last_dash():
    assert parse_slug("Game-Name-TAG") == RiotId("Game-Name", "TAG")
    assert parse_slug("Hex Walker-NA1") == RiotId("Hex Walker", "NA1")
    assert parse_slug("a-b-c-1234") == RiotId("a-b-c", "1234")


@pytest.mark.parametrize("bad", ["NoDash", "-NA1", "Name-", "Name-TOOLONG"])
def test_parse_slug_invalid(bad):
    with pytest.raises(InvalidRiotId):
        parse_slug(bad)


def test_slug_round_trip():
    for name, tag in [("Game-Name", "TAG"), ("Hex Walker", "NA1"), ("x-", "EUW")]:
        rid = parse_slug(to_slug(name, tag))
        assert (rid.game_name, rid.tag_line) == (name, tag)
    assert RiotId("A B", "NA1").slug == "A B-NA1"
    assert str(RiotId("A B", "NA1")) == "A B#NA1"


def test_parse_any():
    assert parse_any("A-B#NA1") == RiotId("A-B", "NA1")
    assert parse_any("A-B-NA1") == RiotId("A-B", "NA1")


def test_casefold_helpers():
    assert casefold_name("  HeX   WALKER ") == "hex walker"
    assert riot_id_key("Hex Walker", "na1") == riot_id_key("hex walker", "NA1")
    assert riot_id_key("Straße", "EUW") == riot_id_key("STRASSE", "euw")
    assert format_riot_id(" Hex  Walker ", "#NA1") == "Hex Walker#NA1"
    assert parse_riot_id("Hex Walker#NA1").key == ("hex walker", "na1")
