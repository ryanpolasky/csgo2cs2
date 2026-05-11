# tests for the post-import workarounds in pipeline:
# - `_content_addon_maps_dir` deriving content/ from game/
# - `_ensure_prefab_refs_stub` / `_write_prefab_refs_from_staged` writing
#   the refs file Keller's wrapper reads to drive per-asset conversion
# - `_importer_logged_successful_import` matching the source1import
#   success line so a wrapper crash after a green import isn't masked.

from __future__ import annotations

from csgo2cs2.config import Config
from csgo2cs2.pipeline import (
    _CONTENTDIR_MARKER,
    _collect_staged_refs,
    _collect_vmf_refs,
    _content_addon_maps_dir,
    _ensure_prefab_refs_stub,
    _format_refs_kv,
    _importer_logged_successful_import,
    _mirror_into_csgo,
    _unmirror_from_csgo,
    _unpatch_importer_contentdir,
    _write_prefab_refs_from_staged,
)


def _cfg_with_addons(tmp_path) -> Config:
    addons = tmp_path / "Counter-Strike Global Offensive" / "game" / "csgo_addons"
    return Config(cs2_addons_path=str(addons))


def test_content_addon_maps_dir_swaps_game_for_content(tmp_path):
    cfg = _cfg_with_addons(tmp_path)
    maps_dir = _content_addon_maps_dir(cfg, "test_addon")
    assert maps_dir is not None
    expected = (
        tmp_path
        / "Counter-Strike Global Offensive"
        / "content"
        / "csgo_addons"
        / "test_addon"
        / "maps"
    )
    assert maps_dir == expected


def test_content_addon_maps_dir_returns_none_when_unconfigured():
    cfg = Config(cs2_addons_path=None)
    assert _content_addon_maps_dir(cfg, "x") is None


def test_content_addon_maps_dir_returns_none_when_game_segment_missing(tmp_path):
    cfg = Config(cs2_addons_path=str(tmp_path / "weird" / "layout" / "csgo_addons"))
    assert _content_addon_maps_dir(cfg, "x") is None


def test_ensure_prefab_refs_stub_creates_empty_kv(tmp_path):
    cfg = _cfg_with_addons(tmp_path)
    _ensure_prefab_refs_stub(cfg, "test_addon", "recoil_master")
    stub = (
        tmp_path
        / "Counter-Strike Global Offensive"
        / "content"
        / "csgo_addons"
        / "test_addon"
        / "maps"
        / "recoil_master_prefab_refs.txt"
    )
    # Empty stub is still a well-formed KV block (no "file" entries)
    # so Keller's ListStringFromRefs parses cleanly.
    text = stub.read_text()
    assert "importfilelist" in text
    assert '"file"' not in text


def test_ensure_prefab_refs_stub_overwrites_existing_refs(tmp_path):
    # We always rewrite the refs file from the current staged + .vmf
    # inputs because we run *before* source1import on each port. Stale
    # refs from prior runs would mask freshly-collected ones.
    cfg = _cfg_with_addons(tmp_path)
    maps_dir = _content_addon_maps_dir(cfg, "test_addon")
    assert maps_dir is not None
    maps_dir.mkdir(parents=True)
    stub = maps_dir / "recoil_master_prefab_refs.txt"
    stub.write_text('importfilelist\n{\n\t"file" "models/stale.mdl"\n}\n')
    _ensure_prefab_refs_stub(cfg, "test_addon", "recoil_master")
    text = stub.read_text()
    assert "importfilelist" in text
    assert "models/stale.mdl" not in text  # stale refs are discarded
    assert '"file"' not in text  # empty stub since no inputs supplied


def test_ensure_prefab_refs_stub_no_op_without_addons_path():
    cfg = Config(cs2_addons_path=None)
    # must not raise
    _ensure_prefab_refs_stub(cfg, "test_addon", "recoil_master")


def test_format_refs_kv_empty():
    out = _format_refs_kv([])
    assert out == "importfilelist\n{\n}\n"


def test_format_refs_kv_populated():
    out = _format_refs_kv(
        [
            "materials/recoil_master/icon_x.vmt",
            "models/props/foo.mdl",
        ]
    )
    assert "importfilelist" in out
    assert '"file" "materials/recoil_master/icon_x.vmt"' in out
    assert '"file" "models/props/foo.mdl"' in out


