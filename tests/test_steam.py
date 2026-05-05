# tests for steam install detection helpers.

from __future__ import annotations

from pathlib import Path

from csgo2cs2.utils import steam

VDF_SAMPLE = """\
"libraryfolders"
{
    "0"
    {
        "path"        "C:\\\\Program Files (x86)\\\\Steam"
        "label"       ""
        "contentid"   "1234567890"
    }
    "1"
    {
        "path"        "D:\\\\SteamLibrary"
        "label"       "games"
        "contentid"   "9876543210"
    }
}
"""


def test_parse_libraryfolders_extracts_paths():
    paths = steam._parse_libraryfolders_vdf(VDF_SAMPLE)
    assert any(str(p).endswith("Steam") for p in paths)
    assert any(str(p).endswith("SteamLibrary") for p in paths)


def test_parse_libraryfolders_handles_empty_input():
    assert steam._parse_libraryfolders_vdf("") == []


def test_read_library_folders_includes_root(tmp_path: Path):
    # write a minimal vdf with one extra library
    vdf = '"libraryfolders"\n{\n  "0" { "path" "/some/where" }\n}\n'
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "libraryfolders.vdf").write_text(vdf, encoding="utf-8")
    libs = steam._read_library_folders(tmp_path)
    # root is always first
    assert libs[0] == tmp_path
    # additional path is parsed in
    assert Path("/some/where") in libs


def test_find_csgo_install_returns_none_when_no_steam(monkeypatch, tmp_path):
    monkeypatch.setattr(steam, "_candidate_steam_roots", lambda: [])
    assert steam.find_csgo_install() is None


def test_find_csgo_install_returns_path_when_present(monkeypatch, tmp_path):
    csgo = tmp_path / "steamapps" / "common" / steam.CSGO_FOLDER_NAME
    csgo.mkdir(parents=True)
    monkeypatch.setattr(steam, "_candidate_steam_roots", lambda: [tmp_path])
    monkeypatch.setattr(steam, "_read_library_folders", lambda root: [tmp_path])
    assert steam.find_csgo_install() == csgo
