# tests for `csgo2cs2 launch`. cross-platform; never actually invokes
# cs2.exe (always uses --print-only or simulates a non-windows host).

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import pytest

from csgo2cs2.cli import build_parser
from csgo2cs2.commands import launch_cmd
from csgo2cs2.config import Config, save_config


def _fake_install(tmp_path: Path, addon: str, vmaps: list[str]) -> Tuple[Path, Path, Path]:
    install = tmp_path / "Counter-Strike Global Offensive"
    bin64 = install / "game" / "bin" / "win64"
    bin64.mkdir(parents=True)
    # touch a fake cs2 binary so resolve_cs2_executable picks it up.
    fake_exe_name = "cs2.exe" if any(_p.name == "win64" for _p in [bin64]) else "cs2"
    (bin64 / fake_exe_name).write_text("# stub", encoding="utf-8")
    (bin64 / "cs2").write_text("# stub", encoding="utf-8")  # also create the unix-style name
    addon_dir = install / "game" / "csgo_addons" / addon
    (addon_dir / "maps").mkdir(parents=True)
    for mapname in vmaps:
        (addon_dir / "maps" / f"{mapname}.vmap").write_text("# vmap", encoding="utf-8")
    return install, bin64, addon_dir


def _ns_for_launch(parser, *args):
    return parser.parse_args(["launch", *args])


def test_resolve_addon_dir_uses_explicit_addons_path(tmp_path: Path) -> None:
    addons = tmp_path / "weird" / "addons"
    addons.mkdir(parents=True)
    cfg = Config(cs2_addons_path=str(addons))
    got = launch_cmd.resolve_addon_dir(cfg, "myaddon")
    assert got == addons / "myaddon"


def test_resolve_addon_dir_derives_from_bin_path(tmp_path: Path) -> None:
    install, bin64, addon_dir = _fake_install(tmp_path, "myaddon", ["de_dust2"])
    cfg = Config(cs2_bin_path=str(bin64))
    got = launch_cmd.resolve_addon_dir(cfg, "myaddon")
    assert got == addon_dir


def test_resolve_addon_dir_returns_none_when_unconfigured() -> None:
    assert launch_cmd.resolve_addon_dir(Config(), "myaddon") is None


def test_autodetect_picks_first_vmap(tmp_path: Path) -> None:
    _, _, addon_dir = _fake_install(tmp_path, "a", ["aim_redline", "de_dust2"])
    detected, alts = launch_cmd.autodetect_mapname(addon_dir)
    # sorted alphabetically.
    assert detected == "aim_redline"
    assert alts == ["aim_redline", "de_dust2"]


def test_autodetect_handles_no_maps(tmp_path: Path) -> None:
    addon_dir = tmp_path / "addon"
    addon_dir.mkdir()
    detected, alts = launch_cmd.autodetect_mapname(addon_dir)
    assert detected is None
    assert alts == []


def test_build_cmdline_includes_addon_and_map(tmp_path: Path) -> None:
    exe = tmp_path / "cs2.exe"
    cmd = launch_cmd.build_cmdline(exe, "myaddon", "de_dust2", hammer=False)
    assert cmd[0] == str(exe)
    assert "-game" in cmd
    assert "csgo" in cmd
    assert "-addon" in cmd
    assert "myaddon" in cmd
    assert "+map" in cmd
    assert "de_dust2" in cmd


def test_build_cmdline_hammer_omits_map(tmp_path: Path) -> None:
    exe = tmp_path / "cs2.exe"
    cmd = launch_cmd.build_cmdline(exe, "myaddon", "de_dust2", hammer=True)
    assert cmd[0] == str(exe)
    assert "-tools" in cmd
    assert "+map" not in cmd  # workshop tools mode ignores +map


def test_print_only_does_not_invoke_subprocess(monkeypatch, tmp_path, capsys) -> None:
    install, bin64, _ = _fake_install(tmp_path, "myaddon", ["de_dust2"])
    cfg = Config(cs2_bin_path=str(bin64))
    cfg_path = tmp_path / "cfg.json"
    save_config(cfg, str(cfg_path))

    spy_called = {"yes": False}

    def fake_popen(*_a, **_kw):
        spy_called["yes"] = True
        raise AssertionError("subprocess.Popen should not be called with --print-only")

    monkeypatch.setattr(launch_cmd.subprocess, "Popen", fake_popen)

    parser = build_parser()
    args = _ns_for_launch(parser, "myaddon", "--print-only")
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 0
    assert spy_called["yes"] is False
    out = capsys.readouterr().out
    assert "myaddon" in out
    assert "+map" in out
    assert "de_dust2" in out


def test_unconfigured_cs2_bin_returns_2(tmp_path) -> None:
    cfg_path = tmp_path / "cfg.json"
    save_config(Config(), str(cfg_path))
    parser = build_parser()
    args = _ns_for_launch(parser, "myaddon", "--print-only")
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 2


def test_missing_addon_dir_returns_2(tmp_path) -> None:
    install, bin64, _addon_dir = _fake_install(tmp_path, "myaddon", ["de_dust2"])
    cfg = Config(cs2_bin_path=str(bin64))
    cfg_path = tmp_path / "cfg.json"
    save_config(cfg, str(cfg_path))
    parser = build_parser()
    args = _ns_for_launch(parser, "addon_does_not_exist", "--print-only")
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 2


def test_missing_vmap_returns_2_when_not_hammer(tmp_path) -> None:
    install, bin64, _ = _fake_install(tmp_path, "myaddon", [])  # no vmaps
    cfg = Config(cs2_bin_path=str(bin64))
    cfg_path = tmp_path / "cfg.json"
    save_config(cfg, str(cfg_path))
    parser = build_parser()
    args = _ns_for_launch(parser, "myaddon", "--print-only")
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 2


def test_hammer_mode_works_without_vmap(monkeypatch, tmp_path, capsys) -> None:
    install, bin64, _ = _fake_install(tmp_path, "myaddon", [])
    cfg = Config(cs2_bin_path=str(bin64))
    cfg_path = tmp_path / "cfg.json"
    save_config(cfg, str(cfg_path))

    monkeypatch.setattr(launch_cmd.subprocess, "Popen", lambda *_, **__: pytest.fail("nope"))

    parser = build_parser()
    args = _ns_for_launch(parser, "myaddon", "--hammer", "--print-only")
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "-tools" in out


def test_warn_when_multiple_vmaps_present(tmp_path, capsys) -> None:
    install, bin64, _ = _fake_install(tmp_path, "myaddon", ["aim_a", "aim_b"])
    cfg = Config(cs2_bin_path=str(bin64))
    cfg_path = tmp_path / "cfg.json"
    save_config(cfg, str(cfg_path))
    parser = build_parser()
    args = _ns_for_launch(parser, "myaddon", "--print-only")
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 0
    captured = capsys.readouterr()
    # warn() writes to stderr; the cmdline preview goes to stdout.
    assert "Multiple .vmap files" in captured.err
    assert "aim_a" in captured.out  # the chosen map ends up in the cmdline
