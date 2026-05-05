# tests for the vmf analyzer.

from csgo2cs2.analyzers.vmf import (
    HDR_ONLY_SKIES,
    KNOWN_CS2_SKIES,
    LEGACY_SPAWN_ENTITIES,
    UNSUPPORTED_ENTITIES,
    analyze_vmf,
)

VMF_MINIMAL = """\
versioninfo
{
\t"editorversion" "400"
}
world
{
\t"id" "1"
\t"classname" "worldspawn"
\t"skyname" "__SKY__"
}
entity
{
\t"id" "10"
\t"classname" "info_player_terrorist"
}
entity
{
\t"id" "11"
\t"classname" "info_player_counterterrorist"
}
"""


def _vmf(sky="sky_csgo_night02", extras: str = "") -> str:
    return VMF_MINIMAL.replace("__SKY__", sky) + extras


def test_known_cs2_sky_produces_no_skybox_finding():
    text = _vmf(sky=next(iter(KNOWN_CS2_SKIES - HDR_ONLY_SKIES)))
    a = analyze_vmf(text)
    assert all(f.issue_id != "skybox_unknown" for f in a.findings)
    assert all(f.issue_id != "skybox_hdr_only" for f in a.findings)


def test_unknown_sky_is_flagged_and_fixable():
    text = _vmf(sky="sky_csgo_someoldsky")
    a = analyze_vmf(text, default_skybox="sky_day01_01")
    sky_findings = [f for f in a.findings if f.issue_id == "skybox_unknown"]
    assert len(sky_findings) == 1
    f = sky_findings[0]
    assert f.fixable
    assert f.context["current"] == "sky_csgo_someoldsky"
    assert f.context["replacement"] == "sky_day01_01"


def test_hdr_only_sky_produces_dedicated_error_finding():
    text = _vmf(sky="sky_office_hdr")
    a = analyze_vmf(text, default_skybox="sky_day01_01")
    hdr = [f for f in a.findings if f.issue_id == "skybox_hdr_only"]
    assert len(hdr) == 1
    assert hdr[0].severity == "error"
    assert hdr[0].fixable
    assert hdr[0].context["current"] == "sky_office_hdr"
    # the unknown-sky finding must NOT also fire on hdr-only matches
    assert not any(f.issue_id == "skybox_unknown" for f in a.findings)


def test_missing_skyname_is_flagged_not_fixable():
    text = """\
world
{
\t"id" "1"
\t"classname" "worldspawn"
}
"""
    a = analyze_vmf(text)
    findings = [f for f in a.findings if f.issue_id == "skybox_missing"]
    assert len(findings) == 1
    assert findings[0].fixable is False


def test_unsupported_entity_flagged():
    extra = """\
entity
{
\t"id" "20"
\t"classname" "env_cascade_light"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    cls_findings = [
        f
        for f in a.findings
        if f.issue_id == "entity_unsupported" and f.context.get("classname") == "env_cascade_light"
    ]
    assert len(cls_findings) == 1
    assert cls_findings[0].fixable
    assert cls_findings[0].context["count"] == 1


def test_expanded_unsupported_set_covers_known_classes():
    # the curated list should at minimum cover these documented offenders
    expected = {
        "env_cascade_light",
        "info_player_logo",
        "func_simpleladder",
        "point_servercommand",
    }
    assert expected.issubset(UNSUPPORTED_ENTITIES)


def test_extra_unsupported_entities_via_config():
    extra = """\
entity
{
\t"id" "30"
\t"classname" "csgo_team_intro_camera"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text, extra_unsupported_entities=["csgo_team_intro_camera"])
    matches = [
        f
        for f in a.findings
        if f.issue_id == "entity_unsupported"
        and f.context.get("classname") == "csgo_team_intro_camera"
    ]
    assert len(matches) == 1


def test_legacy_spawn_entity_flagged_separately():
    extra = """\
entity
{
\t"id" "40"
\t"classname" "info_player_axis"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    legacy = [f for f in a.findings if f.issue_id == "entity_legacy_spawn"]
    assert len(legacy) == 1
    assert legacy[0].context["classname"] == "info_player_axis"
    assert "info_player_axis" in LEGACY_SPAWN_ENTITIES


def test_required_spawns_detected():
    a = analyze_vmf(_vmf())
    missing = [f for f in a.findings if f.issue_id == "missing_spawn"]
    assert missing == []  # both spawns present


def test_missing_required_spawns_flagged():
    text = """\
world
{
\t"classname" "worldspawn"
\t"skyname" "sky_day01_01"
}
"""
    a = analyze_vmf(text)
    missing = sorted(f.context["classname"] for f in a.findings if f.issue_id == "missing_spawn")
    assert missing == ["info_player_counterterrorist", "info_player_terrorist"]


def test_total_entities_and_class_counts():
    a = analyze_vmf(_vmf())
    # worldspawn plus 2 entities equals 3 classnames
    assert a.total_entities == 3
    assert a.class_counts["info_player_terrorist"] == 1
    assert a.class_counts["info_player_counterterrorist"] == 1


def test_asset_path_with_space_flagged_as_error():
    extra = """\
