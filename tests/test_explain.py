# tests for the curated explanation registry.

from __future__ import annotations

from csgo2cs2.analyzers import explain
from csgo2cs2.analyzers.bsp import analyze_bsp_findings, inspect_bsp
from csgo2cs2.analyzers.vmf import analyze_vmf


def test_known_ids_returns_sorted_unique_list():
    ids = explain.known_ids()
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    # make sure a couple of canonical ids are present
    for sentinel in (
        "skybox_hdr_only",
        "manual_rebuild_nav",
        "manual_rebuild_cubemaps",
        "asset_path_csgo_subfolder",
        "bsp_protected",
    ):
        assert sentinel in ids


def test_get_returns_explanation_with_full_fields():
    exp = explain.get("skybox_hdr_only")
    assert exp is not None
    assert exp.issue_id == "skybox_hdr_only"
    assert exp.title
    assert exp.what
    assert exp.why
    assert exp.fix
    # at least one reference for the imported csgo->cs2 pitfall list
    assert exp.refs


def test_get_unknown_returns_none():
    assert explain.get("nope_does_not_exist") is None


def test_render_includes_title_and_sections():
    exp = explain.get("skybox_hdr_only")
    rendered = explain.render(exp)
    assert exp.title in rendered
    assert "What:" in rendered
    assert "Why:" in rendered
    assert "Fix:" in rendered
    assert "References:" in rendered


def test_render_without_refs_omits_references_block():
    exp = explain.get("missing_spawn")
    rendered = explain.render(exp)
    # missing_spawn has no references intentionally
    assert "References:" not in rendered


def test_every_vmf_finding_id_has_an_explanation():
    # build a synthetic vmf that triggers as many findings as possible, then
    # make sure every issue_id we emit has a curated entry. this guards
    # against silently shipping a finding with no human-readable context.
    text = """\
world
{
\t"classname" "worldspawn"
\t"skyname" "sky_office_hdr"
}
entity { "classname" "info_player_axis" }
entity { "classname" "env_cascade_light" }
entity { "classname" "func_areaportal" }
entity { "classname" "env_cubemap" }
entity { "classname" "env_soundscape" }
entity { "classname" "info_overlay" }
entity { "classname" "light_environment" }
entity { "classname" "light_environment" }
entity { "classname" "func_brush" "material" "myproj/customclip" }
entity { "classname" "func_brush" "material" "props/csgo/wall.vmt" }
entity { "classname" "func_brush" "material" "models/foo bar/space.vmt" }
entity { "classname" "prop_static" "model" "C:/abs/box.mdl" }
entity { "classname" "prop_static" "model" "models\\\\back\\\\slash.mdl" }
"""
    a = analyze_vmf(text)
    seen = sorted({f.issue_id for f in a.findings})
    assert seen, "test fixture should emit findings"
    missing = [i for i in seen if explain.get(i) is None]
    assert not missing, f"issue_id(s) without explanation: {missing}"


def test_every_bsp_finding_id_has_an_explanation(tmp_path):
    import io
    import struct
    import zipfile

    from csgo2cs2.analyzers.bsp import LUMP_PAKFILE

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("maps/de_dust2.nav", b"x")
        zf.writestr("resource/overviews/de_dust2_radar.dds", b"x")
        zf.writestr("scripts/soundscapes_de_dust2.txt", b"x")
        zf.writestr("scripts/vscripts/foo.lua", b"x")
        zf.writestr("materials/csgo/de_dust2/wall.vmt", b"x")
        zf.writestr("materials/maps/cubemap_001.hdr.vtf", b"x")
    blob = buf.getvalue()

    header = b"VBSP" + struct.pack("<i", 21)
    lump_table = bytearray(64 * 16)
    pak_offset = 8 + 64 * 16
    struct.pack_into(
        "<iiI4s",
        lump_table,
        LUMP_PAKFILE * 16,
        pak_offset,
        len(blob),
        0,
        b"\x00\x00\x00\x00",
    )
    bsp = tmp_path / "rich.bsp"
    bsp.write_bytes(header + bytes(lump_table) + blob)

    info = inspect_bsp(bsp)
    findings = analyze_bsp_findings(info)
    seen = sorted({f.issue_id for f in findings})
    assert seen, "test fixture should emit findings"
    missing = [i for i in seen if explain.get(i) is None]
    assert not missing, f"bsp issue_id(s) without explanation: {missing}"
