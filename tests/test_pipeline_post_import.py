# tests for the post-import workarounds in pipeline:
# - `_content_addon_maps_dir` deriving content/ from game/
# - `_ensure_prefab_refs_stub` pre-creating the file Keller's script reads
# - `_importer_logged_successful_import` matching the source1import
#   success line so a wrapper crash after a green import isn't masked.

from __future__ import annotations

from csgo2cs2.config import Config
from csgo2cs2.pipeline import (
    _content_addon_maps_dir,
    _ensure_prefab_refs_stub,
    _importer_logged_successful_import,
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


def test_ensure_prefab_refs_stub_creates_empty_file(tmp_path):
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
    assert stub.exists()
    assert stub.stat().st_size == 0


def test_ensure_prefab_refs_stub_preserves_existing_nonempty(tmp_path):
    cfg = _cfg_with_addons(tmp_path)
    maps_dir = _content_addon_maps_dir(cfg, "test_addon")
    assert maps_dir is not None
    maps_dir.mkdir(parents=True)
    stub = maps_dir / "recoil_master_prefab_refs.txt"
    stub.write_text("mdl/foo.mdl\n")
    _ensure_prefab_refs_stub(cfg, "test_addon", "recoil_master")
    assert stub.read_text() == "mdl/foo.mdl\n"  # untouched


def test_ensure_prefab_refs_stub_no_op_without_addons_path():
    cfg = Config(cs2_addons_path=None)
    # must not raise
    _ensure_prefab_refs_stub(cfg, "test_addon", "recoil_master")


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

