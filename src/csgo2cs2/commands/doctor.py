# environment and install patch checks.

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

from .. import __version__
from ..config import load_config
from ..logging_utils import error, header, info, success, warn
from ..platform_check import is_windows, os_label
from ..tools.bspsource import BSPSource
from ..tools.bspzip import BSPZip
from ..tools.steamcmd import SteamCMD
from ..tools.vpkedit import VPKEdit
from ..utils.backup import backup_file, backup_path_for, has_marker, restore_file
from ..utils.drift import check_drift, load_state, record_fix, save_state
from ..utils.steam import find_csgo_install

DECODE_MARKER = ".decode("

# Anchor in `utils/utlc.py` that's brittle on Windows when an extended-key
# byte (0xe0/0x00 prefix for arrow / function / Page Up/Down keys) is in
# the console input buffer when getch() runs: the byte isn't valid utf-8
# and the decode raises. Replaced with a try/except that treats undecodable
# bytes as Enter so automation isn't killed by a stray keystroke.
GETCH_BRITTLE = "return msvcrt.getch().decode('utf-8')"
GETCH_SAFE_MARKER = "except UnicodeDecodeError"


def _utlc_candidates(cfg) -> List[Path]:
    """Candidate paths for the `utils/utlc.py` helper shipped alongside
    `import_map_community.py`. Same lookup as the importer itself --
    `utlc.py` lives next to it in `utils/`."""
    out: List[Path] = []
    for importer in _importer_candidates(cfg):
        cand = importer.parent / "utils" / "utlc.py"
        out.append(cand)
    return out


def _importer_candidates(cfg) -> List[Path]:
    """Candidate paths for `import_map_community.py`, in priority order:
    the path `tools install` recorded in config first, then the legacy
    in-CS:GO-install locations users may have pre-extracted into. The
    port pipeline executes whichever resolves to a real file, so
    `--fix` has to patch the same one."""
    out: List[Path] = []
    if cfg.import_script_path:
        out.append(Path(cfg.import_script_path))
    if cfg.csgo_install_path:
        install = Path(cfg.csgo_install_path)
        out.extend(
            [
                install / "game" / "csgo" / "scripts" / "import_map_community.py",
                install / "game" / "bin" / "win64" / "import_map_community.py",
            ]
        )
    return out


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "doctor",
        help="Check environment, tools, and CS2 install patches.",
    )
    p.add_argument(
        "--fix",
        action="store_true",
        help="Apply known reversible install patches with backups.",
    )
    p.add_argument(
        "--unfix",
        action="store_true",
        help=(
            "Reverse `--fix` mutations: restore the original "
            "import_map_community.py and rename vpk.signatures.old back "
            "to vpk.signatures so VAC-protected servers accept the install."
        ),
    )
    p.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help=(
            "Emit a structured JSON report of the doctor's findings instead "
            "of human-readable output. CI scripts can `jq '.summary.ok'` to "
            "gate builds on environment health."
        ),
    )
    p.set_defaults(func=run)


def _check_python_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _on_path(name: str) -> bool:
    return shutil.which(name) is not None


