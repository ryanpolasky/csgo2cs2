from __future__ import annotations

import argparse
import json
import os
import zipfile
from pathlib import Path

from csgo2cs2.commands import bug_report_cmd


def _make_args(tmp_path: Path, config_path: Path = None, **overrides) -> argparse.Namespace:
    ns = argparse.Namespace(
        config=str(config_path) if config_path else None,
        verbose=False,
        command="bug-report",
        output=None,
        logs=5,
        manifests=5,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _write_config(tmp_path: Path, workspace: Path) -> Path:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"workspace_dir": str(workspace)}),
        encoding="utf-8",
    )
    return cfg_path


def test_bug_report_creates_zip(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg_path = _write_config(tmp_path, workspace)
    out_path = tmp_path / "report.zip"
    args = _make_args(tmp_path, cfg_path, output=str(out_path))
    rc = bug_report_cmd.run(args)
    assert rc == 0
    assert out_path.exists()

    with zipfile.ZipFile(out_path) as zf:
        names = set(zf.namelist())
    # essential members
    assert "summary.json" in names
    assert "env.txt" in names
    assert "config.json" in names


def test_bug_report_includes_logs(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    logs_dir = workspace / "logs"
    logs_dir.mkdir(parents=True)
    for i in range(3):
        f = logs_dir / f"run-{i:02d}.log"
        f.write_text(f"log content {i}", encoding="utf-8")
        os.utime(f, (1_000_000 + i, 1_000_000 + i))

    out_path = tmp_path / "report.zip"
    cfg_path = _write_config(tmp_path, workspace)
    rc = bug_report_cmd.run(_make_args(tmp_path, cfg_path, output=str(out_path)))
    assert rc == 0
    with zipfile.ZipFile(out_path) as zf:
        names = zf.namelist()
    assert any(n.startswith("logs/") for n in names)


def test_bug_report_respects_log_limit(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    logs_dir = workspace / "logs"
    logs_dir.mkdir(parents=True)
    for i in range(10):
        f = logs_dir / f"run-{i:02d}.log"
        f.write_text(f"log {i}", encoding="utf-8")
        os.utime(f, (1_000_000 + i, 1_000_000 + i))

    out_path = tmp_path / "report.zip"
    cfg_path = _write_config(tmp_path, workspace)
    rc = bug_report_cmd.run(_make_args(tmp_path, cfg_path, output=str(out_path), logs=3))
    assert rc == 0
    with zipfile.ZipFile(out_path) as zf:
        log_entries = [n for n in zf.namelist() if n.startswith("logs/")]
    assert len(log_entries) == 3


def test_bug_report_includes_manifests(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    wid_dir = workspace / "12345"
    wid_dir.mkdir()
    (wid_dir / "manifest.json").write_text(
        json.dumps(
            {
                "workshop_id": "12345",
                "addon_name": "ad",
                "copied_files": [],
                "patched_files": [],
                "renamed_files": [],
            }
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "report.zip"
    cfg_path = _write_config(tmp_path, workspace)
    rc = bug_report_cmd.run(_make_args(tmp_path, cfg_path, output=str(out_path)))
    assert rc == 0
    with zipfile.ZipFile(out_path) as zf:
        names = zf.namelist()
    assert "manifests/12345.manifest.json" in names


def test_env_dump_redacts_secrets(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("STEAM_GUARD", "ABCDE")
    monkeypatch.setenv("STEAM_API_KEY", "DEADBEEF")
    out_path = tmp_path / "report.zip"
    cfg_path = _write_config(tmp_path, workspace)
    bug_report_cmd.run(_make_args(tmp_path, cfg_path, output=str(out_path)))
    with zipfile.ZipFile(out_path) as zf:
        env = zf.read("env.txt").decode("utf-8")
    assert "ABCDE" not in env
    assert "DEADBEEF" not in env
    assert "<redacted>" in env


def test_summary_includes_version_and_platform(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    out_path = tmp_path / "report.zip"
    cfg_path = _write_config(tmp_path, workspace)
    bug_report_cmd.run(_make_args(tmp_path, cfg_path, output=str(out_path)))
    with zipfile.ZipFile(out_path) as zf:
        summary = json.loads(zf.read("summary.json").decode("utf-8"))
    assert "csgo2cs2_version" in summary
    assert "python_version" in summary
    assert "platform" in summary
    assert "argv" in summary


def test_default_output_path_under_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg_path = _write_config(tmp_path, workspace)
    rc = bug_report_cmd.run(_make_args(tmp_path, cfg_path))
    assert rc == 0
    out_dir = workspace / "bug-reports"
    files = list(out_dir.glob("bug-report-*.zip"))
    assert len(files) == 1
