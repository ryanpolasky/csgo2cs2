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
    _build_refs_for_addon,
    _collect_staged_refs,
    _collect_vmf_refs,
    _content_addon_dir,
    _content_addon_maps_dir,
    _ensure_prefab_refs_stub,
    _extract_case_fixed_pak01_assets,
    _fix_vmdl_bodygroup_choices_text,
    _format_refs_kv,
    _importer_logged_successful_import,
    _mirror_into_csgo,
    _patch_vmdl_bodygroup_choices,
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
        # env_sprite uses `"model"` for a sprite path. The value is a
        # .vmt or .spr -- both must be skipped, not turned into
        # `models/.../glow.vmt.mdl`.
        'entity\n{\n  "model" "materials/sprites/glow04.vmt"\n}\n'
        'entity\n{\n  "model" "sprites/glow01.spr"\n}\n'
        # Embedded brush-volume ref ("*0", "*1", ...) -- not a file ref.
        'entity\n{\n  "model" "*0"\n}\n'
        # No "models/" prefix and no .mdl extension -- ambiguous, skip.
        'entity\n{\n  "model" "props/no_models_prefix"\n}\n',
        encoding="utf-8",
    )
    refs = _collect_vmf_refs(vmf)
    assert refs == [
        "materials/metal/hr_metal/hr_metal_wall_a.vmt",
        "materials/metal/metalcombine002.vmt",
        "materials/wood/wood_int_10.vmt",
        "models/props/foo.mdl",
        "models/weapons/w_pist_glock18.mdl",
    ]


def test_collect_vmf_refs_missing_file_returns_empty(tmp_path):
    assert _collect_vmf_refs(tmp_path / "nope.vmf") == []


def test_collect_vmf_refs_emits_skybox_faces(tmp_path):
    # worldspawn `"skyname"` resolves to 6 face vmts under
    # `materials/skybox/`. We emit both naming conventions to cover
    # historical (hl2 `<sky><face>`) and modern (csgo `<sky>_<face>`)
    # layouts -- source1import just skips refs it can't find.
    vmf = tmp_path / "test.vmf"
    vmf.write_text(
        'world\n{\n  "skyname" "sky_dust"\n}\n',
        encoding="utf-8",
    )
    refs = _collect_vmf_refs(vmf)
    expected = ["materials/skybox/sky_dust.vmt"]
    # `sky_dust` already starts with `sky_`, so no `sky_sky_dust.vmt`
    # duplicate is emitted.
    for face in ("up", "dn", "lf", "rt", "ft", "bk"):
        expected.append(f"materials/skybox/sky_dust{face}.vmt")
        expected.append(f"materials/skybox/sky_dust_{face}.vmt")
    assert refs == sorted(expected)


def test_collect_vmf_refs_skyname_strips_path_and_extension(tmp_path):
    vmf = tmp_path / "test.vmf"
    vmf.write_text(
        'world\n{\n  "skyname" "skybox/sky_dust.vmt"\n}\n',
        encoding="utf-8",
    )
    refs = _collect_vmf_refs(vmf)
    assert "materials/skybox/sky_dust_up.vmt" in refs
    assert "materials/skybox/sky_dustup.vmt" in refs


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


# `cs_mdl_import` (Valve's .mdl->.vmdl step) emits a .vmdl where every
# `BodyGroupChoice` block is missing the `name = "..."` KV. S2's
# resourcecompiler then errors out with "Invalid empty body group
# choice name" and fails every CSGO weapon model. The fixer injects
# the missing field using the parent BodyGroup's name + a 0-based
# choice index, e.g. `name = "magazine_choice_1"`.
_BODYGROUP_WEAPON_VMDL = (
    "<!-- kv3 modeldoc -->\r\n"
    "{\r\n"
    "\trootNode =\r\n"
    "\t{\r\n"
    '\t\t_class = "RootNode"\r\n'
    "\t\tchildren =\r\n"
    "\t\t[\r\n"
    "\t\t\t{\r\n"
    '\t\t\t\t_class = "BodyGroupList"\r\n'
    "\t\t\t\tchildren =\r\n"
    "\t\t\t\t[\r\n"
    "\t\t\t\t\t{\r\n"
    '\t\t\t\t\t\t_class = "BodyGroup"\r\n'
    '\t\t\t\t\t\tname = "studio"\r\n'
    "\t\t\t\t\t\tchildren =\r\n"
    "\t\t\t\t\t\t[\r\n"
    "\t\t\t\t\t\t\t{\r\n"
    '\t\t\t\t\t\t\t\t_class = "BodyGroupChoice"\r\n'
    "\t\t\t\t\t\t\t\tmeshes = [  ]\r\n"
    "\t\t\t\t\t\t\t},\r\n"
    "\t\t\t\t\t\t]\r\n"
    "\t\t\t\t\t},\r\n"
    "\t\t\t\t\t{\r\n"
    '\t\t\t\t\t\t_class = "BodyGroup"\r\n'
    '\t\t\t\t\t\tname = "magazine"\r\n'
    "\t\t\t\t\t\tchildren =\r\n"
    "\t\t\t\t\t\t[\r\n"
    "\t\t\t\t\t\t\t{\r\n"
    '\t\t\t\t\t\t\t\t_class = "BodyGroupChoice"\r\n'
    '\t\t\t\t\t\t\t\tmeshes = [ "w_pist_glock18_bg_magazine_sm0_lod0" ]\r\n'
    "\t\t\t\t\t\t\t},\r\n"
    "\t\t\t\t\t\t\t{\r\n"
    '\t\t\t\t\t\t\t\t_class = "BodyGroupChoice"\r\n'
    "\t\t\t\t\t\t\t\tmeshes = [  ]\r\n"
    "\t\t\t\t\t\t\t},\r\n"
    "\t\t\t\t\t\t]\r\n"
    "\t\t\t\t\t},\r\n"
    "\t\t\t\t]\r\n"
    "\t\t\t},\r\n"
    "\t\t]\r\n"
    "\t}\r\n"
    "}\r\n"
)


