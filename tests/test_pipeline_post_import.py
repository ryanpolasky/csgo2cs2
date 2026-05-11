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
    _content_addon_maps_dir,
    _ensure_prefab_refs_stub,
    _format_refs_kv,
    _importer_logged_successful_import,
    _patch_importer_contentdir,
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


def test_ensure_prefab_refs_stub_preserves_populated_refs(tmp_path):
    cfg = _cfg_with_addons(tmp_path)
    maps_dir = _content_addon_maps_dir(cfg, "test_addon")
    assert maps_dir is not None
    maps_dir.mkdir(parents=True)
    stub = maps_dir / "recoil_master_prefab_refs.txt"
    # Simulate source1import having already written populated refs.
    populated = 'importfilelist\n{\n\t"file" "models/foo.mdl"\n}\n'
    stub.write_text(populated)
    _ensure_prefab_refs_stub(cfg, "test_addon", "recoil_master")
    assert stub.read_text() == populated  # untouched


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


def test_write_prefab_refs_from_staged_skips_when_populated(tmp_path):
    cfg = _cfg_with_addons(tmp_path)
    maps_dir = _content_addon_maps_dir(cfg, "test_addon")
    assert maps_dir is not None
    maps_dir.mkdir(parents=True)
    out = maps_dir / "recoil_master_prefab_refs.txt"
    populated = 'importfilelist\n{\n\t"file" "materials/from_s1import.vmt"\n}\n'
    out.write_text(populated)
    staged = tmp_path / "staged"
    (staged / "materials").mkdir(parents=True)
    (staged / "materials" / "new.vmt").write_text("")
    n = _write_prefab_refs_from_staged(cfg, "test_addon", "recoil_master", staged)
    # Existing populated refs win -- don't clobber source1import's output.
    assert n == 0
    assert out.read_text() == populated


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


def test_patch_importer_contentdir_applies(tmp_path):
    script = tmp_path / "import_map_community.py"
    script.write_text(
        '#!/usr/bin/env python3\n'
        'importRefsCmd = "source1import -retail -nop4 -nop4sync '
        '-src1gameinfodir \\"%s\\" -s2addon %s -game csgo '
        '-usefilelist \\"%s\\"" % ( s1gamecsgo, s2addon, temp_refs )\n'
        'importcmd = "source1import -retail -nop4 -nop4sync '
        '-src1gameinfodir \\"" + s1gamecsgo + "\\" -s2addon " '
        '+ s2addon + " -game csgo -usefilelist \\"" + refsFile + "\\""'
        '\n',
        encoding="utf-8",
    )
    assert _patch_importer_contentdir(script) is True
    text = script.read_text()
    assert "s1contentcsgo" in text
    assert _CONTENTDIR_MARKER in text


def test_patch_importer_contentdir_idempotent(tmp_path):
    script = tmp_path / "import_map_community.py"
    script.write_text(
        f'already patched\n{_CONTENTDIR_MARKER}\n',
        encoding="utf-8",
    )
    assert _patch_importer_contentdir(script) is False


def test_patch_importer_contentdir_unrecognised_baseline(tmp_path):
    script = tmp_path / "import_map_community.py"
    script.write_text("# unknown version\n", encoding="utf-8")
    assert _patch_importer_contentdir(script) is False