def _path_contains(p: str) -> bool:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    norm = os.path.normcase(os.path.normpath(p))
    return any(os.path.normcase(os.path.normpath(x)) == norm for x in parts if x)


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    issues: List[str] = []
    fixes_applied: List[str] = []

    if args.fix and args.unfix:
        if getattr(args, "emit_json", False):
            json.dump({"error": "--fix and --unfix are mutually exclusive"}, sys.stdout)
            sys.stdout.write("\n")
        else:
            error("--fix and --unfix are mutually exclusive.")
        return 2

    if args.unfix:
        return _run_unfix(cfg)

    if getattr(args, "emit_json", False):
        return _run_json(cfg, args.fix)

    header("Environment")
    info(f"OS: {os_label()}")
    info(f"Python: {sys.version.split()[0]} at {sys.executable}")

    if _check_python_module("colorama"):
        success("colorama is importable")
    else:
        warn("colorama is not installed (required by Valve's import script)")
        issues.append("Install colorama: `pip install colorama`")

    if _on_path("java"):
        success("java is on PATH (needed for BSPSource)")
    else:
        warn("java is not on PATH; BSPSource jar will not run")
        issues.append("Install a Java JRE and ensure `java` is on PATH")

    header("External Tools")
    # SteamCMD + BSPSource are required by the port pipeline (workshop
    # downloads + BSP decompile). VPKEdit + BSPZip are optional: extract
    # uses the built-in pakfile reader by default and never needs to
    # repack BSPs. Missing-optional cases are info-level so they don't
    # contribute to the issue count.
    for adapter in (
        SteamCMD(cfg.steamcmd_path),
        BSPSource(cfg.bspsource_path, java_path=cfg.java_path),
    ):
        st = adapter.status()
        if st.installed:
            success(f"{st.name}: {st.path}")
        else:
            warn(f"{st.name}: not configured or not found")
            issues.append(f"Set `{st.name}_path` in config or place {st.name} on PATH")

    for adapter in (
        VPKEdit(cfg.vpkedit_path),
        BSPZip(cfg.bspzip_path),
    ):
        st = adapter.status()
        if st.installed:
            success(f"{st.name}: {st.path} (optional)")
        else:
            info(f"{st.name}: not configured (optional; not used by the port pipeline)")

    header("CS:GO/CS2 Install")
    if cfg.csgo_install_path and Path(cfg.csgo_install_path).exists():
        success(f"csgo_install_path: {cfg.csgo_install_path}")
    else:
        warn("csgo_install_path is not set or does not exist")
        detected = find_csgo_install()
        if detected:
            info(f"detected install at {detected}; run `csgo2cs2 init` to record it")
        issues.append("Set `csgo_install_path` (or run `csgo2cs2 init` to auto-detect)")

    if cfg.cs2_bin_path:
        if Path(cfg.cs2_bin_path).exists():
            success(f"cs2_bin_path: {cfg.cs2_bin_path}")
            if is_windows() and not _path_contains(cfg.cs2_bin_path):
                warn("cs2_bin_path is not on PATH; Valve's import script needs it")
                issues.append(f"Add `{cfg.cs2_bin_path}` to PATH")
        else:
            warn(f"cs2_bin_path does not exist: {cfg.cs2_bin_path}")
            issues.append("Fix `cs2_bin_path` to point at <install>/game/bin/win64")
    else:
        warn("cs2_bin_path is not set")

    header("Install Patches")
    patched_paths = _check_install_patches(cfg, args.fix, issues, fixes_applied)
    if args.fix and patched_paths:
        _record_drift_state(cfg, patched_paths)
    elif not args.fix:
        _check_drift_state(cfg, patched_paths)
        info("Tip: `csgo2cs2 doctor --unfix` reverses these patches before going to VAC servers.")

    header("Summary")
    if fixes_applied:
        for fx in fixes_applied:
            success(f"applied: {fx}")
    if issues:
        for iss in issues:
            warn(iss)
        error(f"{len(issues)} issue(s) need attention.")
        return 1
    success("All checks passed.")
    return 0


