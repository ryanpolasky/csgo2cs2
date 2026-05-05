# end-to-end port orchestration.

from __future__ import annotations

import re
import shutil
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
from .tools.import_map import ImportInputs, ImportMapTool
from .tools.steamcmd import CSGO_APP_ID, SteamCMD
from .utils.manifest import PortManifest
from .utils.paths import ensure_dir, find_first
from .utils.url import parse_workshop_id


def run_port_pipeline(
    url_or_id: Optional[str],
    addon: str,
    auto: bool = False,
    skip_import: bool = False,
    config_path: Optional[str] = None,
    local_bsp: Optional[Path] = None,
    use_bsp: bool = True,
    no_merge_instances: bool = False,
    skip_deps: bool = False,
) -> int:
    cfg = load_config(config_path)

    # local-file mode skips the workshop download and uses a synthetic id
    if local_bsp:
        if not local_bsp.exists():
            error(f"BSP not found: {local_bsp}")
            return 2
        workshop_id = f"local-{local_bsp.stem}"
    else:
        if not url_or_id:
            error("Either a workshop URL/ID or a local --bsp path is required.")
            return 2
        parsed = parse_workshop_id(url_or_id)
        if not parsed:
            error(f"Could not extract a Workshop ID from {url_or_id!r}")
            return 2
        workshop_id = parsed

    workspace = ensure_dir(Path(cfg.workspace_dir).expanduser() / workshop_id)
    manifest = PortManifest(workshop_id=workshop_id, addon_name=addon)
    manifest_path = workspace / "manifest.json"

    info(f"Workshop ID: {workshop_id}")
    info(f"Workspace:   {workspace}")
    info(f"Addon:       {addon}")

    # step 1: download with steamcmd (or use the provided local file)
    if local_bsp:
        header("Step 1/5: Local BSP")
        bsp = local_bsp
        info(f"Using local BSP: {bsp}")
    else:
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

    rc = _stage_and_import(
        cfg=cfg,
        vmf=vmf,
        bsp=bsp,
        addon=addon,
        workspace=workspace,
        manifest=manifest,
        use_bsp=use_bsp,
        no_merge_instances=no_merge_instances,
        skip_deps=skip_deps,
    )
    manifest.save(manifest_path)
    info(f"Manifest saved: {manifest_path}")
    return rc


def _download(cfg: Config, workshop_id: str) -> Optional[Path]:
    cmd = SteamCMD(cfg.steamcmd_path)
    if not cmd.resolve():
        error("SteamCMD is not configured. Set `steamcmd_path` in config.")
        return None
    result = cmd.download_workshop_item(
        workshop_id,
        app_id=CSGO_APP_ID,
        login=cfg.steam_login,
        retries=cfg.steamcmd_retries,
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
    # 1. user-provided override
    if cfg.import_script_path:
        p = Path(cfg.import_script_path)
        if p.exists():
            return str(p)
    # 2. valve's bundled copy inside a cs:go install
    if cfg.csgo_install_path:
        install = Path(cfg.csgo_install_path)
        candidates = [
            install / "game" / "csgo" / "scripts" / "import_map_community.py",
            install / "game" / "bin" / "win64" / "import_map_community.py",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    # 3. one we fetched into the tools cache
    cached = (
        Path(cfg.workspace_dir).expanduser().parent
        / "tools"
        / "import-scripts"
        / "import_map_community.py"
    )
    if cached.exists():
        return str(cached)
    return None


# the importer requires:
#   <s1_content_dir>/maps/<mapname>.vmf      (the map and any instance vmfs)
#   <s1_content_dir>/maps/instances/...      (when instances exist)
# stage a clean, space-free path under workspace/staged so we never have to
# copy user content around in the steam install.
def _stage_vmf(vmf: Path, workspace: Path, mapname: str) -> Path:
    staged_root = workspace / "staged"
    staged_maps = ensure_dir(staged_root / "maps")
    staged_vmf = staged_maps / f"{mapname}.vmf"
    shutil.copy2(vmf, staged_vmf)
    # also copy any instance vmfs sitting alongside the source vmf
    src_dir = vmf.parent
    src_instances = src_dir / "instances"
    if src_instances.is_dir():
        dst = staged_maps / "instances"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_instances, dst)
    return staged_root


def _derive_mapname(bsp: Path) -> str:
    # safe-ify the bsp stem: lowercase, replace non-[a-z0-9_] with _.
    stem = bsp.stem.lower()
    sanitized = re.sub(r"[^a-z0-9_]+", "_", stem)
    # reject names that have no alphanumerics (importer needs a real name).
    if not re.search(r"[a-z0-9]", sanitized):
        return "map"
    return sanitized


def _stage_and_import(
    cfg: Config,
    vmf: Path,
    bsp: Path,
    addon: str,
    workspace: Path,
    manifest: PortManifest,
    use_bsp: bool,
    no_merge_instances: bool,
    skip_deps: bool,
) -> int:
    # validate s1/s2 install paths the importer needs
    if not cfg.csgo_install_path:
        error("csgo_install_path is not set; cannot locate s1/s2 gameinfo dirs.")
        return 1
    install = Path(cfg.csgo_install_path)
    s1_gameinfo_dir = install / "csgo"
    s2_gameinfo_dir = install / "game" / "csgo"
    if not (s1_gameinfo_dir / "gameinfo.txt").exists():
        error(f"Missing s1 gameinfo.txt: {s1_gameinfo_dir / 'gameinfo.txt'}")
        return 1
    if not (s2_gameinfo_dir / "gameinfo.gi").exists():
        error(f"Missing s2 gameinfo.gi: {s2_gameinfo_dir / 'gameinfo.gi'}")
        return 1

    importer_path = _resolve_importer_path(cfg)
    importer = ImportMapTool(
        importer_path=importer_path,
        python_executable=cfg.python_executable or "python",
    )
    if not importer.resolve():
        error(
            "import_map_community.py was not found. Run `csgo2cs2 tools install` "
            "to fetch a known-good copy, or set `import_script_path` in config."
        )
        return 1

    mapname = _derive_mapname(bsp)
    s1_content_dir = _stage_vmf(vmf, workspace, mapname)
    if " " in str(s1_content_dir):
        error(
            f"Workspace path contains a space: {s1_content_dir}. The importer "
            "fails on spaces; move workspace_dir to a no-space path."
        )
        return 1

    inputs = ImportInputs(
        s1_gameinfo_dir=s1_gameinfo_dir,
        s1_content_dir=s1_content_dir,
        s2_gameinfo_dir=s2_gameinfo_dir,
        s2_addon=addon,
        mapname=mapname,
    )

    info(f"Invoking import_map_community.py for `{addon}` / map `{mapname}`...")
    result = importer.import_map(
        inputs,
        use_bsp=use_bsp,
        no_merge_instances=no_merge_instances,
        skip_deps=skip_deps,
    )
    if result.returncode != 0:
        warn(f"Importer exited with code {result.returncode}")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        return 1

    success("Import completed. Open the addon in CS2 Workshop Tools to compile.")
    return 0
