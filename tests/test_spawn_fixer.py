# tests for the opt-in --fix-spawns ct|t spawn rewriter.

from __future__ import annotations

import pytest

from csgo2cs2.fixers.spawns import (
    SIDE_CT,
    SIDE_T,
    fix_legacy_spawns,
)


def _entity(classname: str) -> str:
    return "entity\n{\n" f'\t"classname" "{classname}"\n' '\t"origin" "0 0 0"\n' "}\n"


def test_no_spawns_returns_text_unchanged():
    text = _entity("info_player_terrorist")
    new, n, summary = fix_legacy_spawns(text, "t")
    assert new == text
    assert n == 0
    assert "no legacy spawn entities" in summary


def test_legacy_axis_to_ct():
    text = _entity("info_player_axis") + _entity("info_player_axis")
    new, n, summary = fix_legacy_spawns(text, "ct")
    assert n == 2
    assert SIDE_CT in new
    assert "info_player_axis" not in new
    assert "info_player_axis x2" in summary


def test_legacy_allies_to_t():
    text = _entity("info_player_allies")
    new, n, _ = fix_legacy_spawns(text, "t")
    assert n == 1
    assert SIDE_T in new


def test_legacy_player_start_to_ct():
    text = _entity("info_player_start")
    new, n, _ = fix_legacy_spawns(text, "ct")
    assert n == 1
    assert SIDE_CT in new


def test_long_form_side_aliases():
    text = _entity("info_player_axis")
    for alias in ("counter", "counterterrorist", "Counter"):
        new, n, _ = fix_legacy_spawns(text, alias)
        assert n == 1
        assert SIDE_CT in new


def test_unknown_side_raises_value_error():
    with pytest.raises(ValueError, match="unknown spawn side"):
        fix_legacy_spawns(_entity("info_player_axis"), "spectator")


def test_does_not_touch_non_legacy_classnames():
    text = _entity("logic_relay") + _entity("info_player_terrorist")
    new, n, _ = fix_legacy_spawns(text, "ct")
    assert n == 0
    assert new == text


def test_does_not_touch_substring_classname_keys():
    # custom kvs that happen to contain "classname" must not be rewritten
    text = "entity\n{\n" '\t"_classname" "info_player_axis"\n' '\t"classname" "logic_relay"\n' "}\n"
    new, n, _ = fix_legacy_spawns(text, "ct")
    assert n == 0
    # custom underscore key untouched
    assert '"_classname" "info_player_axis"' in new
