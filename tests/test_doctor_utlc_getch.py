# tests for the `utils/utlc.py` getch() UnicodeDecodeError hardening in
# `csgo2cs2 doctor --fix`. patches go in-place; we exercise them with a
# fake utlc.py next to a fake importer (no real CSGO install required).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from csgo2cs2.commands.doctor import (
    GETCH_BRITTLE,
    GETCH_SAFE_MARKER,
    _check_install_patches_silent,
    _patch_utlc_getch,
    _run_unfix,
    _summarize_patches,
    _utlc_candidates,
    _utlc_needs_getch_patch,
)
from csgo2cs2.utils.backup import backup_path_for


@dataclass
class FakeCfg:
    csgo_install_path: str | None
    cs2_bin_path: str | None
    import_script_path: str | None = None


# `utls.py` ships in https://github.com/andreaskeller96/cs2-import-scripts with
# TAB indentation; mirror that exactly so the patcher's anchor matches.
PRISTINE_UTLC = (
    "class KeyboardHandler(object):\n"
    "\tdef getch(self):\n"
    "\t\tif os.name == 'nt':\n"
    f"\t\t\t{GETCH_BRITTLE}\n"
    "\t\telse:\n"
    "\t\t\treturn sys.stdin.read(1)\n"
)


def _make_utlc(tmp_path: Path) -> tuple[Path, Path]:
    """Create a fake importer + utlc.py in the layout the doctor expects."""
    install = tmp_path / "csgo"
    scripts_dir = install / "game" / "csgo" / "scripts"
    scripts_dir.mkdir(parents=True)
    importer = scripts_dir / "import_map_community.py"
    importer.write_text("# fake importer", encoding="utf-8")
    utils_dir = scripts_dir / "utils"
    utils_dir.mkdir()
    utlc = utils_dir / "utlc.py"
    utlc.write_text(PRISTINE_UTLC, encoding="utf-8")
    return install, utlc


def test_utlc_candidates_includes_importer_sibling(tmp_path):
    install, utlc = _make_utlc(tmp_path)
    cfg = FakeCfg(csgo_install_path=str(install), cs2_bin_path=None)
    cands = _utlc_candidates(cfg)
    assert utlc in cands


def test_utlc_needs_getch_patch_detects_brittle_form(tmp_path):
    _, utlc = _make_utlc(tmp_path)
    assert _utlc_needs_getch_patch(utlc) is True


def test_utlc_needs_getch_patch_false_when_missing(tmp_path):
    missing = tmp_path / "no_such" / "utlc.py"
    assert _utlc_needs_getch_patch(missing) is False


def test_utlc_needs_getch_patch_false_when_already_patched(tmp_path):
    _, utlc = _make_utlc(tmp_path)
    # mark as already patched: write a sentinel containing the safety marker
    utlc.write_text(
        PRISTINE_UTLC.replace(
            GETCH_BRITTLE,
            "try:\n\t\t\t\t" + GETCH_BRITTLE + "\n\t\t\texcept UnicodeDecodeError:\n"
            "\t\t\t\treturn '\\r'",
        ),
        encoding="utf-8",
    )
    assert _utlc_needs_getch_patch(utlc) is False


def test_patch_utlc_getch_writes_safety_wrapper(tmp_path):
    _, utlc = _make_utlc(tmp_path)
    assert _patch_utlc_getch(utlc) is True
    patched = utlc.read_text(encoding="utf-8")
    # safety wrapper present
    assert GETCH_SAFE_MARKER in patched
    # original line still present (inside the try)
    assert GETCH_BRITTLE in patched
    # fallback returns '\r' (Enter)
    assert "return '\\r'" in patched
    # backup written so --unfix can restore
    assert backup_path_for(utlc).exists()


def test_patch_utlc_getch_idempotent(tmp_path):
    _, utlc = _make_utlc(tmp_path)
    assert _patch_utlc_getch(utlc) is True
    # second invocation should be a no-op
    assert _patch_utlc_getch(utlc) is False


def test_patch_utlc_getch_noop_when_anchor_missing(tmp_path):
    _, utlc = _make_utlc(tmp_path)
    utlc.write_text("# completely unexpected content\n", encoding="utf-8")
    # without the anchor line, we shouldn't touch the file
    assert _patch_utlc_getch(utlc) is False
    # and no backup should be created
    assert not backup_path_for(utlc).exists()


def test_silent_patches_utlc_when_fix_true(tmp_path):
    install, utlc = _make_utlc(tmp_path)
    cfg = FakeCfg(csgo_install_path=str(install), cs2_bin_path=None)
    issues: list[str] = []
    fixes: list[str] = []
    tracked = _check_install_patches_silent(cfg, fix=True, issues=issues, fixes_applied=fixes)

    # utlc was patched and surfaced as a fix
    assert any(str(utlc) in f for f in fixes)
    assert utlc in tracked
    # file is now hardened
    assert GETCH_SAFE_MARKER in utlc.read_text(encoding="utf-8")


def test_silent_reports_issue_when_fix_false(tmp_path):
    install, utlc = _make_utlc(tmp_path)
    cfg = FakeCfg(csgo_install_path=str(install), cs2_bin_path=None)
    issues: list[str] = []
    fixes: list[str] = []
    _check_install_patches_silent(cfg, fix=False, issues=issues, fixes_applied=fixes)

    assert any("getch" in i for i in issues)
    assert not fixes
    # file untouched
    assert GETCH_SAFE_MARKER not in utlc.read_text(encoding="utf-8")


def test_summarize_patches_reports_utlc_state(tmp_path):
    install, utlc = _make_utlc(tmp_path)
    cfg = FakeCfg(csgo_install_path=str(install), cs2_bin_path=None)
    summary = _summarize_patches(cfg)
    assert summary["utlc_getch"] is not None
    assert summary["utlc_getch"]["patched"] is False
    # after patching, summary flips to patched=True
    _patch_utlc_getch(utlc)
    summary = _summarize_patches(cfg)
    assert summary["utlc_getch"]["patched"] is True


def test_unfix_restores_utlc_from_backup(tmp_path):
    install, utlc = _make_utlc(tmp_path)
    # simulate post-fix state: patched utlc + backup of original
    _patch_utlc_getch(utlc)
    assert backup_path_for(utlc).exists()
    bin_dir = install / "game" / "bin" / "win64"
    bin_dir.mkdir(parents=True)
    cfg = FakeCfg(csgo_install_path=str(install), cs2_bin_path=str(bin_dir))

    rc = _run_unfix(cfg)
    assert rc == 0
    # utlc restored to pristine
    assert utlc.read_text(encoding="utf-8") == PRISTINE_UTLC
    # backup consumed
    assert not backup_path_for(utlc).exists()
