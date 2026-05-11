# Pre-flight checks for `csgo2cs2 port`.
#
# Validates everything we need before a port writes anything or hits
# Steam. The goal is to catch the predictable failure modes (missing
# tools, unwritable addon dir, no free disk, addon name collision,
# Windows MAX_PATH, install patches not applied) up front and present a
# single "fix these N things" report -- instead of failing mid-pipeline
# after a 600 MB download.

from __future__ import annotations

import os
import shutil
import string
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..config import Config
from ..platform_check import is_windows
from .drift import load_state
from .long_path import WIN_SAFE_BUDGET, is_too_long


@dataclass
class PreflightIssue:
    id: str
    severity: str  # "error" or "warn"
    message: str
    hint: str = ""


@dataclass
class PreflightReport:
    issues: List[PreflightIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[PreflightIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[PreflightIssue]:
        return [i for i in self.issues if i.severity == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _safe_dir_writable(path: Path) -> bool:
    """Probe by creating + deleting a sentinel file in `path`."""
    if not path.exists() or not path.is_dir():
        return False
    sentinel = path / f".csgo2cs2_write_probe_{uuid.uuid4().hex[:8]}"
    try:
        sentinel.write_text("probe", encoding="utf-8")
    except OSError:
        return False
    try:
        sentinel.unlink()
    except OSError:
        return True  # we wrote it; we just can't clean it up
    return True


def _free_bytes(path: Path) -> Optional[int]:
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return None


def _existing_addon(cs2_addons_path: Optional[str], addon: str) -> Optional[Path]:
    if not cs2_addons_path:
        return None
    p = Path(cs2_addons_path).expanduser() / addon
    if p.exists():
        return p
    return None


_VALID_ADDON_CHARS = set(string.ascii_lowercase + string.digits + "_-")


def _check_addon_name(report: PreflightReport, addon: str) -> None:
    if not addon:
        report.issues.append(
            PreflightIssue(
                id="addon_name_empty",
                severity="error",
                message="--addon is required.",
                hint="Pass --addon <name> on the command line.",
            )
        )
        return
    if addon != addon.lower():
        report.issues.append(
            PreflightIssue(
                id="addon_name_case",
                severity="warn",
                message=f"Addon name {addon!r} has uppercase letters; CS2 expects lowercase.",
                hint=f"Re-run with --addon {addon.lower()}.",
            )
        )
    bad = sorted({c for c in addon if c not in _VALID_ADDON_CHARS})
    if bad:
        report.issues.append(
            PreflightIssue(
                id="addon_name_invalid_chars",
                severity="error",
                message=(
                    f"Addon name {addon!r} contains characters CS2 will reject: "
                    f"{', '.join(repr(c) for c in bad)}."
                ),
                hint="Use only lowercase a-z, digits, underscore, and dash.",
            )
        )


def _check_tools(report: PreflightReport, cfg: Config, *, skip_import: bool) -> None:
    required = [
        ("steamcmd_path", cfg.steamcmd_path),
        ("bspsource_path", cfg.bspsource_path),
    ]
    for key, value in required:
        if not value:
            report.issues.append(
                PreflightIssue(
                    id=f"tool_missing_{key}",
                    severity="error",
                    message=f"{key} is not set in config.",
                    hint="Run `csgo2cs2 tools install` to fetch the pinned versions.",
                )
            )
            continue
        if not Path(value).exists():
            report.issues.append(
                PreflightIssue(
                    id=f"tool_not_on_disk_{key}",
                    severity="error",
                    message=f"{key} = {value!r} does not exist on disk.",
                    hint="Run `csgo2cs2 tools install` or update the path in config.",
                )
            )
    if not skip_import and not cfg.import_script_path:
        report.issues.append(
            PreflightIssue(
                id="tool_missing_import_script_path",
                severity="warn",
                message="import_script_path is not set; will use auto-detection.",
                hint=(
                    "Run `csgo2cs2 tools install import-script` for a pinned copy "
                    "of import_map_community.py."
                ),
            )
        )


def _check_install_paths(report: PreflightReport, cfg: Config, *, skip_import: bool) -> None:
    if skip_import:
        return
    if not cfg.csgo_install_path:
        report.issues.append(
            PreflightIssue(
                id="csgo_install_path_unset",
                severity="error",
                message="csgo_install_path is not set; the importer cannot find gameinfo files.",
                hint="Run `csgo2cs2 init --interactive` to set it.",
            )
        )
        return
    install = Path(cfg.csgo_install_path).expanduser()
    if not install.exists():
        report.issues.append(
            PreflightIssue(
                id="csgo_install_path_missing",
                severity="error",
                message=f"csgo_install_path = {install} does not exist.",
                hint=(
                    "Update csgo_install_path in config to the 'Counter-Strike "
                    "Global Offensive' folder under your Steam library."
                ),
            )
        )
        return
    s1 = install / "csgo" / "gameinfo.txt"
    s2 = install / "game" / "csgo" / "gameinfo.gi"
    if not s1.exists():
        report.issues.append(
            PreflightIssue(
                id="missing_gameinfo_txt",
                severity="error",
                message=f"Missing S1 gameinfo: {s1}",
                hint="Confirm csgo_install_path points to a CS:GO/CS2 install.",
            )
        )
    if not s2.exists():
        report.issues.append(
            PreflightIssue(
                id="missing_gameinfo_gi",
                severity="error",
                message=f"Missing S2 gameinfo: {s2}",
                hint="CS2 install layout has changed; reverify the path.",
            )
        )


def _check_addon_dir(
    report: PreflightReport,
    cfg: Config,
    addon: str,
    *,
    overwrite: bool,
    skip_import: bool,
) -> None:
    if skip_import:
        return
    if not cfg.cs2_addons_path:
        report.issues.append(
            PreflightIssue(
                id="cs2_addons_path_unset",
                severity="warn",
                message="cs2_addons_path is not set; verify command will fall back to defaults.",
                hint="Run `csgo2cs2 init --interactive` to set it.",
            )
        )
        return
    addons_root = Path(cfg.cs2_addons_path).expanduser()
    if not addons_root.exists():
        report.issues.append(
            PreflightIssue(
                id="cs2_addons_path_missing",
                severity="error",
                message=f"cs2_addons_path = {addons_root} does not exist.",
                hint="Verify your CS2 install path or run `csgo2cs2 init --interactive`.",
            )
        )
        return
    if not _safe_dir_writable(addons_root):
        report.issues.append(
            PreflightIssue(
                id="cs2_addons_path_not_writable",
                severity="error",
                message=f"cs2_addons_path = {addons_root} is not writable.",
                hint=(
                    "Close CS2 and Hammer 2 if open. On Windows, if the install lives "
                    "under Program Files, run your terminal as Administrator."
                ),
            )
        )
        return
    existing = _existing_addon(cfg.cs2_addons_path, addon)
    if existing is not None and not overwrite:
        report.issues.append(
            PreflightIssue(
                id="addon_already_exists",
                severity="error",
                message=f"Addon {addon!r} already exists at {existing}.",
                hint=(
                    "Pick a different --addon, manually delete the directory, or "
                    "re-run with --overwrite to allow the importer to merge into it."
                ),
            )
        )


def _check_workspace(report: PreflightReport, cfg: Config) -> None:
    workspace = Path(cfg.workspace_dir).expanduser()
    parent = workspace.parent if not workspace.exists() else workspace
    if not parent.exists():
        # we will mkdir it; nothing to check beyond writability of root
        return
    if not _safe_dir_writable(parent):
        report.issues.append(
            PreflightIssue(
                id="workspace_not_writable",
                severity="error",
                message=f"workspace_dir parent = {parent} is not writable.",
                hint="Pick a workspace_dir under your home directory.",
            )
        )
    if " " in str(workspace):
        report.issues.append(
            PreflightIssue(
                id="workspace_has_space",
                severity="error",
                message=f"workspace_dir = {workspace} contains a space.",
                hint="The CS2 importer rejects paths with spaces. Use C:\\csgo2cs2 (Windows) or ~/csgo2cs2 (others).",
            )
        )
    if is_too_long(workspace):
        report.issues.append(
            PreflightIssue(
                id="workspace_path_too_long",
                severity="warn",
                message=(
                    f"workspace_dir = {workspace} ({len(str(workspace))} chars) is close "
                    f"to the Windows {WIN_SAFE_BUDGET}-char safe budget."
                ),
                hint="Move workspace_dir to a shorter root like C:\\csgo2cs2.",
            )
        )


def _check_disk_space(report: PreflightReport, cfg: Config, *, headroom_gb: float = 2.0) -> None:
    workspace = Path(cfg.workspace_dir).expanduser()
    probe_dir = workspace if workspace.exists() else workspace.parent
    if not probe_dir.exists():
        return
    free = _free_bytes(probe_dir)
    if free is None:
        return
    free_gb = free / (1024**3)
    if free_gb < headroom_gb:
        report.issues.append(
            PreflightIssue(
                id="low_disk_space",
                severity="error",
                message=f"Only {free_gb:.1f} GB free under {probe_dir}; need at least {headroom_gb:.1f} GB.",
                hint="Free space or move workspace_dir to a larger volume.",
            )
        )


def _check_install_patches(
    report: PreflightReport,
    cfg: Config,
    *,
    skip_import: bool,
) -> None:
    if skip_import or not is_windows():
        return
    workspace = Path(cfg.workspace_dir).expanduser()
    state = load_state(workspace)
    if not state.entries:
        report.issues.append(
            PreflightIssue(
                id="install_patches_not_applied",
                severity="warn",
                message="No record of install patches being applied.",
                hint=(
                    "If the import step fails with an importer .decode() error or "
                    "vpk.signatures.old, run `csgo2cs2 doctor --fix` first."
                ),
            )
        )


def run_preflight(
    cfg: Config,
    *,
    addon: str,
    skip_import: bool = False,
    overwrite: bool = False,
) -> PreflightReport:
    """Run every preflight check. Returns a report; caller decides what to do."""
    report = PreflightReport()
    _check_addon_name(report, addon)
    _check_tools(report, cfg, skip_import=skip_import)
    _check_install_paths(report, cfg, skip_import=skip_import)
    _check_addon_dir(report, cfg, addon, overwrite=overwrite, skip_import=skip_import)
    _check_workspace(report, cfg)
    _check_disk_space(report, cfg)
    _check_install_patches(report, cfg, skip_import=skip_import)
    return report


def format_report(report: PreflightReport) -> str:
    """Render a report as a human-readable multi-line string."""
    lines: List[str] = []
    for issue in report.issues:
        prefix = "ERROR" if issue.severity == "error" else "warn "
        lines.append(f"[{prefix}] {issue.id}: {issue.message}")
        if issue.hint:
            lines.append(f"        hint: {issue.hint}")
    if not lines:
        lines.append("All preflight checks passed.")
    return "\n".join(lines)


# environment escape hatch for users who know what they're doing
def is_skip_requested() -> bool:
    return bool(os.environ.get("CSGO2CS2_SKIP_PREFLIGHT"))
