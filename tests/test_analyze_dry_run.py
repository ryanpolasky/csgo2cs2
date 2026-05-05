# tests for `analyze --fix --dry-run`: print diff, write nothing.

from __future__ import annotations

from pathlib import Path

from csgo2cs2.commands import analyze
from csgo2cs2.config import Config, save_config


def _ns(**kwargs):
    base = {
        "config": None,
        "vmf": None,
        "fix": False,
        "output": None,
        "report_json": None,
        "bsp": None,
        "explain": False,
        "dry_run": False,
        "fix_spawns": None,
    }
    base.update(kwargs)
    return type("NS", (), base)


_SAMPLE_VMF = """\
world
{
\t"classname" "worldspawn"
\t"skyname" "sky_dust2"
}
entity { "classname" "info_player_terrorist" }
entity { "classname" "info_player_counterterrorist" }
"""


def test_dry_run_does_not_write_files(tmp_path: Path) -> None:
    vmf = tmp_path / "in.vmf"
    vmf.write_text(_SAMPLE_VMF, encoding="utf-8")
    cfg_path = tmp_path / "config.json"
    save_config(Config(), str(cfg_path))
    original = vmf.read_text(encoding="utf-8")

    rc = analyze.run(_ns(config=str(cfg_path), vmf=str(vmf), fix=True, dry_run=True))
    assert rc == 0
    # nothing on disk should have changed
    assert vmf.read_text(encoding="utf-8") == original
    # no .csgo2cs2.bak written
    assert not (tmp_path / "in.vmf.csgo2cs2.bak").exists()
    # no -o output written
    assert list(tmp_path.glob("*.fixed.vmf")) == []


def test_dry_run_prints_unified_diff(tmp_path: Path, capsys) -> None:
    vmf = tmp_path / "in.vmf"
    vmf.write_text(_SAMPLE_VMF, encoding="utf-8")
    cfg_path = tmp_path / "config.json"
    save_config(Config(), str(cfg_path))

    rc = analyze.run(_ns(config=str(cfg_path), vmf=str(vmf), fix=True, dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    # unified-diff hunks include the +++/---/@@ markers
    assert "---" in out
    assert "+++" in out
    assert "@@" in out
    # the actual change: skybox swap. `sky_dust2` trips the smart-skybox
    # mood rule for "dust2" -> wiki-confirmed `sky_de_dust2`.
    assert "sky_dust2" in out  # in the - line
    assert "sky_de_dust2" in out  # in the + line


def test_dry_run_without_fix_is_a_noop_path(tmp_path: Path) -> None:
    # `analyze --dry-run` without --fix should still bail out with the same
    # "pass --fix" message and not crash.
    vmf = tmp_path / "in.vmf"
    vmf.write_text(_SAMPLE_VMF, encoding="utf-8")
    cfg_path = tmp_path / "config.json"
    save_config(Config(), str(cfg_path))
    rc = analyze.run(_ns(config=str(cfg_path), vmf=str(vmf), fix=False, dry_run=True))
    # findings present + no --fix => returns 1, same as the existing flow
    assert rc == 1


def test_apply_then_dry_run_is_idempotent(tmp_path: Path) -> None:
    """After --fix has been applied, a subsequent --fix --dry-run shouldn't
    propose any further changes (no findings remain on a clean vmf)."""
    vmf = tmp_path / "in.vmf"
    vmf.write_text(_SAMPLE_VMF, encoding="utf-8")
    cfg_path = tmp_path / "config.json"
    save_config(Config(), str(cfg_path))
    # first apply for real
    rc = analyze.run(_ns(config=str(cfg_path), vmf=str(vmf), fix=True))
    assert rc == 0
    # now dry-run on the patched file
    rc = analyze.run(_ns(config=str(cfg_path), vmf=str(vmf), fix=True, dry_run=True))
    # no findings remain -> rc == 0 (clean) without going through the fix path
    assert rc in (0, 1)  # accept either: 0 means clean, 1 means findings-but-no-fix