# emit a structured json report capturing the same checks the human
# path performs. when `do_fix` is True, install patches are still
# applied (with the same backup semantics) and the fixes_applied list
# is included in the report.
def _run_json(cfg, do_fix: bool) -> int:
    issues: List[str] = []
    fixes_applied: List[str] = []
    report: Dict[str, Any] = {
        "schema_version": 1,
        "csgo2cs2_version": __version__,
        "os": os_label(),
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
        },
        "modules": {
            "colorama": _check_python_module("colorama"),
        },
        "tools": {},
        "install": {
            "csgo_install_path": cfg.csgo_install_path,
            "csgo_install_present": bool(
                cfg.csgo_install_path and Path(cfg.csgo_install_path).exists()
            ),
            "cs2_bin_path": cfg.cs2_bin_path,
            "cs2_bin_present": bool(cfg.cs2_bin_path and Path(cfg.cs2_bin_path).exists()),
            "cs2_bin_on_path": bool(cfg.cs2_bin_path and _path_contains(cfg.cs2_bin_path)),
            "java_on_path": _on_path("java"),
        },
    }

    # SteamCMD + BSPSource are required; missing them contributes to
    # the issue count. VPKEdit + BSPZip are optional accelerators (the
    # port pipeline falls back to the built-in pakfile reader) and only
    # carry a `required` flag in the report.
    required_adapters = (
        SteamCMD(cfg.steamcmd_path),
        BSPSource(cfg.bspsource_path, java_path=cfg.java_path),
    )
    optional_adapters = (
        VPKEdit(cfg.vpkedit_path),
        BSPZip(cfg.bspzip_path),
    )
    for adapter in required_adapters:
        st = adapter.status()
        report["tools"][st.name] = {
            "installed": st.installed,
            "path": str(st.path) if st.path else None,
            "required": True,
        }
        if not st.installed:
            issues.append(f"{st.name} not configured/found")
    for adapter in optional_adapters:
        st = adapter.status()
        report["tools"][st.name] = {
            "installed": st.installed,
            "path": str(st.path) if st.path else None,
            "required": False,
        }

    if not report["modules"]["colorama"]:
        issues.append("colorama not installed")
    if not report["install"]["java_on_path"]:
        issues.append("java not on PATH (BSPSource needs it)")
    if not report["install"]["csgo_install_present"]:
        issues.append("csgo_install_path missing or unset")
    if cfg.cs2_bin_path and not report["install"]["cs2_bin_present"]:
        issues.append("cs2_bin_path does not exist")
    if cfg.cs2_bin_path and is_windows() and not report["install"]["cs2_bin_on_path"]:
        issues.append("cs2_bin_path not on PATH")

    # install patches: state-only in json mode unless --fix is set
    patched_paths = _check_install_patches_silent(cfg, do_fix, issues, fixes_applied)
    report["install_patches"] = _summarize_patches(cfg)
    if do_fix and patched_paths:
        _record_drift_state(cfg, patched_paths)
    drift_results = _gather_drift(cfg, patched_paths)
    report["drift"] = drift_results
    report["fixes_applied"] = list(fixes_applied)
    report["issues"] = list(issues)
    report["summary"] = {
        "ok": len(issues) == 0,
        "issue_count": len(issues),
        "fixes_applied_count": len(fixes_applied),
        "drift_count": sum(1 for d in drift_results if d.get("drifted")),
    }

    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if not issues else 1


# silent variant of _check_install_patches: no human prints, same
# fix-side effects + tracked-paths return contract.
def _check_install_patches_silent(
    cfg, fix: bool, issues: List[str], fixes_applied: List[str]
) -> List[Path]:
    tracked: List[Path] = []
    importer = next((p for p in _importer_candidates(cfg) if p.exists()), None)
    if importer:
        tracked.append(importer)
        if has_marker(importer, DECODE_MARKER):
            if fix:
                _patch_remove_decode(importer)
                fixes_applied.append(f"patched {importer}")
            else:
                issues.append(f"{importer.name} unpatched")

    utlc = next((p for p in _utlc_candidates(cfg) if p.is_file()), None)
    if utlc:
        tracked.append(utlc)
        if _utlc_needs_getch_patch(utlc):
            if fix:
                if _patch_utlc_getch(utlc):
                    fixes_applied.append(f"patched {utlc}")
            else:
                issues.append(f"{utlc.name} getch() unpatched")

    if cfg.cs2_bin_path:
        sigs = Path(cfg.cs2_bin_path) / "vpk.signatures"
        renamed = sigs.with_suffix(sigs.suffix + ".old")
        tracked.append(renamed)
        if sigs.exists():
            if fix:
                backup_file(sigs)
                if renamed.exists():
                    renamed.unlink()
                sigs.rename(renamed)
                fixes_applied.append(f"renamed {sigs.name} -> {renamed.name}")
            else:
                issues.append("vpk.signatures present (not yet renamed)")
    return tracked