def test_collect_staged_refs_walks_materials_and_models(tmp_path):
    staged = tmp_path / "staged"
    (staged / "materials" / "recoil_master").mkdir(parents=True)
    (staged / "materials" / "recoil_master" / "a.vmt").write_text("")
    (staged / "materials" / "recoil_master" / "sub" / "b.vmt").parent.mkdir()
    (staged / "materials" / "recoil_master" / "sub" / "b.vmt").write_text("")
    (staged / "materials" / "recoil_master" / "ignore.vtf").write_text("")
    (staged / "models" / "props").mkdir(parents=True)
    (staged / "models" / "props" / "c.mdl").write_text("")
    (staged / "models" / "props" / "c.vtx").write_text("")  # not a .mdl ref
    refs = _collect_staged_refs(staged)
    assert refs == [
        "materials/recoil_master/a.vmt",
        "materials/recoil_master/sub/b.vmt",
        "models/props/c.mdl",
    ]


def test_collect_staged_refs_empty_staged_root(tmp_path):
    staged = tmp_path / "staged"
    staged.mkdir()
    assert _collect_staged_refs(staged) == []


def test_write_prefab_refs_from_staged_populates(tmp_path):
    cfg = _cfg_with_addons(tmp_path)
    staged = tmp_path / "staged"
    (staged / "materials" / "recoil_master").mkdir(parents=True)
    (staged / "materials" / "recoil_master" / "icon.vmt").write_text("")
    n = _write_prefab_refs_from_staged(cfg, "test_addon", "recoil_master", staged)
    assert n == 1
    out = (
        tmp_path
        / "Counter-Strike Global Offensive"
        / "content"
        / "csgo_addons"
        / "test_addon"
        / "maps"
        / "recoil_master_prefab_refs.txt"
    )
    text = out.read_text()
    assert '"file" "materials/recoil_master/icon.vmt"' in text


def test_write_prefab_refs_from_staged_overwrites_empty_kv_stub(tmp_path):
    cfg = _cfg_with_addons(tmp_path)
    # Pre-create an empty KV stub (no "file" entries) as our own pipeline
    # would on an earlier pass without staged content.
    _ensure_prefab_refs_stub(cfg, "test_addon", "recoil_master")
    staged = tmp_path / "staged"
    (staged / "materials" / "recoil_master").mkdir(parents=True)
    (staged / "materials" / "recoil_master" / "x.vmt").write_text("")
    n = _write_prefab_refs_from_staged(cfg, "test_addon", "recoil_master", staged)
    assert n == 1
    out = (
        tmp_path
        / "Counter-Strike Global Offensive"
        / "content"
        / "csgo_addons"
        / "test_addon"
        / "maps"
        / "recoil_master_prefab_refs.txt"
    )
    assert '"file" "materials/recoil_master/x.vmt"' in out.read_text()


def test_collect_vmf_refs_extracts_materials_and_models(tmp_path):
    # Synthetic .vmf body covers the shapes encountered in real maps:
    # bare material refs, all-caps material refs, model refs with .mdl,
    # tools/* refs to be filtered out, and an extra-quoted .vmt suffix.
    vmf = tmp_path / "test.vmf"
    vmf.write_text(
        'solid\n{\n  side\n  {\n    "material" "METAL/METALCOMBINE002"\n  }\n}\n'
        'side\n{\n  "material" "wood/wood_int_10"\n}\n'
        'side\n{\n  "material" "tools/toolsclip"\n}\n'
        'side\n{\n  "material" "metal/hr_metal/hr_metal_wall_a.vmt"\n}\n'
        'entity\n{\n  "model" "models/weapons/w_pist_glock18.mdl"\n}\n'
        'entity\n{\n  "model" "models/props/foo"\n}\n'
        'entity\n{\n  "model" "props/no_models_prefix.mdl"\n}\n',
        encoding="utf-8",
    )
    refs = _collect_vmf_refs(vmf)
    assert refs == [
        "materials/metal/hr_metal/hr_metal_wall_a.vmt",
        "materials/metal/metalcombine002.vmt",
        "materials/wood/wood_int_10.vmt",
        "models/props/foo.mdl",
        "models/props/no_models_prefix.mdl",
        "models/weapons/w_pist_glock18.mdl",
    ]


def test_collect_vmf_refs_missing_file_returns_empty(tmp_path):
    assert _collect_vmf_refs(tmp_path / "nope.vmf") == []


