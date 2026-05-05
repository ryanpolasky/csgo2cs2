import pytest

from csgo2cs2.utils.url import parse_workshop_id, workshop_url


@pytest.mark.parametrize(
    "given, expected",
    [
        ("123456789", "123456789"),
        ("https://steamcommunity.com/sharedfiles/filedetails/?id=123456789", "123456789"),
        ("https://steamcommunity.com/workshop/filedetails/?id=987654321", "987654321"),
        (
            "https://steamcommunity.com/sharedfiles/filedetails/?id=42&searchtext=foo",
            "42",
        ),
        (
            "https://steamcommunity.com/sharedfiles/filedetails/?searchtext=foo&id=42",
            "42",
        ),
        ("steam://url/CommunityFilePage/55", "55"),
        ("  https://steamcommunity.com/sharedfiles/filedetails/?id=7  ", "7"),
    ],
)
def test_parse_workshop_id_valid(given, expected):
    assert parse_workshop_id(given) == expected


@pytest.mark.parametrize(
    "given",
    [
        "",
        "   ",
        "https://steamcommunity.com/",
        "not a url",
        "https://example.com/?id=abc",
    ],
)
def test_parse_workshop_id_invalid(given):
    assert parse_workshop_id(given) is None


def test_workshop_url_round_trip():
    wid = "123456789"
    url = workshop_url(wid)
    assert parse_workshop_id(url) == wid
