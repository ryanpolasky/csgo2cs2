# tests for the vmf_missing_top_level_keys analyzer + fixer.

from __future__ import annotations

import csgo2cs2.fixers  # noqa: F401  (registers fixers on import)
from csgo2cs2.analyzers.vmf import Finding, analyze_vmf
from csgo2cs2.fixers.base import get
from csgo2cs2.fixers.vmf_top_level import (
    REQUIRED_TOP_LEVEL_BLOCKS,
    fix_vmf_missing_top_level_keys,
)


def _findings_by_id(text: str, issue_id: str) -> list[Finding]:
    return [f for f in analyze_vmf(text).findings if f.issue_id == issue_id]


# the test_port_01 / recoil_master shape that BSPSource emits: world +
# entities, no viewsettings. analyzer should flag it.
_MISSING_VIEWSETTINGS = """\
versioninfo
{
\t"editorversion" "400"
}
visgroups
{
}
world
{
\t"id" "1"
\t"classname" "worldspawn"
}
entity
{
\t"id" "10"
\t"classname" "info_player_terrorist"
}
"""

# the fully-populated shape Hammer writes. analyzer should be silent on this.
_COMPLETE = (
    _MISSING_VIEWSETTINGS.replace(
        "visgroups\n{\n}\n",
        "visgroups\n{\n}\nviewsettings\n{\n\t\"bSnapToGrid\" \"1\"\n}\n",
    )
)


def test_complete_vmf_emits_no_top_level_finding():
    assert _findings_by_id(_COMPLETE, "vmf_missing_top_level_keys") == []


def test_missing_viewsettings_is_flagged():
    findings = _findings_by_id(_MISSING_VIEWSETTINGS, "vmf_missing_top_level_keys")
    assert len(findings) == 1
    assert findings[0].fixable is True
    assert "viewsettings" in findings[0].context["missing"]
    assert "versioninfo" not in findings[0].context["missing"]


def test_missing_multiple_blocks_lists_all():
    # raw world+entities, nothing else (worst-case BSPSource output)
    raw = """\
world
{
\t"id" "1"
\t"classname" "worldspawn"
}
entity
{
\t"id" "10"
\t"classname" "info_player_terrorist"
}
"""
    findings = _findings_by_id(raw, "vmf_missing_top_level_keys")
    assert len(findings) == 1
    missing = findings[0].context["missing"]
    assert set(missing) == set(REQUIRED_TOP_LEVEL_BLOCKS)


def test_fixer_adds_missing_block_before_world():
    finding = Finding(
        issue_id="vmf_missing_top_level_keys",
        severity="error",
        message="",
        fixable=True,
        context={"missing": ["viewsettings"]},
    )
    new_text, applied, detail = fix_vmf_missing_top_level_keys(
        _MISSING_VIEWSETTINGS, finding
    )
    assert applied is True
    assert "viewsettings" in new_text
    # inserted before world, not after
    assert new_text.index("viewsettings\n{") < new_text.index("world\n{")
    # original content preserved
    assert "info_player_terrorist" in new_text
    assert "added missing top-level block(s): viewsettings" in detail


def test_fixer_is_registered():
    assert get("vmf_missing_top_level_keys") is fix_vmf_missing_top_level_keys


def test_fixer_no_op_when_nothing_missing():
    finding = Finding(
        issue_id="vmf_missing_top_level_keys",
        severity="error",
        message="",
        fixable=True,
        context={"missing": []},
    )
    new_text, applied, _ = fix_vmf_missing_top_level_keys(_COMPLETE, finding)
    assert applied is False
    assert new_text == _COMPLETE


def test_analyze_then_fix_roundtrip_yields_compliant_vmf():
    """End-to-end: analyzer flags missing keys, fixer applies, second
    analyzer pass on the patched text emits no missing-keys finding."""
    findings = _findings_by_id(_MISSING_VIEWSETTINGS, "vmf_missing_top_level_keys")
    assert len(findings) == 1
    patched, applied, _ = fix_vmf_missing_top_level_keys(
        _MISSING_VIEWSETTINGS, findings[0]
    )
    assert applied is True
    assert _findings_by_id(patched, "vmf_missing_top_level_keys") == []


def test_nested_viewsettings_key_does_not_count():
    """An entity with a key literally named 'viewsettings' must not
    suppress the top-level finding -- the regex is column-0 anchored."""
    raw = """\
versioninfo
{
}
visgroups
{
}
world
{
\t"id" "1"
\t"classname" "worldspawn"
}
entity
{
\t"id" "10"
\t"classname" "func_brush"
\t"viewsettings" "0"
}
"""
    findings = _findings_by_id(raw, "vmf_missing_top_level_keys")
    assert len(findings) == 1
    assert "viewsettings" in findings[0].context["missing"]

