# Tests for the csgo_blacklisted_materials analyzer finding + fixer.
#
# Source1import has a hardcoded "Removing blacklisted file from import"
# list. Any .vmf brush side that references one of those materials
# silently drops the .vmat conversion, leading to missing-texture
# warnings + checkerboard renders in CS2. The fixer rewrites the
# `"material" "<path>"` value to a CS2 stock equivalent at .vmf-time so
# the brush renders sensibly.

from __future__ import annotations

from csgo2cs2.analyzers.vmf import (
    CSGO_BLACKLISTED_MATERIALS,
    Finding,
    _find_blacklisted_material_refs,
    _norm_mat,
    analyze_vmf,
)
from csgo2cs2.fixers import apply_all  # registers fixers
from csgo2cs2.fixers.blacklisted_materials import fix_csgo_blacklisted_materials


def _wrap_world_with_brush(material: str) -> str:
    return (
        "world\n{\n"
        '\t"id" "1"\n'
        '\t"classname" "worldspawn"\n'
        '\t"skyname" "sky_cs_office"\n'
        "\tsolid\n\t{\n"
        '\t\t"id" "2"\n'
        "\t\tside\n\t\t{\n"
        '\t\t\t"id" "3"\n'
        f'\t\t\t"material" "{material}"\n'
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )


def test_norm_mat_strips_extension_and_prefix():
    assert _norm_mat("materials/dev/dev_hazzardstripe01a.vmt") == "dev/dev_hazzardstripe01a"
    assert _norm_mat("DEV/DEV_HAZZARDSTRIPE01A") == "dev/dev_hazzardstripe01a"
    assert _norm_mat("dev\\dev_hazzardstripe01a") == "dev/dev_hazzardstripe01a"


def test_blacklist_known_materials():
    # all 4 entries in the source1import blacklist round-trip cleanly
    expected = {
        "dev/dev_hazzardstripe01a",
        "dev/reflectivity_90b",
        "editor/gray",
        "tools/locked",
    }
    assert set(CSGO_BLACKLISTED_MATERIALS.keys()) == expected
    # every substitute material is a real, stable cs2 stock path
    for replacement in CSGO_BLACKLISTED_MATERIALS.values():
        assert replacement.startswith(("dev/", "tools/"))


def test_find_blacklisted_material_refs():
    text = (
        'side { "material" "dev/dev_hazzardstripe01a" }\n'
        'side { "material" "metal/some_safe_material" }\n'
        'side { "material" "TOOLS/LOCKED" }\n'  # case-insensitive match
        'side { "material" "editor/gray.vmt" }\n'  # with extension
    )
    hits = _find_blacklisted_material_refs(text)
    # 3 of the 4 hit; the safe metal material is excluded
    assert len(hits) == 3
    assert "dev/dev_hazzardstripe01a" in hits
    assert "TOOLS/LOCKED" in hits
    assert "editor/gray.vmt" in hits


def test_analyze_vmf_emits_blacklisted_finding():
    text = _wrap_world_with_brush("dev/dev_hazzardstripe01a")
    a = analyze_vmf(text)
    bl = [f for f in a.findings if f.issue_id == "csgo_blacklisted_materials"]
    assert len(bl) == 1
    assert bl[0].fixable is True
    assert "dev/dev_hazzardstripe01a" in bl[0].context["refs"]


def test_fixer_substitutes_brush_ref():
    text = _wrap_world_with_brush("dev/dev_hazzardstripe01a")
    finding = Finding(
        issue_id="csgo_blacklisted_materials",
        severity="warn",
        message="",
        fixable=True,
        context={"refs": ["dev/dev_hazzardstripe01a"]},
    )
    new_text, applied, detail = fix_csgo_blacklisted_materials(text, finding)
    assert applied is True
    assert "dev/dev_measuregeneric01b" in new_text
    assert "dev/dev_hazzardstripe01a" not in new_text
    assert "1 ref(s)" in detail


def test_fixer_case_insensitive_match():
    # bspsource sometimes emits "Material" with a capital M. Ensure we
    # still substitute.
    text = _wrap_world_with_brush("dev/dev_hazzardstripe01a").replace(
        '"material"', '"Material"'
    )
    finding = Finding(
        issue_id="csgo_blacklisted_materials",
        severity="warn",
        message="",
        fixable=True,
        context={"refs": ["dev/dev_hazzardstripe01a"]},
    )
    new_text, applied, _detail = fix_csgo_blacklisted_materials(text, finding)
    assert applied is True
    assert "dev/dev_measuregeneric01b" in new_text


def test_fixer_propagates_through_apply_all():
    # end-to-end: analyze_vmf -> apply_all -> substituted vmf body
    text = _wrap_world_with_brush("dev/dev_hazzardstripe01a")
    a = analyze_vmf(text)
    new_text, results = apply_all(text, a.findings)
    applied_ids = {r.issue_id for r in results if r.applied}
    assert "csgo_blacklisted_materials" in applied_ids
    assert "dev/dev_measuregeneric01b" in new_text
    assert "dev/dev_hazzardstripe01a" not in new_text


def test_fixer_handles_all_4_blacklisted_at_once():
    # one .vmf can reference multiple blacklisted materials simultaneously;
    # the fixer must substitute all of them in a single pass.
    text = (
        'world\n{\n\t"classname" "worldspawn"\n\t"skyname" "sky_cs_office"\n'
        '\tside { "material" "dev/dev_hazzardstripe01a" }\n'
        '\tside { "material" "dev/reflectivity_90b" }\n'
        '\tside { "material" "editor/gray" }\n'
        '\tside { "material" "tools/locked" }\n'
        "}\n"
    )
    a = analyze_vmf(text)
    new_text, results = apply_all(text, a.findings)
    for original in (
        "dev/dev_hazzardstripe01a",
        "dev/reflectivity_90b",
        "editor/gray",
        "tools/locked",
    ):
        assert original not in new_text, f"{original} should be substituted"
    # substitutes present
    assert "dev/dev_measuregeneric01b" in new_text  # for hazzard + reflectivity
    assert "tools/toolsblack" in new_text  # for editor/gray
    assert "tools/toolsnodraw" in new_text  # for tools/locked


def test_no_finding_when_brush_uses_safe_materials():
    text = _wrap_world_with_brush("metal/hr_metal/hr_metal_wall_a")
    a = analyze_vmf(text)
    bl = [f for f in a.findings if f.issue_id == "csgo_blacklisted_materials"]
    assert bl == []
