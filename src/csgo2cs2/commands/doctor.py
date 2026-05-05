# environment and install patch checks.

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import List

from ..config import load_config
from ..logging_utils import error, header, info, success, warn
from ..platform_check import is_windows, os_label
from ..tools.bspsource import BSPSource
from ..tools.bspzip import BSPZip
from ..tools.steamcmd import SteamCMD
from ..tools.vpkedit import VPKEdit
from ..utils.backup import backup_file, has_marker
from ..utils.steam import find_csgo_install

DECODE_MARKER = ".decode("


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
    for adapter in (
        SteamCMD(cfg.steamcmd_path),
        BSPSource(cfg.bspsource_path, java_path=cfg.java_path),
        VPKEdit(cfg.vpkedit_path),
        BSPZip(cfg.bspzip_path),
    ):
        st = adapter.status()
        if st.installed:
            success(f"{st.name}: {st.path}")
        else:
            warn(f"{st.name}: not configured or not found")
            issues.append(f"Set `{st.name}_path` in config or place {st.name} on PATH")

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
    _check_install_patches(cfg, args.fix, issues, fixes_applied)

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


def _check_install_patches(cfg, fix: bool, issues: List[str], fixes_applied: List[str]) -> None:
    if not cfg.csgo_install_path:
        warn("Skipping install patch checks (csgo_install_path not set)")
        return

    install = Path(cfg.csgo_install_path)

    # import_map_community.py `.decode()` patch
    importer_candidates = [
        install / "game" / "csgo" / "scripts" / "import_map_community.py",
        install / "game" / "bin" / "win64" / "import_map_community.py",
    ]
    importer = next((p for p in importer_candidates if p.exists()), None)
    if importer:
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

    # vpk.signatures rename
    if cfg.cs2_bin_path:
        sigs = Path(cfg.cs2_bin_path) / "vpk.signatures"
        renamed = sigs.with_suffix(sigs.suffix + ".old")
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