def _summarize_patches(cfg) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "import_map_community_py": None,
        "utlc_getch": None,
        "vpk_signatures": None,
    }
    for cand in _importer_candidates(cfg):
        if cand.exists():
            out["import_map_community_py"] = {
                "path": str(cand),
                "patched": not has_marker(cand, DECODE_MARKER),
            }
            break
    for cand in _utlc_candidates(cfg):
        if cand.is_file():
            text = cand.read_text(encoding="utf-8", errors="ignore")
            out["utlc_getch"] = {
                "path": str(cand),
                "patched": GETCH_SAFE_MARKER in text or GETCH_BRITTLE not in text,
            }
            break
    if cfg.cs2_bin_path:
        sigs = Path(cfg.cs2_bin_path) / "vpk.signatures"
        renamed = sigs.with_suffix(sigs.suffix + ".old")
        out["vpk_signatures"] = {
            "live_present": sigs.exists(),
            "renamed_present": renamed.exists(),
            "patched": (not sigs.exists()) and renamed.exists(),
        }
    return out


def _gather_drift(cfg, patched_paths: List[Path]) -> List[Dict[str, Any]]:
    workspace = Path(cfg.workspace_dir).expanduser()
    state = load_state(workspace)
    if not state.entries:
        return []
    return [
        {
            "path": r.path,
            "drifted": r.drifted,
            "last_fixed_at": r.last_fixed_at,
            "reason": r.reason,
        }
        for r in check_drift(state, patched_paths)
    ]


def _check_install_patches(
    cfg, fix: bool, issues: List[str], fixes_applied: List[str]
) -> List[Path]:
    """returns the list of paths whose post-fix state should be tracked
    for drift detection on subsequent runs."""
    tracked: List[Path] = []

    # import_map_community.py `.decode()` patch
    importer = next((p for p in _importer_candidates(cfg) if p.exists()), None)
    if importer:
        # we always track the importer path: when it's still patched
        # (success branch) drift will report unchanged; when it's been
        # unpatched (warn branch) and we have a prior baseline, drift
        # will surface that as "steam reverted this since last --fix".
        tracked.append(importer)
        if has_marker(importer, DECODE_MARKER):
            warn(f"{importer.name} still contains `.decode(` (needs patch)")
            if fix:
                _patch_remove_decode(importer)
                fixes_applied.append(f"patched {importer}")
            else:
                issues.append(
                    f"Run `csgo2cs2 doctor --fix` to remove .decode() from {importer.name}"
                )
        else:
            success(f"{importer.name} already patched (no `.decode(` found)")
    else:
        warn("Could not locate import_map_community.py under known paths")

    # utils/utlc.py getch() UnicodeDecodeError patch
    utlc = next((p for p in _utlc_candidates(cfg) if p.is_file()), None)
    if utlc:
        tracked.append(utlc)
        if _utlc_needs_getch_patch(utlc):
            warn(
                f"{utlc.name} getch() can crash on extended-key bytes "
                "(arrow / F-keys / Page Up/Down) in the console buffer"
            )
            if fix:
                if _patch_utlc_getch(utlc):
                    fixes_applied.append(f"patched {utlc}")
                else:
                    warn(f"{utlc.name}: getch line layout didn't match; no patch applied")
            else:
                issues.append(
                    f"Run `csgo2cs2 doctor --fix` to harden getch() in {utlc.name}"
                )
        else:
            success(f"{utlc.name} getch() already hardened (UnicodeDecodeError-safe)")
    else:
        info("utils/utlc.py not found next to importer; skipping getch hardening check")

    # vpk.signatures rename
    if cfg.cs2_bin_path:
        sigs = Path(cfg.cs2_bin_path) / "vpk.signatures"
        renamed = sigs.with_suffix(sigs.suffix + ".old")
        # track the renamed path so drift detection surfaces a returning
        # vpk.signatures as steam having reshipped it.
        tracked.append(renamed)
        if sigs.exists():
            warn("vpk.signatures is present (needs to be renamed)")
            if fix:
                backup_file(sigs)
                if renamed.exists():
                    renamed.unlink()
                sigs.rename(renamed)
                fixes_applied.append(f"renamed {sigs.name} -> {renamed.name}")
            else:
                issues.append(
                    "Run `csgo2cs2 doctor --fix` to rename vpk.signatures to vpk.signatures.old"
                )
        elif renamed.exists():
            success("vpk.signatures already renamed")
        else:
            info("vpk.signatures not found (CS2 may not require this on your version)")

    return tracked


