# tests for vmf fixers.

import csgo2cs2.fixers  # noqa: F401  (registers fixers)
from csgo2cs2.analyzers.vmf import analyze_vmf
from csgo2cs2.fixers.base import apply_all
from csgo2cs2.fixers.entities import remove_unsupported_entity
from csgo2cs2.fixers.skybox import fix_skybox


def _wrap_world(sky: str) -> str:
    return (
        "world\n{\n"
        "\t\"id\" \"1\"\n"
        "\t\"classname\" \"worldspawn\"\n"
        f"\t\"skyname\" \"{sky}\"\n"
        "}\n"
    )


def test_skybox_fixer_replaces_value():
    text = _wrap_world("sky_csgo_old")
    a = analyze_vmf(text, default_skybox="sky_day01_01")
    sky_finding = next(f for f in a.findings if f.issue_id == "skybox_unknown")
    new_text, applied, detail = fix_skybox(text, sky_finding)
    assert applied
    assert "sky_day01_01" in new_text
    assert "sky_csgo_old" not in new_text
    assert "sky_day01_01" in detail


def test_skybox_fixer_no_op_when_no_skyname():
    text = "world\n{\n\t\"classname\" \"worldspawn\"\n}\n"
    a = analyze_vmf(text)
    # analyzer reports skybox_missing, which is not fixable
    # direct fixer calls without a skyname should bail out cleanly
    from csgo2cs2.analyzers.vmf import Finding
    fake_finding = Finding(
        issue_id="skybox_unknown",
        severity="warn",
        message="forced",
        fixable=True,
        context={"current": "x", "replacement": "sky_day01_01"},
    )
    new_text, applied, detail = fix_skybox(text, fake_finding)
    assert applied is False
    assert new_text == text


def test_entity_fixer_removes_block():
    text = (
        _wrap_world("sky_day01_01")
        + "entity\n{\n\t\"id\" \"10\"\n\t\"classname\" \"env_cascade_light\"\n}\n"
        + "entity\n{\n\t\"id\" \"11\"\n\t\"classname\" \"info_player_terrorist\"\n}\n"
    )
    a = analyze_vmf(text)
    cascade_finding = next(
        f for f in a.findings
        if f.issue_id == "entity_unsupported"
        and f.context.get("classname") == "env_cascade_light"
    )
    new_text, applied, detail = remove_unsupported_entity(text, cascade_finding)
    assert applied
    assert "env_cascade_light" not in new_text
    assert "info_player_terrorist" in new_text


def test_apply_all_chains_fixers():
    text = (
        _wrap_world("sky_csgo_old")
        + "entity\n{\n\t\"id\" \"10\"\n\t\"classname\" \"env_cascade_light\"\n}\n"
    )
    a = analyze_vmf(text, default_skybox="sky_day01_01")
    new_text, results = apply_all(text, a.findings)
    applied_ids = {r.issue_id for r in results if r.applied}
    assert "skybox_unknown" in applied_ids
    assert "entity_unsupported" in applied_ids
    assert "sky_day01_01" in new_text
    assert "env_cascade_light" not in new_text
