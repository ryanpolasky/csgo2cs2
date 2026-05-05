# tests for `csgo2cs2 publish`. cross-platform; works against a fake
# addon dir on disk + checks the output zip's contents.

from __future__ import annotations

import zipfile
from pathlib import Path

from csgo2cs2.cli import build_parser
from csgo2cs2.config import Config, save_config


def _fake_install(tmp_path: Path, addon: str = "myaddon") -> tuple[Path, Path]:
    install = tmp_path / "Counter-Strike Global Offensive"
    bin64 = install / "game" / "bin" / "win64"
    bin64.mkdir(parents=True)
    (bin64 / "cs2.exe").write_text("# stub", encoding="utf-8")
    addon_dir = install / "game" / "csgo_addons" / addon
    (addon_dir / "maps").mkdir(parents=True)
    (addon_dir / "maps" / "de_dust2.vmap").write_text("# vmap", encoding="utf-8")
    (addon_dir / "addoninfo.json").write_text('{"title": "ok"}', encoding="utf-8")
    (addon_dir / "materials").mkdir()
    (addon_dir / "materials" / "foo.vmat").write_text("# vmat", encoding="utf-8")
    return bin64, addon_dir


def _cfg(tmp_path: Path, bin64: Path) -> Path:
    cfg = Config(cs2_bin_path=str(bin64), workspace_dir=str(tmp_path / "ws"))
    cfg_path = tmp_path / "cfg.json"
    save_config(cfg, str(cfg_path))
    return cfg_path


def _run(parser, args_list, cfg_path) -> int:
    args = parser.parse_args(args_list)
    args.config = str(cfg_path)
    return args.func(args)


def test_publish_writes_zip_with_addon_contents(tmp_path: Path) -> None:
    bin64, _ = _fake_install(tmp_path)
    cfg_path = _cfg(tmp_path, bin64)
    parser = build_parser()

    rc = _run(parser, ["publish", "myaddon", "-o", str(tmp_path / "myaddon.zip")], cfg_path)
    assert rc == 0
    out_zip = tmp_path / "myaddon.zip"
    assert out_zip.exists()
    with zipfile.ZipFile(out_zip) as zf:
        names = sorted(zf.namelist())
    assert "addoninfo.json" in names
    assert "maps/de_dust2.vmap" in names
    assert "materials/foo.vmat" in names


def test_publish_excludes_backup_files(tmp_path: Path) -> None:
    bin64, addon_dir = _fake_install(tmp_path)
    (addon_dir / "maps" / "de_dust2.vmap.csgo2cs2.bak").write_text("old", encoding="utf-8")
    (addon_dir / "_csgo2cs2_preview_dl.tmp").write_text("trash", encoding="utf-8")

    cfg_path = _cfg(tmp_path, bin64)
    parser = build_parser()
    rc = _run(parser, ["publish", "myaddon", "-o", str(tmp_path / "myaddon.zip")], cfg_path)
    assert rc == 0

    with zipfile.ZipFile(tmp_path / "myaddon.zip") as zf:
        names = zf.namelist()
    assert not any(".bak" in n for n in names)
    assert not any(n.startswith("_csgo2cs2_") for n in names)


def test_publish_aborts_when_verify_errors(tmp_path: Path) -> None:
    # missing materials -> verify will report errors -> publish should
    # exit non-zero (without --allow-errors).
    bin64, addon_dir = _fake_install(tmp_path)
    (addon_dir / "maps" / "de_dust2.vmap").write_text(
        '"materialname" "materials/missing_thing.vmat"', encoding="utf-8"
    )
    cfg_path = _cfg(tmp_path, bin64)
    parser = build_parser()
    rc = _run(parser, ["publish", "myaddon", "-o", str(tmp_path / "out.zip")], cfg_path)
    assert rc == 1
    assert not (tmp_path / "out.zip").exists()


def test_publish_allow_errors_overrides_verify_failure(tmp_path: Path) -> None:
    bin64, addon_dir = _fake_install(tmp_path)
    (addon_dir / "maps" / "de_dust2.vmap").write_text(
        '"materialname" "materials/missing_thing.vmat"', encoding="utf-8"
    )
    cfg_path = _cfg(tmp_path, bin64)
    parser = build_parser()
    rc = _run(
        parser,
        ["publish", "myaddon", "-o", str(tmp_path / "out.zip"), "--allow-errors"],
        cfg_path,
    )
    assert rc == 0
    assert (tmp_path / "out.zip").exists()


def test_publish_skip_verify_runs_packaging_only(tmp_path: Path) -> None:
    bin64, addon_dir = _fake_install(tmp_path)
    (addon_dir / "maps" / "de_dust2.vmap").write_text(
        '"materialname" "materials/missing_thing.vmat"', encoding="utf-8"
    )
    cfg_path = _cfg(tmp_path, bin64)
    parser = build_parser()
    rc = _run(
        parser,
        ["publish", "myaddon", "-o", str(tmp_path / "out.zip"), "--skip-verify"],
        cfg_path,
    )
    assert rc == 0
    assert (tmp_path / "out.zip").exists()


def test_publish_default_output_lives_in_workspace_dir(tmp_path: Path) -> None:
    bin64, _ = _fake_install(tmp_path)
    cfg_path = _cfg(tmp_path, bin64)
    parser = build_parser()
    rc = _run(parser, ["publish", "myaddon"], cfg_path)
    assert rc == 0
    expected = tmp_path / "ws" / "myaddon.zip"
    assert expected.exists()


def test_publish_returns_2_for_unknown_addon(tmp_path: Path) -> None:
    bin64, _ = _fake_install(tmp_path)
    cfg_path = _cfg(tmp_path, bin64)
    parser = build_parser()
    rc = _run(parser, ["publish", "no_such_addon"], cfg_path)
    assert rc == 2