# write the post-fix state to <workspace_dir>/.csgo2cs2_drift.json so
# subsequent doctor runs can detect when steam reverts our patches.
def _record_drift_state(cfg, patched_paths: List[Path]) -> None:
    workspace = Path(cfg.workspace_dir).expanduser()
    state = load_state(workspace)
    for p in patched_paths:
        record_fix(state, p)
    save_state(state, workspace)


# compare current state against the recorded post-fix state. when a
# tracked file's hash has drifted we surface it as a "steam likely
# reverted this; re-run --fix" warning, which is the most common cause
# of "i already ran doctor, why is import failing again" confusion.
def _check_drift_state(cfg, patched_paths: List[Path]) -> None:
    workspace = Path(cfg.workspace_dir).expanduser()
    state = load_state(workspace)
    if not state.entries:
        return
    results = check_drift(state, patched_paths)
    drifted = [r for r in results if r.drifted]
    if not drifted:
        return
    warn(
        "patch drift detected on "
        f"{len(drifted)} file(s) (steam likely reverted them in a recent update):"
    )
    for r in drifted:
        warn(f"  {Path(r.path).name}: {r.reason}")
    info("Tip: re-run `csgo2cs2 doctor --fix` to re-apply.")


# patch valve's script after creating a backup.
def _patch_remove_decode(path: Path) -> None:
    backup_file(path)
    text = path.read_text(encoding="utf-8")
    out_lines: List[str] = []
    for line in text.splitlines(keepends=True):
        if DECODE_MARKER in line:
            out_lines.append(_strip_decode(line))
        else:
            out_lines.append(line)
    path.write_text("".join(out_lines), encoding="utf-8")


def _utlc_needs_getch_patch(path: Path) -> bool:
    """True iff utlc.py contains the brittle getch decode AND hasn't
    already been wrapped in a UnicodeDecodeError-safe try/except."""
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return GETCH_BRITTLE in text and GETCH_SAFE_MARKER not in text


