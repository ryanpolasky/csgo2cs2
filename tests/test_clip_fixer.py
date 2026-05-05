# tests for the texture_clip_custom auto-fix.

from __future__ import annotations

from csgo2cs2.analyzers.vmf import analyze_vmf
from csgo2cs2.fixers import apply_all  # noqa: F401  (registers fixers)
from csgo2cs2.fixers.clip_textures import DEFAULT_CLIP, fix_texture_clip_custom


def _vmf_with_clip(material: str) -> str:
    # smallest valid-ish vmf shape: a worldspawn plus one solid with one
    # side that uses the supplied material. analyze_vmf doesn't need
    # full structural correctness here, just the `"material" "..."` pair.
    return (
        "world\n{\n"
        '\t"classname" "worldspawn"\n'
        '\t"skyname" "sky_de_dust2"\n'
        "\tsolid\n\t{\n"
        "\t\tside\n\t\t{\n"
        f'\t\t\t"material" "{material}"\n'
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )


def test_custom_clip_finding_is_now_fixable():
    text = _vmf_with_clip("office/office_clip_special")
    a = analyze_vmf(text)
    [f] = [x for x in a.findings if x.issue_id == "texture_clip_custom"]
    assert f.fixable is True
    assert f.context["path"] == "office/office_clip_special"


def test_fixer_rewrites_to_default_clip():
    text = _vmf_with_clip("office/office_clip_special")
    a = analyze_vmf(text)
    [f] = [x for x in a.findings if x.issue_id == "texture_clip_custom"]
    new_text, ok, detail = fix_texture_clip_custom(text, f)
    assert ok is True
    assert "office/office_clip_special" not in new_text
    assert f'"material" "{DEFAULT_CLIP}"' in new_text
    assert "office/office_clip_special" in detail


def test_fixer_is_idempotent_via_full_pipeline():
    text = _vmf_with_clip("custom/clip_blob")
    a1 = analyze_vmf(text)
    new_text, _ = apply_all(text, a1.findings)
    a2 = analyze_vmf(new_text)
    # no clip findings should remain after a single --fix pass
    assert not any(f.issue_id == "texture_clip_custom" for f in a2.findings)


def test_fixer_skips_when_already_default():
    text = _vmf_with_clip(DEFAULT_CLIP)
    a = analyze_vmf(text)
    # tools/toolsclip is recognized; analyzer should not flag it
    assert not any(f.issue_id == "texture_clip_custom" for f in a.findings)


def test_fixer_handles_capitalized_material_key():
    # rare in checked-in vmfs but the analyzer's regex is case-insensitive
    # so the fixer's fallback path needs to handle it too.
    text = _vmf_with_clip("custom/clip").replace('"material"', '"Material"')
    a = analyze_vmf(text)
    [f] = [x for x in a.findings if x.issue_id == "texture_clip_custom"]
    new_text, ok, _ = fix_texture_clip_custom(text, f)
    assert ok is True
    assert DEFAULT_CLIP in new_text