def test_write_prefab_refs_from_staged_merges_vmf_refs(tmp_path):
    cfg = _cfg_with_addons(tmp_path)
    staged = tmp_path / "staged"
    (staged / "materials" / "recoil_master").mkdir(parents=True)
    (staged / "materials" / "recoil_master" / "icon.vmt").write_text("")
    vmf = staged / "maps" / "recoil_master.vmf"
    vmf.parent.mkdir(parents=True)
    vmf.write_text(
        'side\n{\n  "material" "metal/metalcombine002"\n}\n'
        'entity\n{\n  "model" "models/weapons/w_pist_glock18.mdl"\n}\n',
        encoding="utf-8",
    )
    n = _write_prefab_refs_from_staged(cfg, "test_addon", "recoil_master", staged, vmf)
    # Both staged refs and VMF-referenced refs end up in the output.
    assert n == 3
    out = (
        tmp_path
        / "Counter-Strike Global Offensive"
        / "content"
        / "csgo_addons"
        / "test_addon"
        / "maps"
        / "recoil_master_prefab_refs.txt"
    )
    text = out.read_text()
    assert '"file" "materials/recoil_master/icon.vmt"' in text
    assert '"file" "materials/metal/metalcombine002.vmt"' in text
    assert '"file" "models/weapons/w_pist_glock18.mdl"' in text


def test_write_prefab_refs_from_staged_overwrites_existing_populated(tmp_path):
    # Re-running `csgo2cs2 port` must refresh the refs file from the
    # current staged + .vmf inputs. Source1import never runs before us,
    # so we can't be racing its output.
    cfg = _cfg_with_addons(tmp_path)
    maps_dir = _content_addon_maps_dir(cfg, "test_addon")
    assert maps_dir is not None
    maps_dir.mkdir(parents=True)
    out = maps_dir / "recoil_master_prefab_refs.txt"
    stale = 'importfilelist\n{\n\t"file" "materials/stale.vmt"\n}\n'
    out.write_text(stale)
    staged = tmp_path / "staged"
    (staged / "materials").mkdir(parents=True)
    (staged / "materials" / "new.vmt").write_text("")
    n = _write_prefab_refs_from_staged(cfg, "test_addon", "recoil_master", staged)
    assert n == 1
    text = out.read_text()
    assert '"file" "materials/new.vmt"' in text
    assert "materials/stale.vmt" not in text


def test_importer_success_marker_matches_canonical_line():
    line = (
        "-----------------------------------------------------------------\n"
        " OK: 1 imported, 0 failed, 0 skipped, 0 unknown, 0m:03s\n"
        "-----------------------------------------------------------------\n"
    )
    assert _importer_logged_successful_import(line) is True


def test_importer_success_marker_rejects_partial_failure():
    # `1 failed` in the count must not be misread as success.
    line = " OK: 1 imported, 1 failed, 0 skipped, 0 unknown, 0m:03s"
    assert _importer_logged_successful_import(line) is False


def test_importer_success_marker_rejects_error_summary():
    line = " ERROR: 0 imported, 1 failed, 0 skipped, 0 unknown, 0m:02s"
    assert _importer_logged_successful_import(line) is False


def test_importer_success_marker_empty_input():
    assert _importer_logged_successful_import("") is False
    assert _importer_logged_successful_import(None) is False  # type: ignore[arg-type]


def test_unpatch_importer_contentdir_reverts_old_injection(tmp_path):
    # an older csgo2cs2 patched the script -- verify we restore it.
    script = tmp_path / "import_map_community.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        'importRefsCmd = "source1import -retail -nop4 -nop4sync '
        '-src1gameinfodir \\"%s\\" -src1contentdir \\"%s\\" -s2addon %s -game csgo '
        '-usefilelist \\"%s\\"" % ( s1gamecsgo, s1contentcsgo, s2addon, temp_refs )\n'
        'importcmd = "source1import -retail -nop4 -nop4sync '
        '-src1gameinfodir \\"" + s1gamecsgo + "\\" -src1contentdir \\"" '
        '+ s1contentcsgo + "\\" -s2addon " '
        '+ s2addon + " -game csgo -usefilelist \\"" + refsFile + "\\""\n'
        f"\n{_CONTENTDIR_MARKER}\n",
        encoding="utf-8",
    )
    assert _unpatch_importer_contentdir(script) is True
    text = script.read_text()
    assert _CONTENTDIR_MARKER not in text
    assert "-src1contentdir" not in text
    assert (
        'importRefsCmd = "source1import -retail -nop4 -nop4sync '
        '-src1gameinfodir \\"%s\\" -s2addon %s -game csgo '
        '-usefilelist \\"%s\\"" % ( s1gamecsgo, s2addon, temp_refs )'
    ) in text