entity
{
\t"id" "50"
\t"classname" "func_brush"
\t"material" "models/props/my prop/wall.vmt"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    spaces = [f for f in a.findings if f.issue_id == "asset_path_space"]
    assert len(spaces) == 1
    assert spaces[0].severity == "error"
    assert "models/props/my prop/wall.vmt" == spaces[0].context["path"]


def test_asset_path_absolute_drive_letter_flagged():
    extra = """\
entity
{
\t"id" "51"
\t"classname" "prop_static"
\t"model" "C:/dev/maps/myprop.mdl"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    abs_findings = [f for f in a.findings if f.issue_id == "asset_path_absolute"]
    assert len(abs_findings) == 1
    assert abs_findings[0].severity == "error"


def test_asset_path_backslash_flagged_as_warning():
    extra = """\
entity
{
\t"id" "52"
\t"classname" "prop_static"
\t"model" "models\\\\props\\\\wall.mdl"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    bs = [f for f in a.findings if f.issue_id == "asset_path_backslash"]
    assert len(bs) == 1
    assert bs[0].severity == "warn"


def test_asset_refs_dedup_and_sort():
    extra = """\
entity
{
\t"id" "60"
\t"material" "props/wall.vmt"
\t"texture" "props/wall.vmt"
\t"model" "props/box.mdl"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    assert a.asset_refs == ["props/box.mdl", "props/wall.vmt"]


def test_cs2_sky_list_override_accepts_custom_sky():
    text = _vmf(sky="my_studio_sky")
    a = analyze_vmf(text, cs2_sky_list=["my_studio_sky"])
    assert all(f.issue_id != "skybox_unknown" for f in a.findings)


def test_finding_to_dict_round_trip():
    text = _vmf(sky="sky_csgo_someoldsky")
    a = analyze_vmf(text)
    d = a.to_dict()
    assert d["skyname"] == "sky_csgo_someoldsky"
    assert isinstance(d["findings"], list)
    assert d["total_entities"] == a.total_entities
    # findings serialize to dicts with all required keys
    for f in d["findings"]:
        assert {"issue_id", "severity", "message", "fixable", "context"} <= set(f.keys())


# ---------------------------------------------------------------------------
# pr3 pitfall coverage
# ---------------------------------------------------------------------------


def test_deprecated_s2_entity_func_areaportal_flagged_info():
    extra = """\
entity
{
\t"id" "70"
\t"classname" "func_areaportal"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    dep = [
        f
        for f in a.findings
        if f.issue_id == "entity_deprecated_s2" and f.context.get("classname") == "func_areaportal"
    ]
    assert len(dep) == 1
    assert dep[0].severity == "info"
    assert dep[0].fixable is False


def test_color_correction_volume_flagged_deprecated():
    extra = """\
entity
{
\t"id" "71"
\t"classname" "color_correction_volume"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    assert any(
        f.issue_id == "entity_deprecated_s2"
        and f.context.get("classname") == "color_correction_volume"
        for f in a.findings
    )


def test_env_cubemap_emits_manual_rebuild_cubemaps_once():
    extra = """\
entity
{
\t"id" "80"
\t"classname" "env_cubemap"
}
entity
{
\t"id" "81"
\t"classname" "env_cubemap"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    rebuild = [f for f in a.findings if f.issue_id == "manual_rebuild_cubemaps"]
    assert len(rebuild) == 1  # deduped per category
    assert rebuild[0].severity == "info"


def test_soundscape_entities_emit_manual_review_soundscapes():
    extra = """\
entity
{
\t"id" "82"
\t"classname" "env_soundscape"
}
entity
{
\t"id" "83"
\t"classname" "ambient_generic"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    rebuild = [f for f in a.findings if f.issue_id == "manual_review_soundscapes"]
    assert len(rebuild) == 1


def test_info_overlay_emits_manual_review_overlays():
    extra = """\
entity
{
\t"id" "84"
\t"classname" "info_overlay"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    assert any(f.issue_id == "manual_review_overlays" for f in a.findings)


def test_multiple_light_environment_flagged():
    extra = """\
entity
{
\t"id" "90"
\t"classname" "light_environment"
}
entity
{
\t"id" "91"
\t"classname" "light_environment"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    le = [f for f in a.findings if f.issue_id == "light_environment_count"]
    assert len(le) == 1
    assert le[0].context["count"] == 2


def test_single_light_environment_not_flagged():
    extra = """\
entity
{
\t"id" "92"
\t"classname" "light_environment"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    assert not any(f.issue_id == "light_environment_count" for f in a.findings)


def test_custom_clip_texture_flagged():
    extra = """\
entity
{
\t"id" "100"
\t"classname" "func_brush"
\t"material" "myproj/customclip"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    clip = [f for f in a.findings if f.issue_id == "texture_clip_custom"]
    assert len(clip) == 1
    assert clip[0].context["path"] == "myproj/customclip"


def test_tools_clip_texture_not_flagged():
    extra = """\
entity
{
\t"id" "101"
\t"classname" "func_brush"
\t"material" "tools/toolsclip"
}
entity
{
\t"id" "102"
\t"classname" "func_brush"
\t"material" "tools/toolsplayerclip"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    assert not any(f.issue_id == "texture_clip_custom" for f in a.findings)


def test_csgo_subfolder_in_asset_path_flagged_once():
    extra = """\
entity
{
\t"id" "110"
\t"classname" "func_brush"
\t"material" "models/csgo/de_dust2/wall.vmt"
}
entity
{
\t"id" "111"
\t"classname" "func_brush"
\t"material" "materials/csgo/something_else.vmt"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    sub = [f for f in a.findings if f.issue_id == "asset_path_csgo_subfolder"]
    # we emit a single category-level finding to avoid noise
    assert len(sub) == 1


def test_no_csgo_subfolder_when_csgo_appears_only_in_filename():
    # "csgo" embedded in a file/folder name but not as a directory segment
    # should NOT trigger the finding.
    extra = """\
entity
{
\t"id" "112"
\t"classname" "func_brush"
\t"material" "models/cs_go_props/wall.vmt"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    assert not any(f.issue_id == "asset_path_csgo_subfolder" for f in a.findings)
