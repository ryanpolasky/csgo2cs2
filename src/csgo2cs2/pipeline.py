# end-to-end port orchestration.

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import fixers  # noqa: F401  (registers fixers on import)
from .analyzers.bsp import inspect_bsp
from .analyzers.vmf import analyze_vmf
from .config import Config, load_config
from .extract import extract_bsp_assets
from .fixers.base import apply_all
from .logging_utils import error, header, info, success, warn
from .platform_check import require_windows
from .tools.bspsource import BSPSource
from .tools.import_map import ImportMapTool
from .tools.steamcmd import CSGO_APP_ID, SteamCMD
from .utils.manifest import PortManifest
from .utils.paths import ensure_dir, find_first
from .utils.url import parse_workshop_id


def run_port_pipeline(
    url_or_id: str,
    addon: str,
    auto: bool = False,
    skip_import: bool = False,
    config_path: Optional[str] = None,
) -> int:
    cfg = load_config(config_path)

    workshop_id = parse_workshop_id(url_or_id)
    if not workshop_id:
        error(f"Could not extract a Workshop ID from {url_or_id!r}")
        return 2

    workspace = ensure_dir(Path(cfg.workspace_dir).expanduser() / workshop_id)
    manifest = PortManifest(workshop_id=workshop_id, addon_name=addon)
    manifest_path = workspace / "manifest.json"

    info(f"Workshop ID: {workshop_id}")
    info(f"Workspace:   {workspace}")
    info(f"Addon:       {addon}")

    # step 1: download with steamcmd
    header("Step 1/5: Download")
    bsp = _download(cfg, workshop_id)
    if not bsp:
        manifest.save(manifest_path)
        return 1

    # step 2: inspect the bsp before decompile
    header("Step 2/5: Inspect BSP")
    bsp_info = inspect_bsp(bsp)
    if not bsp_info.valid_header:
        error(f"{bsp.name} does not look like a Source 1 BSP (header missing).")
        manifest.save(manifest_path)
        return 1
    info(f"BSP version: {bsp_info.version}")
    if bsp_info.suspected_protected:
        error(
            f"BSP appears to be protected (marker `{bsp_info.detected_marker}`). "
            "Decompilers will fail or produce garbage. Aborting."
        )
        manifest.save(manifest_path)
        return 1

    # step 3: extract packed assets if a tool is configured
    header("Step 3/5: Extract packed assets")
    extract_dir = workspace / "extracted"
    extract_result = extract_bsp_assets(cfg, bsp, extract_dir)
    if not extract_result.succeeded:
        warn(extract_result.detail or "asset extraction skipped")

    # step 4: decompile with bspsource
    header("Step 4/5: Decompile")
    vmf = _decompile(cfg, bsp, workspace / "decompiled")
    if not vmf:
        manifest.save(manifest_path)
        return 1

    # step 5a: analyze and optionally auto-fix the vmf
    header("Step 5/5: Analyze and fix VMF")
    vmf = _analyze_and_fix(vmf, cfg, manifest, auto=auto)

    # step 5b: import with the windows-only cs2 toolchain
    if skip_import:
        warn("Skipping import as requested. VMF is ready for Windows-side import.")
        manifest.save(manifest_path)
        info(f"Manifest saved: {manifest_path}")
        return 0

    require_windows("CS2 map import")

    importer = ImportMapTool(
        importer_path=_resolve_importer_path(cfg),
        python_executable="python",
    )
    if not importer.resolve():
        error(
            "import_map_community.py was not found. Set csgo_install_path in "
            "config or ensure CS2 is installed."
        )
        manifest.save(manifest_path)
        return 1

    info("Invoking Valve's import_map_community.py...")
    result = importer.import_vmf(vmf, addon)
    if result.returncode != 0:
        warn(f"Importer exited with code {result.returncode}")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        manifest.save(manifest_path)
        return 1

    success("Import completed. Open the addon in CS2 Workshop Tools to compile.")
    manifest.save(manifest_path)
    info(f"Manifest saved: {manifest_path}")
    return 0


def _download(cfg: Config, workshop_id: str) -> Optional[Path]:
    cmd = SteamCMD(cfg.steamcmd_path)
    if not cmd.resolve():
        error("SteamCMD is not configured. Set `steamcmd_path` in config.")
        return None
    result = cmd.download_workshop_item(
        workshop_id, app_id=CSGO_APP_ID, login=cfg.steam_login
    )
    if result.returncode != 0:
        warn(f"SteamCMD exit code: {result.returncode}")
    expected = cmd.expected_workshop_path(workshop_id)
    if not expected or not expected.exists():
        error("Workshop content folder not found after SteamCMD run.")
        return None
    bsp = find_first(expected, ["*.bsp"])
    if not bsp:
        error(f"No .bsp inside {expected}")
        return None
    success(f"Downloaded: {bsp}")
    return bsp


def _decompile(cfg: Config, bsp: Path, output_dir: Path) -> Optional[Path]:
    bs = BSPSource(cfg.bspsource_path, java_path=cfg.java_path)
    if not bs.resolve():
        error("BSPSource is not configured. Set `bspsource_path` in config.")
        return None
    ensure_dir(output_dir)
    result = bs.decompile(bsp, output_dir)
    if result.returncode != 0:
        warn(f"BSPSource exit code: {result.returncode}")
    vmf = find_first(output_dir, ["*.vmf"])
    if not vmf:
        error(
            "No .vmf produced. The map may be bspProtect-protected, or BSPSource may have failed."
        )
        return None
    success(f"VMF written: {vmf}")
    return vmf


# analyze the vmf and write a fixed copy when `--auto` applies fixes.
def _analyze_and_fix(vmf: Path, cfg: Config, manifest: PortManifest, auto: bool) -> Path:
    text = vmf.read_text(encoding="utf-8", errors="ignore")
    analysis = analyze_vmf(text, default_skybox=cfg.default_skybox)

    if not analysis.findings:
        success("No issues detected; VMF is clean.")
        return vmf

    for f in analysis.findings:
        marker = "[fix]" if f.fixable else "[ ]"
        warn(f"{marker} {f.issue_id}: {f.message}")

    if not auto:
        info("Pass `--auto` to apply auto-fixes; using original VMF as-is.")
        return vmf

    new_text, results = apply_all(text, analysis.findings)
    applied = [r for r in results if r.applied]
    if not applied:
        info("No fixers matched; using original VMF.")
        return vmf

    fixed = vmf.with_name(vmf.stem + ".fixed.vmf")
    fixed.write_text(new_text, encoding="utf-8")
    manifest.record_patch(fixed)
    for r in applied:
        success(f"{r.issue_id}: {r.detail}")
    info(f"Fixed VMF: {fixed}")
    return fixed


def _resolve_importer_path(cfg: Config) -> Optional[str]:
    if not cfg.csgo_install_path:
        return None
    install = Path(cfg.csgo_install_path)
    candidates = [
        install / "game" / "csgo" / "scripts" / "import_map_community.py",
        install / "game" / "bin" / "win64" / "import_map_community.py",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None
