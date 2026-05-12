# tests for `csgo2cs2 doctor --json`. cross-platform; uses a fake
# install dir so we don't need real cs2 / steamcmd / java.

from __future__ import annotations

import json
from pathlib import Path

from csgo2cs2.cli import build_parser
from csgo2cs2.config import Config, save_config


def _fake_install(tmp_path: Path) -> tuple[Path, Path]:
    install = tmp_path / "csgo"
    scripts = install / "game" / "csgo" / "scripts"
    scripts.mkdir(parents=True)
    bin_dir = install / "game" / "bin" / "win64"
    bin_dir.mkdir(parents=True)
    importer = scripts / "import_map_community.py"
    importer.write_text("clean\n", encoding="utf-8")
    return install, bin_dir


def _cfg(tmp_path: Path) -> Path:
    install, bin_dir = _fake_install(tmp_path)
    cfg = Config(
        csgo_install_path=str(install),
        cs2_bin_path=str(bin_dir),
        workspace_dir=str(tmp_path / "ws"),
    )
    cfg_path = tmp_path / "cfg.json"
    save_config(cfg, str(cfg_path))
    return cfg_path


def test_doctor_json_emits_structured_report(tmp_path: Path, capsys) -> None:
    cfg_path = _cfg(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["doctor", "--json"])
    args.config = str(cfg_path)
    rc = args.func(args)
    out = capsys.readouterr().out
    payload = json.loads(out)
    # the actual rc depends on the host's tools (java, steamcmd etc.)
    # so we just check structure here, not the issue count.
    assert rc in (0, 1)
    assert payload["schema_version"] == 1
    assert "csgo2cs2_version" in payload
    assert "tools" in payload
    assert "install" in payload
    assert "install_patches" in payload
    assert "summary" in payload
    assert "ok" in payload["summary"]
    assert "issue_count" in payload["summary"]


def test_doctor_json_install_patches_section(tmp_path: Path, capsys) -> None:
    cfg_path = _cfg(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["doctor", "--json"])
    args.config = str(cfg_path)
    args.func(args)
    payload = json.loads(capsys.readouterr().out)
    patches = payload["install_patches"]
    assert patches["import_map_community_py"] is not None
    assert patches["import_map_community_py"]["patched"] is True
    assert patches["vpk_signatures"] is not None


def test_doctor_json_fix_records_drift_and_reports(tmp_path: Path, capsys) -> None:
    cfg_path = _cfg(tmp_path)
    parser = build_parser()
    # first run --fix --json
    args = parser.parse_args(["doctor", "--fix", "--json"])
    args.config = str(cfg_path)
    args.func(args)
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload["fixes_applied"], list)
    assert payload["summary"]["fixes_applied_count"] == len(payload["fixes_applied"])
    # drift state file should exist now
    drift_state = tmp_path / "ws" / ".csgo2cs2_drift.json"
    assert drift_state.exists()


def test_doctor_json_tools_flags_required_vs_optional(tmp_path: Path, capsys) -> None:
    """`vpkedit` / `bspzip` are optional accelerators; the report must
    surface them with `required=False` so consumers can ignore them when
    they're not configured. SteamCMD + BSPSource stay `required=True`."""
    cfg_path = _cfg(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["doctor", "--json"])
    args.config = str(cfg_path)
    args.func(args)
    payload = json.loads(capsys.readouterr().out)
    tools = payload["tools"]
    # required tools are flagged as such
    assert tools["steamcmd"]["required"] is True
    assert tools["bspsource"]["required"] is True
    # optional tools are flagged false so cli consumers can gate on it
    assert tools["vpkedit"]["required"] is False
    assert tools["bspzip"]["required"] is False
    # and missing optional tools never appear in the issue list
    issues_blob = " ".join(payload["issues"])
    assert "vpkedit" not in issues_blob.lower()
    assert "bspzip" not in issues_blob.lower()


def test_doctor_json_mutually_exclusive_flags(tmp_path: Path, capsys) -> None:
    cfg_path = _cfg(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["doctor", "--fix", "--unfix", "--json"])
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 2
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "error" in payload