def test_fix_vmdl_bodygroup_choices_injects_name_per_parent():
    new_text, n = _fix_vmdl_bodygroup_choices_text(_BODYGROUP_WEAPON_VMDL)
    assert n == 3
    # Names are unique within each parent BodyGroup and start at 0.
    assert 'name = "studio_choice_0"' in new_text
    assert 'name = "magazine_choice_0"' in new_text
    assert 'name = "magazine_choice_1"' in new_text
    # Each `name = ...` line is matched with its parent BodyGroupChoice
    # block and follows the `_class = ...` line directly.
    assert ('_class = "BodyGroupChoice"\r\n' '\t\t\t\t\t\t\t\tname = "studio_choice_0"') in new_text


def test_fix_vmdl_bodygroup_choices_preserves_crlf_line_endings():
    # cs_mdl_import emits CRLF on Windows. Universal-newline text mode
    # would silently rewrite to LF and trip diff/sign tools.
    new_text, n = _fix_vmdl_bodygroup_choices_text(_BODYGROUP_WEAPON_VMDL)
    assert n == 3
    assert "\r\n" in new_text
    # No lone LFs introduced.
    raw = new_text.encode("utf-8")
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_fix_vmdl_bodygroup_choices_idempotent():
    once, n1 = _fix_vmdl_bodygroup_choices_text(_BODYGROUP_WEAPON_VMDL)
    twice, n2 = _fix_vmdl_bodygroup_choices_text(once)
    assert n1 == 3
    assert n2 == 0
    assert once == twice


def test_fix_vmdl_bodygroup_choices_leaves_named_choices_alone():
    # A .vmdl that already has names on its BodyGroupChoice children
    # should not be touched. The per-parent counter still advances so
    # sibling un-named choices receive distinct injected indices.
    vmdl = (
        "{\n"
        '\t_class = "BodyGroup"\n'
        '\tname = "magazine"\n'
        "\tchildren =\n"
        "\t[\n"
        "\t\t{\n"
        '\t\t\t_class = "BodyGroupChoice"\n'
        '\t\t\tname = "full"\n'
        "\t\t\tmeshes = []\n"
        "\t\t},\n"
        "\t\t{\n"
        '\t\t\t_class = "BodyGroupChoice"\n'
        "\t\t\tmeshes = [  ]\n"
        "\t\t},\n"
        "\t]\n"
        "}\n"
    )
    new_text, n = _fix_vmdl_bodygroup_choices_text(vmdl)
    assert n == 1
    # First child already had a name; the second gets the next index.
    assert 'name = "magazine_choice_1"' in new_text
    assert 'name = "full"' in new_text


def test_patch_vmdl_bodygroup_choices_walks_addon_models(tmp_path):
    cfg = _cfg_with_addons(tmp_path)
    addon_dir = _content_addon_dir(cfg, "test_addon")
    assert addon_dir is not None
    models = addon_dir / "models" / "weapons"
    models.mkdir(parents=True)
    weapon = models / "w_pist_glock18.vmdl"
    weapon.write_bytes(_BODYGROUP_WEAPON_VMDL.encode("utf-8"))
    # an unrelated text file we shouldn't touch.
    (models / "notes.txt").write_text("not a vmdl")

    n_files, n_choices = _patch_vmdl_bodygroup_choices(cfg, "test_addon")
    assert (n_files, n_choices) == (1, 3)
    # Re-running is a no-op.
    assert _patch_vmdl_bodygroup_choices(cfg, "test_addon") == (0, 0)
    # The .txt sibling is untouched.
    assert (models / "notes.txt").read_text() == "not a vmdl"


