# tests for the new list / status / init commands.

from __future__ import annotations

import json
from pathlib import Path

from csgo2cs2.commands import init_cmd, list_cmd, status_cmd
from csgo2cs2.config import Config, save_config
from csgo2cs2.utils.manifest import PortManifest


def _ns(**kwargs):
    return type("NS", (), kwargs)


def _seed_manifest(workspace: Path, workshop_id: str, addon: str) -> Path:
    target = workspace / workshop_id
    target.mkdir(parents=True)
    m = PortManifest(workshop_id=workshop_id, addon_name=addon)
    p = target / "manifest.json"
    m.save(p)
    return p


def test_list_no_workspace_returns_zero(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    save_config(Config(workspace_dir=str(tmp_path / "missing")), str(cfg_path))
    rc = list_cmd.run(_ns(config=str(cfg_path), paths_only=False))
    assert rc == 0


def test_list_finds_seeded_manifest(tmp_path: Path, capsys):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed_manifest(workspace, "12345", "my_addon")
    cfg_path = tmp_path / "config.json"
    save_config(Config(workspace_dir=str(workspace)), str(cfg_path))
    rc = list_cmd.run(_ns(config=str(cfg_path), paths_only=False))
    assert rc == 0


def test_list_paths_only_prints_paths(tmp_path: Path, capsys):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    manifest_path = _seed_manifest(workspace, "12345", "my_addon")
    cfg_path = tmp_path / "config.json"
    save_config(Config(workspace_dir=str(workspace)), str(cfg_path))
    rc = list_cmd.run(_ns(config=str(cfg_path), paths_only=True))
    assert rc == 0
    captured = capsys.readouterr()
    assert str(manifest_path) in captured.out


def test_status_missing_manifest_returns_one(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    save_config(Config(workspace_dir=str(tmp_path / "ws")), str(cfg_path))
    rc = status_cmd.run(_ns(config=str(cfg_path), url_or_id="99999"))
    assert rc == 1


def test_status_reads_seeded_manifest(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed_manifest(workspace, "12345", "my_addon")
    cfg_path = tmp_path / "config.json"
    save_config(Config(workspace_dir=str(workspace)), str(cfg_path))
    rc = status_cmd.run(_ns(config=str(cfg_path), url_or_id="12345"))
    assert rc == 0


def test_status_accepts_local_id(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _seed_manifest(workspace, "local-test_map", "my_addon")
    cfg_path = tmp_path / "config.json"
    save_config(Config(workspace_dir=str(workspace)), str(cfg_path))
    rc = status_cmd.run(_ns(config=str(cfg_path), url_or_id="local-test_map"))
    assert rc == 0


def test_init_autodetect_picks_up_csgo_install(monkeypatch, tmp_path: Path):
    # fabricate a steam tree so find_csgo_install returns a known path
    csgo = tmp_path / "Counter-Strike Global Offensive"
    csgo.mkdir()
    (csgo / "game" / "csgo_addons").mkdir(parents=True)
    (csgo / "game" / "bin" / "win64").mkdir(parents=True)
    (csgo / "bin").mkdir()
    monkeypatch.setattr(init_cmd, "find_csgo_install", lambda: csgo)
    monkeypatch.setattr(init_cmd, "find_steamcmd", lambda: None)
    cfg_path = tmp_path / "config.json"
    rc = init_cmd.run(_ns(config=str(cfg_path), force=False, interactive=False))
    assert rc == 0
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["csgo_install_path"] == str(csgo)
    assert data["cs2_addons_path"] == str(csgo / "game" / "csgo_addons")
    assert data["cs2_bin_path"] == str(csgo / "game" / "bin" / "win64")
    assert data["legacy_csgo_bin_path"] == str(csgo / "bin")


def test_init_autodetect_no_overwrite_existing_value(monkeypatch, tmp_path: Path):
    # write a config with an existing csgo_install_path
    cfg_path = tmp_path / "config.json"
    save_config(Config(csgo_install_path="/preset/path"), str(cfg_path))
    csgo = tmp_path / "Counter-Strike Global Offensive"
    csgo.mkdir()
    monkeypatch.setattr(init_cmd, "find_csgo_install", lambda: csgo)
    monkeypatch.setattr(init_cmd, "find_steamcmd", lambda: None)
    rc = init_cmd.run(_ns(config=str(cfg_path), force=False, interactive=False))
    assert rc == 0
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["csgo_install_path"] == "/preset/path"
