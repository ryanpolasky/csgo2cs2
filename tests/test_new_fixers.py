# tests for the PR4 fixers: backslash paths, deprecated_s2 removal, light_env dedupe.

from __future__ import annotations

from csgo2cs2.analyzers.vmf import analyze_vmf
from csgo2cs2.fixers import apply_all


def _vmf(extra: str = "") -> str:
    # sky_day01_01 is in KNOWN_CS2_SKIES so it doesn't trip skybox_unknown,
    # leaving us with a "clean" baseline for testing the new fixers.
    return (
        "world\n{\n"
        '\t"classname" "worldspawn"\n'
        '\t"skyname" "sky_day01_01"\n'
        "}\n"
        'entity { "classname" "info_player_terrorist" }\n'
        'entity { "classname" "info_player_counterterrorist" }\n' + extra
    )


# --- asset_path_backslash --------------------------------------------------


def test_fixer_backslash_rewrites_quoted_path():
    # raw string: the .vmf literal contains single backslashes between
    # path segments, e.g. `"material" "models\foo\bar"`.
    extra = (
        "entity\n{\n"
        '\t"id" "10"\n'
        '\t"classname" "func_brush"\n'
        '\t"material" "models\\foo\\bar"\n'
        "}\n"
    )
    text = _vmf(extra)
    a = analyze_vmf(text)
    findings = [f for f in a.findings if f.issue_id == "asset_path_backslash"]
    assert findings and findings[0].fixable

    new_text, results = apply_all(text, a.findings)
    applied = [r for r in results if r.applied and r.issue_id == "asset_path_backslash"]
    assert len(applied) == 1
    # the rewritten value should be present, the old value gone
    assert '"models/foo/bar"' in new_text
    assert "models\\foo\\bar" not in new_text


def test_fixer_backslash_idempotent_on_clean_vmf():
    text = _vmf()
    a = analyze_vmf(text)
    new_text, results = apply_all(text, a.findings)
    # no backslash finding, so no apply
    assert not any(r.applied and r.issue_id == "asset_path_backslash" for r in results)
    assert new_text == text


# --- entity_deprecated_s2 --------------------------------------------------


def test_fixer_deprecated_s2_removes_block():
    extra = "entity\n{\n" '\t"id" "11"\n' '\t"classname" "func_areaportal"\n' "}\n"
    text = _vmf(extra)
    a = analyze_vmf(text)
    deprecated = [f for f in a.findings if f.issue_id == "entity_deprecated_s2"]
    assert deprecated and deprecated[0].fixable

    new_text, results = apply_all(text, a.findings)
    applied = [r for r in results if r.applied and r.issue_id == "entity_deprecated_s2"]
    assert len(applied) == 1
    assert "func_areaportal" not in new_text


# --- light_environment_count -----------------------------------------------


def test_fixer_dedupe_light_environment_keeps_first():
    extra = (
        "entity\n{\n"
        '\t"id" "20"\n'
        '\t"classname" "light_environment"\n'
        '\t"_light" "255 255 255 200"\n'
        "}\n"
        "entity\n{\n"
        '\t"id" "21"\n'
        '\t"classname" "light_environment"\n'
        '\t"_light" "100 100 100 50"\n'
        "}\n"
        "entity\n{\n"
        '\t"id" "22"\n'
        '\t"classname" "light_environment"\n'
        '\t"_light" "0 0 0 0"\n'
        "}\n"
    )
    text = _vmf(extra)
    a = analyze_vmf(text)
    le = [f for f in a.findings if f.issue_id == "light_environment_count"]
    assert le and le[0].fixable
    assert le[0].context["count"] == 3

    new_text, results = apply_all(text, a.findings)
    applied = [r for r in results if r.applied and r.issue_id == "light_environment_count"]
    assert len(applied) == 1
    # only the first (`200`) should survive
    assert new_text.count('"classname" "light_environment"') == 1
    assert '"255 255 255 200"' in new_text
    assert '"100 100 100 50"' not in new_text
    assert '"0 0 0 0"' not in new_text


def test_fixer_dedupe_light_environment_noop_with_one():
    extra = (
        "entity\n{\n"
        '\t"id" "30"\n'
        '\t"classname" "light_environment"\n'
        '\t"_light" "255 255 255 200"\n'
        "}\n"
    )
    text = _vmf(extra)
    a = analyze_vmf(text)
    # finding shouldn't fire with only one
    assert not any(f.issue_id == "light_environment_count" for f in a.findings)


def test_fixer_dedupe_after_analyze_findings_no_more_dupes():
    """Round-trip: after fixer runs, re-analyzing should report no dupe finding."""
    extra = (
        'entity { "classname" "light_environment" }\n'
        'entity { "classname" "light_environment" }\n'
    )
    text = _vmf(extra)
    a = analyze_vmf(text)
    new_text, _ = apply_all(text, a.findings)
    a2 = analyze_vmf(new_text)
    assert not any(f.issue_id == "light_environment_count" for f in a2.findings)