def test_patch_vmdl_bodygroup_choices_handles_unconfigured(tmp_path):
    # No cs2_addons_path configured -> nothing to patch.
    cfg = Config()
    assert _patch_vmdl_bodygroup_choices(cfg, "any") == (0, 0)


def test_patch_vmdl_bodygroup_choices_handles_missing_models_dir(tmp_path):
    cfg = _cfg_with_addons(tmp_path)
    addon_dir = _content_addon_dir(cfg, "test_addon")
    assert addon_dir is not None
    addon_dir.mkdir(parents=True)  # no models/ subdir
    assert _patch_vmdl_bodygroup_choices(cfg, "test_addon") == (0, 0)


# --- build_refs_for_addon ---------------------------------------------------


def test_build_refs_for_addon_merges_staged_and_vmf(tmp_path):
    # `_build_refs_for_addon` is the shared merge helper used by
    # `_write_prefab_refs_from_staged` AND the pak01 case-fix
    # preprocessor. Both must see the same ref set.
    staged = tmp_path / "staged"
    (staged / "materials" / "foo").mkdir(parents=True)
    (staged / "materials" / "foo" / "bar.vmt").write_text("x")
    vmf = tmp_path / "test.vmf"
    vmf.write_text(
        'world\n{\n  "skyname" "sky_dust"\n}\n'
        'side\n{\n  "material" "metal/hr_metal/hr_metal_wall_a"\n}\n',
        encoding="utf-8",
    )
    refs = _build_refs_for_addon(staged, vmf)
    assert "materials/foo/bar.vmt" in refs
    assert "materials/metal/hr_metal/hr_metal_wall_a.vmt" in refs
    assert "materials/skybox/sky_dust.vmt" in refs
    assert "materials/skybox/sky_dust_up.vmt" in refs


def test_build_refs_for_addon_handles_missing_inputs(tmp_path):
    # Both staged + vmf absent -> empty list (writer then emits empty KV).
    assert _build_refs_for_addon(None, None) == []
    assert _build_refs_for_addon(tmp_path / "nope", None) == []
    assert _build_refs_for_addon(None, tmp_path / "nope.vmf") == []


# --- skybox unsuffixed combined-ref emission --------------------------------


def test_collect_vmf_refs_emits_unsuffixed_skybox_with_sky_prefix(tmp_path):
    # CS2 also asks for the combined `sky_<skyname>.vmt` (no face suffix);
    # we emit it alongside the 6-face set. When the skyname already
    # starts with `sky_` (e.g. `sky_dust`), we don't add a `sky_sky_dust`
    # duplicate.
    vmf = tmp_path / "test.vmf"
    vmf.write_text('world\n{\n  "skyname" "dust"\n}\n', encoding="utf-8")
    refs = _collect_vmf_refs(vmf)
    assert "materials/skybox/dust.vmt" in refs
    assert "materials/skybox/sky_dust.vmt" in refs
    # 6 faces x 2 conventions + 2 unsuffixed (bare + sky_-prefixed) = 14
    assert len(refs) == 14


def test_collect_vmf_refs_skips_sky_prefix_when_skyname_already_prefixed(tmp_path):
    # `sky_dust` already starts with `sky_`, so we only emit one
    # unsuffixed variant (the bare one), not `sky_sky_dust.vmt`.
    vmf = tmp_path / "test.vmf"
    vmf.write_text('world\n{\n  "skyname" "sky_dust"\n}\n', encoding="utf-8")
    refs = _collect_vmf_refs(vmf)
    assert "materials/skybox/sky_dust.vmt" in refs
    assert "materials/skybox/sky_sky_dust.vmt" not in refs


# --- pak01 case-fix preprocessor --------------------------------------------


def _build_synthetic_pak01(install_dir, vmt_path, vmt_text, vtf_path):
    """Build a minimal pak01_dir.vpk under `<install>/csgo/` containing
    one .vmt + one .vtf at the given paths. The vpk library indexes
    whatever paths we hand it via the on-disk layout, so we use a
    temp dir to seed the file structure and then save the vpk."""
    import shutil
    import tempfile

    import vpk

    csgo_dir = install_dir / "csgo"
    csgo_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path as _Path

        pakroot = _Path(tmp) / "pakroot"
        (pakroot / vmt_path).parent.mkdir(parents=True, exist_ok=True)
        (pakroot / vmt_path).write_text(vmt_text, encoding="latin-1")
        (pakroot / vtf_path).parent.mkdir(parents=True, exist_ok=True)
        (pakroot / vtf_path).write_bytes(b"\x00VTF_BLOB" * 8)

        new_vpk = vpk.new(str(pakroot))
        out = csgo_dir / "pak01_dir.vpk"
        new_vpk.save(str(out))
        shutil.rmtree(pakroot, ignore_errors=True)
    return csgo_dir / "pak01_dir.vpk"