def test_unpatch_importer_contentdir_noop_on_pristine(tmp_path):
    # pristine Keller script has no marker; unpatch is a no-op.
    script = tmp_path / "import_map_community.py"
    script.write_text("# pristine\n", encoding="utf-8")
    assert _unpatch_importer_contentdir(script) is False


def test_unpatch_importer_contentdir_idempotent(tmp_path):
    # unpatching an already-unpatched script is a no-op.
    script = tmp_path / "import_map_community.py"
    script.write_text("# already reverted, no marker\n", encoding="utf-8")
    assert _unpatch_importer_contentdir(script) is False


def test_mirror_into_csgo_copies_materials_and_models(tmp_path):
    staged = tmp_path / "staged"
    (staged / "materials" / "recoil_master").mkdir(parents=True)
    (staged / "materials" / "recoil_master" / "icon.vmt").write_text("vmt")
    (staged / "materials" / "recoil_master" / "icon.vtf").write_bytes(b"\x00\x01")
    (staged / "models" / "props" / "recoil_master").mkdir(parents=True)
    (staged / "models" / "props" / "recoil_master" / "p.mdl").write_bytes(b"\x00")

    csgo = tmp_path / "csgo"
    csgo.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    n = _mirror_into_csgo(staged, csgo, workspace)
    assert n == 3
    assert (csgo / "materials" / "recoil_master" / "icon.vmt").is_file()
    assert (csgo / "materials" / "recoil_master" / "icon.vtf").is_file()
    assert (csgo / "models" / "props" / "recoil_master" / "p.mdl").is_file()

    manifest = workspace / ".csgo_mirror_manifest"
    assert manifest.is_file()
    lines = manifest.read_text().splitlines()
    assert len(lines) == 3


def test_mirror_into_csgo_preserves_existing_base_files(tmp_path):
    # csgo/materials/concrete/ already exists (base CSGO content). The
    # mirror must NOT overwrite it even if staged has a same-path file.
    staged = tmp_path / "staged"
    (staged / "materials" / "concrete").mkdir(parents=True)
    (staged / "materials" / "concrete" / "wall.vmt").write_text("workshop tampered")

    csgo = tmp_path / "csgo"
    (csgo / "materials" / "concrete").mkdir(parents=True)
    (csgo / "materials" / "concrete" / "wall.vmt").write_text("base")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    n = _mirror_into_csgo(staged, csgo, workspace)
    assert n == 0
    assert (csgo / "materials" / "concrete" / "wall.vmt").read_text() == "base"


def test_mirror_into_csgo_handles_missing_subdirs(tmp_path):
    staged = tmp_path / "staged"
    staged.mkdir()  # no materials/ or models/ inside
    csgo = tmp_path / "csgo"
    csgo.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert _mirror_into_csgo(staged, csgo, workspace) == 0


def test_unmirror_from_csgo_removes_only_mirrored_files(tmp_path):
    staged = tmp_path / "staged"
    (staged / "materials" / "recoil_master").mkdir(parents=True)
    (staged / "materials" / "recoil_master" / "icon.vmt").write_text("vmt")

    csgo = tmp_path / "csgo"
    # pre-existing base file that the mirror should not touch.
    (csgo / "materials" / "concrete").mkdir(parents=True)
    (csgo / "materials" / "concrete" / "base.vmt").write_text("base")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _mirror_into_csgo(staged, csgo, workspace)
    assert (csgo / "materials" / "recoil_master" / "icon.vmt").is_file()

    removed = _unmirror_from_csgo(workspace)
    assert removed == 1
    assert not (csgo / "materials" / "recoil_master" / "icon.vmt").exists()
    # parent recoil_master/ dir should be cleaned up too (best-effort).
    assert not (csgo / "materials" / "recoil_master").exists()
    # the base file must remain.
    assert (csgo / "materials" / "concrete" / "base.vmt").is_file()
    assert not (workspace / ".csgo_mirror_manifest").exists()


def test_unmirror_from_csgo_noop_when_no_manifest(tmp_path):
    assert _unmirror_from_csgo(tmp_path) == 0
