# tests for `csgo2cs2 verify`. cross-platform; runs entirely against
# fake addon directories on disk.

from __future__ import annotations

from pathlib import Path

from csgo2cs2.cli import build_parser
from csgo2cs2.commands import verify_cmd
from csgo2cs2.config import Config, save_config


def _fake_addon(
    tmp_path: Path, addon: str = "myaddon", *, vmap_text: str = "# vmap"
) -> tuple[Path, Path]:
    install = tmp_path / "Counter-Strike Global Offensive"
    bin64 = install / "game" / "bin" / "win64"
    bin64.mkdir(parents=True)
    (bin64 / "cs2.exe").write_text("# stub", encoding="utf-8")
    addon_dir = install / "game" / "csgo_addons" / addon
    (addon_dir / "maps").mkdir(parents=True)
    (addon_dir / "maps" / "de_dust2.vmap").write_text(vmap_text, encoding="utf-8")
    return bin64, addon_dir


def _cfg_for(tmp_path: Path, bin64: Path) -> Path:
    cfg = Config(cs2_bin_path=str(bin64))
    cfg_path = tmp_path / "cfg.json"
    save_config(cfg, str(cfg_path))
    return cfg_path


def test_verify_clean_addon_returns_0(tmp_path, capsys) -> None:
    bin64, addon_dir = _fake_addon(tmp_path)
    # add a minimal addoninfo.json + a referenced material on disk.
    (addon_dir / "addoninfo.json").write_text('{"title": "myaddon"}', encoding="utf-8")
    (addon_dir / "maps" / "de_dust2.vmap").write_text(
        '"materialname" "materials/foo.vmat"', encoding="utf-8"
    )
    (addon_dir / "materials").mkdir()
    (addon_dir / "materials" / "foo.vmat").write_text("# vmat", encoding="utf-8")

    cfg_path = _cfg_for(tmp_path, bin64)
    parser = build_parser()
    args = parser.parse_args(["verify", "myaddon"])
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr()
    assert "Verification passed" in out.err or "Verification passed" in out.out


def test_verify_missing_addon_returns_1(tmp_path) -> None:
    bin64, _addon_dir = _fake_addon(tmp_path)
    cfg_path = _cfg_for(tmp_path, bin64)
    parser = build_parser()
    args = parser.parse_args(["verify", "nope"])
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 1


def test_verify_no_vmap_returns_1(tmp_path) -> None:
    bin64, addon_dir = _fake_addon(tmp_path)
    # remove the vmap.
    (addon_dir / "maps" / "de_dust2.vmap").unlink()

    cfg_path = _cfg_for(tmp_path, bin64)
    parser = build_parser()
    args = parser.parse_args(["verify", "myaddon"])
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 1


def test_verify_missing_assets_returns_1(tmp_path, capsys) -> None:
    bin64, addon_dir = _fake_addon(tmp_path)
    (addon_dir / "maps" / "de_dust2.vmap").write_text(
        '"materialname" "materials/missing_thing.vmat"\n' '"modelname" "models/missing_other.vmdl"',
        encoding="utf-8",
    )
    cfg_path = _cfg_for(tmp_path, bin64)
    parser = build_parser()
    args = parser.parse_args(["verify", "myaddon"])
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 1
    err = capsys.readouterr().err
    assert "missing_thing" in err or "missing_other" in err


def test_verify_warns_on_multiple_vmaps_without_map_arg(tmp_path, capsys) -> None:
    bin64, addon_dir = _fake_addon(tmp_path)
    # add a second vmap so the autodetect picks one and warns.
    (addon_dir / "maps" / "aim_redline.vmap").write_text("# vmap", encoding="utf-8")

    cfg_path = _cfg_for(tmp_path, bin64)
    parser = build_parser()
    args = parser.parse_args(["verify", "myaddon"])
    args.config = str(cfg_path)
    args.func(args)
    err = capsys.readouterr().err
    assert "Multiple .vmap files" in err


def test_verify_warns_on_malformed_addoninfo_json(tmp_path, capsys) -> None:
    bin64, addon_dir = _fake_addon(tmp_path)
    (addon_dir / "addoninfo.json").write_text("{ this is not json", encoding="utf-8")
    cfg_path = _cfg_for(tmp_path, bin64)
    parser = build_parser()
    args = parser.parse_args(["verify", "myaddon"])
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 1
    err = capsys.readouterr().err
    assert "addoninfo" in err.lower()
    assert "malformed" in err.lower()


def test_verify_returns_report_object_for_programmatic_use(tmp_path) -> None:
    bin64, addon_dir = _fake_addon(tmp_path)
    cfg = Config(cs2_bin_path=str(bin64))
    report = verify_cmd.verify_addon(cfg, "myaddon")
    assert isinstance(report, verify_cmd.VerifyReport)
    assert report.addon_dir == addon_dir
    assert isinstance(report.issues, list)