def _patch_utlc_getch(path: Path) -> bool:
    """Wrap the Windows branch of `getch()` in `utils/utlc.py` with a
    try/except UnicodeDecodeError so a stray extended-key keystroke
    (arrow keys, F-keys, Page Up/Down) sitting in the console buffer
    doesn't kill the importer at the `Enter to Continue` prompt.
    Returns True on success, False on no-op (already patched / line
    layout doesn't match). The file uses TAB indentation; we mirror it."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if GETCH_SAFE_MARKER in text:
        return False  # already patched
    # The original line is `\t\t\treturn msvcrt.getch().decode('utf-8')`.
    # Replace with a try/except that returns '\r' on undecodable bytes
    # (extended-key prefix), preserving the original tab indentation.
    old = "\t\t\t" + GETCH_BRITTLE
    new = (
        "\t\t\ttry:\n"
        "\t\t\t\treturn msvcrt.getch().decode('utf-8')\n"
        "\t\t\texcept UnicodeDecodeError:\n"
        "\t\t\t\t# extended-key prefix (0xe0/0x00) or other non-utf8\n"
        "\t\t\t\t# byte in the console buffer -- treat as Enter so\n"
        "\t\t\t\t# automation isn't killed by a stray keystroke.\n"
        "\t\t\t\treturn '\\r'"
    )
    if old not in text:
        return False
    backup_file(path)
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    return True


# reverse the install-side mutations made by `doctor --fix`. each unfix step is
# best-effort and idempotent: missing backups / already-restored state are not
# errors. we want users heading to VAC servers to be able to run this without
# having to remember which fixes were applied.
def _run_unfix(cfg) -> int:
    header("Reversing install patches")
    if not (cfg.csgo_install_path or cfg.import_script_path or cfg.cs2_bin_path):
        error("Nothing to unfix: csgo_install_path, import_script_path, and cs2_bin_path are all unset.")
        return 1

    reversed_count = 0
    skipped: List[str] = []

    # 1. restore import_map_community.py from its backup if one exists.
    importer_candidates = _importer_candidates(cfg)
    importer = next((p for p in importer_candidates if p.exists()), None)
    if importer is None:
        # the backup may still exist even if the patched file is gone (rare).
        for cand in importer_candidates:
            if backup_path_for(cand).exists():
                importer = cand
                break

    if importer is None:
        skipped.append("import_map_community.py: not found in any expected location")
    else:
        backup = backup_path_for(importer)
        if backup.exists():
            if restore_file(importer):
                # remove the backup once we've successfully restored from it,
                # so a future --fix starts from a clean tree.
                backup.unlink()
                success(f"restored {importer} from backup")
                reversed_count += 1
            else:
                warn(f"failed to restore {importer} (backup unreadable?)")
        else:
            skipped.append(
                f"{importer.name}: no backup at {backup.name}; "
                "either --fix was never run or the backup was deleted"
            )

    # 2. restore utils/utlc.py from its backup if one exists.
    utlc_candidates = _utlc_candidates(cfg)
    utlc = next((p for p in utlc_candidates if p.is_file()), None)
    if utlc is None:
        for cand in utlc_candidates:
            if backup_path_for(cand).exists():
                utlc = cand
                break
    if utlc is None:
        skipped.append("utlc.py: not found next to importer in any expected location")
    else:
        backup = backup_path_for(utlc)
        if backup.exists():
            if restore_file(utlc):
                backup.unlink()
                success(f"restored {utlc} from backup")
                reversed_count += 1
            else:
                warn(f"failed to restore {utlc} (backup unreadable?)")
        else:
            skipped.append(
                f"{utlc.name}: no backup at {backup.name}; "
                "either --fix was never run or the backup was deleted"
            )

    # 3. rename vpk.signatures.old -> vpk.signatures, removing any backup.
    if cfg.cs2_bin_path:
        sigs = Path(cfg.cs2_bin_path) / "vpk.signatures"
        renamed = sigs.with_suffix(sigs.suffix + ".old")
        if renamed.exists():
            if sigs.exists():
                # both present: keep the live one, drop the .old. uncommon but
                # possible if the user manually restored or steam shipped a new copy.
                renamed.unlink()
                info(f"vpk.signatures already present; removed stale {renamed.name}")
            else:
                renamed.rename(sigs)
                success(f"renamed {renamed.name} -> {sigs.name}")
                reversed_count += 1
            # clean up any backup we wrote alongside the original rename.
            backup = backup_path_for(sigs)
            if backup.exists():
                backup.unlink()
        elif sigs.exists():
            skipped.append("vpk.signatures: already in place; nothing to reverse")
        else:
            skipped.append(
                "vpk.signatures: neither vpk.signatures nor vpk.signatures.old "
                "exists at the configured cs2_bin_path"
            )
    else:
        skipped.append("vpk.signatures: cs2_bin_path not set")

    header("Summary")
    if reversed_count:
        success(f"Reversed {reversed_count} install patch(es).")
        info("Your install should now pass VAC checks again.")
    else:
        warn("No install patches were reversed.")
    for s in skipped:
        info(s)
    # unfix is idempotent: skipped steps are not failures. exit 0 always so
    # users can chain it (e.g. `csgo2cs2 doctor --unfix && cs2.exe`).
    return 0


# strip one `.decode(...)` call from a line.
def _strip_decode(line: str) -> str:
    idx = line.find(DECODE_MARKER)
    if idx < 0:
        return line
    open_paren = idx + len(DECODE_MARKER) - 1
    depth = 0
    end = -1
    for i in range(open_paren, len(line)):
        c = line[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return line  # unbalanced; leave alone
    return line[:idx] + line[end + 1 :]
