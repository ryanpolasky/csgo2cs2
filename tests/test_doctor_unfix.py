# tests for `csgo2cs2 doctor --unfix`.
#
# we don't actually run the doctor's environment checks (those are gated by
# `--fix` / `--unfix` and the env-checks early-return). instead we exercise
# `_run_unfix` directly with a fake install dir, so the test is platform-
# agnostic.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from csgo2cs2.commands.doctor import _run_unfix
from csgo2cs2.utils.backup import backup_path_for


@dataclass
class FakeCfg:
    csgo_install_path: str | None
    cs2_bin_path: str | None
    import_script_path: str | None = None


def _make_install(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    install = tmp_path / "csgo"
    scripts_dir = install / "game" / "csgo" / "scripts"
    scripts_dir.mkdir(parents=True)
    bin_dir = install / "game" / "bin" / "win64"
    bin_dir.mkdir(parents=True)
    importer = scripts_dir / "import_map_community.py"
    sigs = bin_dir / "vpk.signatures"
    return install, importer, bin_dir, sigs


def test_unfix_no_install_returns_failure():
    cfg = FakeCfg(csgo_install_path=None, cs2_bin_path=None)
    rc = _run_unfix(cfg)
    assert rc == 1


def test_unfix_restores_importer_from_backup(tmp_path):
    install, importer, bin_dir, sigs = _make_install(tmp_path)
    importer.write_text("PATCHED\n", encoding="utf-8")
    backup = backup_path_for(importer)
    backup.write_text("ORIGINAL with .decode('utf-8')\n", encoding="utf-8")

    cfg = FakeCfg(csgo_install_path=str(install), cs2_bin_path=str(bin_dir))
    rc = _run_unfix(cfg)
    assert rc == 0
    assert importer.read_text(encoding="utf-8") == "ORIGINAL with .decode('utf-8')\n"
    # backup is consumed so a future --fix starts clean
    assert not backup.exists()


def test_unfix_renames_signatures_old_back(tmp_path):
    install, importer, bin_dir, sigs = _make_install(tmp_path)
    importer.write_text("anything\n", encoding="utf-8")  # no backup -> noop on importer
    renamed = sigs.with_suffix(sigs.suffix + ".old")
    renamed.write_bytes(b"signature blob")
    backup = backup_path_for(sigs)
    backup.write_bytes(b"older blob backup")

    cfg = FakeCfg(csgo_install_path=str(install), cs2_bin_path=str(bin_dir))
    rc = _run_unfix(cfg)
    assert rc == 0
    assert sigs.exists()
    assert sigs.read_bytes() == b"signature blob"
    assert not renamed.exists()
    assert not backup.exists()


def test_unfix_full_round_trip_after_fix(tmp_path):
    install, importer, bin_dir, sigs = _make_install(tmp_path)
    # simulate post-`--fix` state: patched importer + .old signature + backups.
    importer.write_text("patched, no .decode\n", encoding="utf-8")
    backup_path_for(importer).write_text("with .decode('utf-8')\n", encoding="utf-8")
    renamed = sigs.with_suffix(sigs.suffix + ".old")
    renamed.write_bytes(b"sig")
    backup_path_for(sigs).write_bytes(b"sig backup")

    cfg = FakeCfg(csgo_install_path=str(install), cs2_bin_path=str(bin_dir))
    rc = _run_unfix(cfg)
    assert rc == 0
    # importer restored
    assert importer.read_text(encoding="utf-8") == "with .decode('utf-8')\n"
    assert not backup_path_for(importer).exists()
    # signature put back in place
    assert sigs.exists()
    assert sigs.read_bytes() == b"sig"
    assert not renamed.exists()
    assert not backup_path_for(sigs).exists()


def test_unfix_idempotent_when_nothing_to_do(tmp_path):
    install, importer, bin_dir, sigs = _make_install(tmp_path)
    # importer has no backup, no signatures.old in place: nothing to reverse
    importer.write_text("clean\n", encoding="utf-8")

    cfg = FakeCfg(csgo_install_path=str(install), cs2_bin_path=str(bin_dir))
    rc = _run_unfix(cfg)
    # idempotent: still exit 0 even though nothing changed
    assert rc == 0
    assert importer.read_text(encoding="utf-8") == "clean\n"


def test_unfix_handles_signatures_present_alongside_old(tmp_path):
    install, importer, bin_dir, sigs = _make_install(tmp_path)
    importer.write_text("anything\n", encoding="utf-8")
    # both files exist (rare; user manually intervened or steam shipped a new
    # signature): keep the live one, drop the .old.
    sigs.write_bytes(b"current")
    renamed = sigs.with_suffix(sigs.suffix + ".old")
    renamed.write_bytes(b"stale")

    cfg = FakeCfg(csgo_install_path=str(install), cs2_bin_path=str(bin_dir))
    rc = _run_unfix(cfg)
    assert rc == 0
    assert sigs.read_bytes() == b"current"
    assert not renamed.exists()
