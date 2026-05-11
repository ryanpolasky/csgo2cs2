# tests for the patch-drift state machinery + doctor's drift warning.
#
# the drift module is pure-python and easily exercised in isolation.
# we then drive _check_install_patches (the doctor sub-helper) via a
# FakeCfg to verify the round-trip: --fix records state, then a
# subsequent doctor run with the file mutated reports drift.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from csgo2cs2.commands import doctor as doctor_mod
from csgo2cs2.utils import drift


@dataclass
class FakeCfg:
    csgo_install_path: str | None
    cs2_bin_path: str | None
    workspace_dir: str
    import_script_path: str | None = None


def _make_install(tmp_path: Path) -> tuple[FakeCfg, Path, Path]:
    install = tmp_path / "csgo"
    scripts = install / "game" / "csgo" / "scripts"
    scripts.mkdir(parents=True)
    bin_dir = install / "game" / "bin" / "win64"
    bin_dir.mkdir(parents=True)
    importer = scripts / "import_map_community.py"
    importer.write_text("clean code\n", encoding="utf-8")  # no .decode( -> patched state
    cfg = FakeCfg(
        csgo_install_path=str(install),
        cs2_bin_path=str(bin_dir),
        workspace_dir=str(tmp_path / "ws"),
    )
    return cfg, importer, bin_dir


# --- pure drift module ------------------------------------------------------


def test_state_round_trip_via_disk(tmp_path: Path) -> None:
    state = drift.DriftState()
    f = tmp_path / "x.py"
    f.write_text("hello\n")
    drift.record_fix(state, f)
    drift.save_state(state, tmp_path)

    loaded = drift.load_state(tmp_path)
    assert str(f.resolve()) in loaded.entries
    assert loaded.entries[str(f.resolve())].sha256 == state.entries[str(f.resolve())].sha256


def test_load_returns_empty_state_for_missing_file(tmp_path: Path) -> None:
    state = drift.load_state(tmp_path)
    assert state.entries == {}


def test_load_returns_empty_state_for_corrupt_file(tmp_path: Path) -> None:
    p = tmp_path / drift.DRIFT_STATE_FILENAME
    p.write_text("{not json")
    state = drift.load_state(tmp_path)
    assert state.entries == {}


def test_check_drift_reports_unchanged(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("v1")
    state = drift.DriftState()
    drift.record_fix(state, f)
    [check] = drift.check_drift(state, [f])
    assert check.drifted is False


def test_check_drift_reports_changed(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("v1")
    state = drift.DriftState()
    drift.record_fix(state, f)
    f.write_text("v2 (steam reverted us)")
    [check] = drift.check_drift(state, [f])
    assert check.drifted is True
    assert "sha256 changed" in check.reason


def test_check_drift_reports_missing_file(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("v1")
    state = drift.DriftState()
    drift.record_fix(state, f)
    f.unlink()
    [check] = drift.check_drift(state, [f])
    assert check.drifted is True
    assert "missing" in check.reason


def test_check_drift_skips_untracked_paths(tmp_path: Path) -> None:
    f = tmp_path / "never_fixed.py"
    f.write_text("untracked")
    state = drift.DriftState()
    # never recorded -> drift check should return no entry for it
    assert drift.check_drift(state, [f]) == []


# --- doctor integration -----------------------------------------------------


def test_doctor_fix_records_drift_state(tmp_path: Path) -> None:
    cfg, importer, _ = _make_install(tmp_path)
    issues: list = []
    fixes: list = []
    tracked = doctor_mod._check_install_patches(cfg, fix=True, issues=issues, fixes_applied=fixes)
    assert importer in tracked
    doctor_mod._record_drift_state(cfg, tracked)

    state = drift.load_state(Path(cfg.workspace_dir))
    key = str(importer.resolve())
    assert key in state.entries


def test_doctor_drift_warning_on_reverted_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    cfg, importer, _ = _make_install(tmp_path)
    # simulate first --fix: importer is already clean (no .decode), we
    # just record it.
    tracked = doctor_mod._check_install_patches(cfg, fix=True, issues=[], fixes_applied=[])
    doctor_mod._record_drift_state(cfg, tracked)
    capsys.readouterr()  # discard

    # steam ships an update that puts back the .decode() patch target
    importer.write_text("import sys\nsys.argv[1].decode('utf-8')\n", encoding="utf-8")

    # plain doctor: drift check should emit the warn line
    tracked2 = doctor_mod._check_install_patches(cfg, fix=False, issues=[], fixes_applied=[])
    doctor_mod._check_drift_state(cfg, tracked2)
    err = capsys.readouterr().err
    assert "patch drift detected" in err
    assert "import_map_community.py" in err


def test_doctor_drift_silent_when_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cfg, importer, _ = _make_install(tmp_path)
    tracked = doctor_mod._check_install_patches(cfg, fix=True, issues=[], fixes_applied=[])
    doctor_mod._record_drift_state(cfg, tracked)
    capsys.readouterr()

    # plain doctor immediately after --fix: no drift expected
    tracked2 = doctor_mod._check_install_patches(cfg, fix=False, issues=[], fixes_applied=[])
    doctor_mod._check_drift_state(cfg, tracked2)
    err = capsys.readouterr().err
    assert "patch drift detected" not in err



def test_doctor_fix_patches_cached_importer_via_import_script_path(tmp_path: Path) -> None:
    """Regression: `tools install` writes the importer into the tools
    cache and records it as `cfg.import_script_path`. The port pipeline
    runs *that* copy, so `doctor --fix` has to patch the same file --
    not just the legacy in-CS:GO-install locations. Without this, the
    `.decode()` patch never reaches the script that actually executes
    and the import stage crashes mid-port on Windows."""
    install = tmp_path / "csgo"  # empty install -- no legacy importer copy here
    install.mkdir()
    cached = tmp_path / "tools" / "import_map_community" / "import_map_community.py"
    cached.parent.mkdir(parents=True)
    cached.write_text("import sys\nsys.argv[1].decode('utf-8')\n", encoding="utf-8")

    cfg = FakeCfg(
        csgo_install_path=str(install),
        cs2_bin_path=None,
        workspace_dir=str(tmp_path / "ws"),
        import_script_path=str(cached),
    )
    tracked = doctor_mod._check_install_patches(cfg, fix=True, issues=[], fixes_applied=[])
    assert cached in tracked
    assert ".decode(" not in cached.read_text(encoding="utf-8")