def test_extract_case_fixed_pak01_assets_handles_capital_d_basetexture(tmp_path):
    # Reproduce the dev_hazzardstripe01a bug: pak01 stores the .vtf at
    # `materials/dev/dev_hazzardstripe01a.vtf` (lowercase) but the .vmt's
    # `$basetexture` value is `Dev/dev_hazzardstripe01a` (capital D).
    # source1import's case-sensitive VPK lookup misses the .vtf and
    # silently drops the .vmt. We stage both as loose files under
    # <csgo>/ so Windows' case-insensitive fs resolves them.
    install = tmp_path / "Counter-Strike Global Offensive"
    _build_synthetic_pak01(
        install,
        vmt_path="materials/dev/dev_hazzardstripe01a.vmt",
        vmt_text=(
            '"LightmappedGeneric"\n{\n'
            '\t"$basetexture" "Dev/dev_hazzardstripe01a"\n'
            '\t"$surfaceprop" "concrete"\n}\n'
        ),
        vtf_path="materials/dev/dev_hazzardstripe01a.vtf",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    refs = ["materials/dev/dev_hazzardstripe01a.vmt"]

    n = _extract_case_fixed_pak01_assets(refs, install, workspace)
    assert n == 2  # .vmt + .vtf
    loose_vmt = install / "csgo" / "materials" / "dev" / "dev_hazzardstripe01a.vmt"
    loose_vtf = install / "csgo" / "materials" / "dev" / "dev_hazzardstripe01a.vtf"
    assert loose_vmt.is_file()
    assert loose_vtf.is_file()
    manifest = (workspace / ".csgo_mirror_manifest").read_text(encoding="utf-8")
    assert str(loose_vmt) in manifest
    assert str(loose_vtf) in manifest


def test_extract_case_fixed_pak01_assets_skips_clean_vmts(tmp_path):
    # When the .vmt's $basetexture already matches pak01's actual case,
    # source1import resolves it fine; we don't need to stage anything.
    install = tmp_path / "Counter-Strike Global Offensive"
    _build_synthetic_pak01(
        install,
        vmt_path="materials/concrete/floor.vmt",
        vmt_text=(
            '"LightmappedGeneric"\n{\n'
            '\t"$basetexture" "concrete/floor"\n}\n'  # lowercase, matches pak01
        ),
        vtf_path="materials/concrete/floor.vtf",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    refs = ["materials/concrete/floor.vmt"]
    assert _extract_case_fixed_pak01_assets(refs, install, workspace) == 0


def test_extract_case_fixed_pak01_assets_no_pak01(tmp_path):
    # No pak01_dir.vpk -> nothing to do, no error.
    install = tmp_path / "no_csgo"
    install.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert _extract_case_fixed_pak01_assets(["materials/x.vmt"], install, workspace) == 0


def test_extract_case_fixed_pak01_assets_empty_refs(tmp_path):
    # No refs in the prefab list -> no-op early.
    install = tmp_path / "Counter-Strike Global Offensive"
    install.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert _extract_case_fixed_pak01_assets([], install, workspace) == 0


def test_extract_case_fixed_pak01_assets_appends_to_existing_manifest(tmp_path):
    # The mirror fix may have already written a manifest with workshop
    # paths; we must APPEND to it (not overwrite) so cleanup removes
    # both sets of loose files.
    install = tmp_path / "Counter-Strike Global Offensive"
    _build_synthetic_pak01(
        install,
        vmt_path="materials/dev/dev_hazzardstripe01a.vmt",
        vmt_text=('"LightmappedGeneric"\n{\n' '\t"$basetexture" "Dev/dev_hazzardstripe01a"\n}\n'),
        vtf_path="materials/dev/dev_hazzardstripe01a.vtf",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # Pre-existing manifest entry (as if _mirror_into_csgo already wrote it).
    existing = install / "csgo" / "materials" / "wood" / "workshop_wood.vmt"
    existing.parent.mkdir(parents=True)
    existing.write_text("placeholder")
    (workspace / ".csgo_mirror_manifest").write_text(
        f"{existing}\n",
        encoding="utf-8",
    )

    refs = ["materials/dev/dev_hazzardstripe01a.vmt"]
    n = _extract_case_fixed_pak01_assets(refs, install, workspace)
    assert n == 2

    manifest = (workspace / ".csgo_mirror_manifest").read_text(encoding="utf-8")
    # Original workshop entry preserved
    assert str(existing) in manifest
    # New case-fixed paths appended
    loose_vmt = install / "csgo" / "materials" / "dev" / "dev_hazzardstripe01a.vmt"
    loose_vtf = install / "csgo" / "materials" / "dev" / "dev_hazzardstripe01a.vtf"
    assert str(loose_vmt) in manifest
    assert str(loose_vtf) in manifest
