# end-to-end port orchestration.

from __future__ import annotations

import re
import shutil
import sys
import time
from pathlib import Path

from . import fixers  # noqa: F401  (registers fixers on import)
from .analyzers.bsp import inspect_bsp
from .analyzers.vmf import analyze_vmf
from .config import Config, load_config
from .extract import extract_bsp_assets
from .fixers.base import apply_all
from .logging_utils import error, header, info, success, warn
from .platform_check import require_windows
from .tools.bspsource import BSPSource
from .tools.import_map import HeartbeatPrinter, ImportInputs, ImportMapTool
from .tools.steamcmd import CSGO_APP_ID, SteamCMD, resolve_downloaded_bsp
from .utils.known_errors import match_error
from .utils.manifest import (
    PORT_STAGES,
    STAGE_DONE,
    STAGE_FAILED,
    STAGE_SKIPPED,
    PortManifest,
    WorkshopMeta,
)
from .utils.paths import ensure_dir, find_first
from .utils.preflight import (
    format_report,
    is_skip_requested,
    run_preflight,
    try_autofix_interactive,
)
from .utils.retry import RetryPolicy, retry_until
from .utils.run_log import current as current_log
from .utils.run_log import log_event
from .utils.url import parse_workshop_id


# Print a "[stage N/M] name • elapsed" header for the current stage and
# return the start time the caller passes to `_log_stage_end`.
def _log_stage_start(stage: str, n: int, total: int = 6) -> float:
    header(f"Step {n}/{total}: {stage}")
    log_event(f"stage_start: {stage}")
    return time.monotonic()


def _log_stage_end(stage: str, start: float, status: str = "done") -> None:
    elapsed = time.monotonic() - start
    log_event(f"stage_end: {stage} ({status}, {elapsed:.1f}s)")
    info(f"[stage:{stage}] {status} in {elapsed:.1f}s")


# match known error patterns against subprocess output and surface a hint.
def _surface_known_error(text: str) -> None:
    if not text:
        return
    hit = match_error(text)
    if hit is None:
        return
    warn(f"hint ({hit.id}): {hit.hint}")


def _record_subprocess(tool: str, argv: list, returncode: int, stdout: str, stderr: str) -> None:
    log = current_log()
    if log is not None:
        log.record_subprocess(tool, argv, returncode, stdout, stderr)


def run_port_pipeline(
    url_or_id: str | None,
    addon: str,
    auto: bool = False,
    skip_import: bool = False,
    config_path: str | None = None,
    local_bsp: Path | None = None,
    use_bsp: bool = True,
    no_merge_instances: bool = False,
    skip_deps: bool = False,
    dry_run: bool = False,
    export_images: str | None = None,
    auto_addoninfo: bool = False,
    resume: bool = True,
    restart: bool = False,
    overwrite: bool = False,
    skip_preflight: bool = False,
    create_addon: bool = False,
) -> int:
    # --auto implies --create-addon: the whole point of --auto is
    # "don't stop to ask me about fixable preconditions."
    if auto:
        create_addon = True
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
    manifest_path = workspace / "manifest.json"
    if not restart and manifest_path.exists():
        try:
            manifest = PortManifest.load(manifest_path)
            # if the addon name changed, treat as a fresh run
            if manifest.addon_name != addon:
                info(
                    f"Manifest addon mismatch ({manifest.addon_name!r} vs {addon!r}); "
                    "starting fresh."
                )
                manifest = PortManifest(workshop_id=workshop_id, addon_name=addon)
        except (OSError, ValueError):
            manifest = PortManifest(workshop_id=workshop_id, addon_name=addon)
    else:
        if restart and manifest_path.exists():
            info("--restart: clearing prior stage state.")
        manifest = PortManifest(workshop_id=workshop_id, addon_name=addon)

    info(f"Workshop ID: {workshop_id}")
    info(f"Workspace:   {workspace}")
    info(f"Addon:       {addon}")

    # record last_args so resume runs preserve fix choices
    manifest.last_args = {
        "auto": auto,
        "skip_import": skip_import,
        "use_bsp": use_bsp,
        "no_merge_instances": no_merge_instances,
        "skip_deps": skip_deps,
        "dry_run": dry_run,
        "export_images": export_images,
        "auto_addoninfo": auto_addoninfo,
    }
    manifest.save(manifest_path)

    # ----- preflight ----------------------------------------------------
    if not skip_preflight and not is_skip_requested():
        # one pass plus one retry-after-autofix attempt: if the user fixes
        # workspace_dir interactively we want to re-check, but no further
        # loops to keep behavior predictable.
        for attempt in range(2):
            report = run_preflight(
                cfg,
                addon=addon,
                skip_import=skip_import or bool(local_bsp),
                overwrite=overwrite,
                create_addon=create_addon,
            )
            if not report.errors:
                break
            if attempt == 0 and try_autofix_interactive(cfg, config_path, report):
                info("Re-running preflight after auto-fix...")
                continue
            break
        if report.warnings:
            info("Preflight warnings:")
            for w in report.warnings:
                warn(f"  {w.id}: {w.message}")
                if w.hint:
                    info(f"    hint: {w.hint}")
        if report.errors:
            error("Preflight blocked the port. Fix these and re-run:")
            print(format_report(report))
            info("Set CSGO2CS2_SKIP_PREFLIGHT=1 to override (not recommended).")
            return 2
        elif not report.warnings:
            success("Preflight passed.")
    else:
        info("Preflight skipped (--skip-preflight or CSGO2CS2_SKIP_PREFLIGHT).")

    # ----- stage 1: download (or use local bsp) -------------------------
    stage = "download"
    if local_bsp:
        start = _log_stage_start("Local BSP", 1)
        bsp = local_bsp
        manifest.start_stage(stage)
        info(f"Using local BSP: {bsp}")
        manifest.finish_stage(stage, STAGE_SKIPPED, "local --bsp; download skipped")
        manifest.save(manifest_path)
        _log_stage_end(stage, start, "skipped")
    elif resume and manifest.stage_is_done(stage):
        info(f"Stage {stage!r} already done; skipping.")
        bsp = _resolve_existing_bsp(cfg, workshop_id)
        if bsp is None:
            warn("Manifest says download is done but no BSP found; re-downloading.")
            start = _log_stage_start("Download", 1)
            manifest.start_stage(stage)
            bsp = _download(cfg, workshop_id)
            if not bsp:
                manifest.finish_stage(stage, STAGE_FAILED, "no .bsp after retry")
                manifest.save(manifest_path)
                return 1
            manifest.finish_stage(stage, STAGE_DONE, str(bsp))
            manifest.save(manifest_path)
            _log_stage_end(stage, start)
    else:
        start = _log_stage_start("Download", 1)
        manifest.start_stage(stage)
        bsp = _download(cfg, workshop_id)
        if not bsp:
            manifest.finish_stage(stage, STAGE_FAILED, "no .bsp after retry")
            manifest.save(manifest_path)
            return 1
        manifest.finish_stage(stage, STAGE_DONE, str(bsp))
        manifest.save(manifest_path)
        _log_stage_end(stage, start)

    # optional: fetch workshop metadata. shared between --export-images
    # (writes to a side dir) and --auto-addoninfo (writes into the addon
    # dir post-import). local-bsp mode has no upstream item to query.
    workshop_meta = None
    if (export_images or auto_addoninfo) and not local_bsp:
        workshop_meta = _fetch_workshop_meta(workshop_id)
    if workshop_meta is not None:
        import time as _time

        manifest.record_workshop_meta(
            WorkshopMeta(
                title=workshop_meta.title,
                description=workshop_meta.description,
                creator=workshop_meta.creator,
                tags=list(workshop_meta.tags),
                preview_url=workshop_meta.preview_url,
                time_created=workshop_meta.time_created,
                time_updated=workshop_meta.time_updated,
                fetched_at=_time.time(),
            )
        )
    if export_images and workshop_meta is not None:
        _write_workshop_images(workshop_meta, export_images)

    # ----- stage 2: inspect ---------------------------------------------
    stage = "inspect"
    if resume and manifest.stage_is_done(stage):
        info(f"Stage {stage!r} already done; skipping.")
    else:
        start = _log_stage_start("Inspect BSP", 2)
        manifest.start_stage(stage)
        bsp_info = inspect_bsp(bsp)
        if not bsp_info.valid_header:
            error(f"{bsp.name} does not look like a Source 1 BSP (header missing).")
            manifest.finish_stage(stage, STAGE_FAILED, "missing BSP header")
            manifest.save(manifest_path)
            return 1
        info(f"BSP version: {bsp_info.version}")
        if bsp_info.suspected_protected:
            error(
                f"BSP appears to be protected (marker `{bsp_info.detected_marker}`). "
                "Decompilers will fail or produce garbage. Aborting."
            )
            manifest.finish_stage(stage, STAGE_FAILED, "bsp protected")
            manifest.save(manifest_path)
            return 1
        manifest.finish_stage(stage, STAGE_DONE, f"version {bsp_info.version}")
        manifest.save(manifest_path)
        _log_stage_end(stage, start)

    # ----- stage 3: extract ---------------------------------------------
    stage = "extract"
    extract_dir = workspace / "extracted"
    if resume and manifest.stage_is_done(stage):
        info(f"Stage {stage!r} already done; skipping.")
    else:
        start = _log_stage_start("Extract packed assets", 3)
        manifest.start_stage(stage)
        extract_result = extract_bsp_assets(cfg, bsp, extract_dir)
        if not extract_result.succeeded:
            warn(extract_result.detail or "asset extraction skipped")
            manifest.finish_stage(stage, STAGE_SKIPPED, extract_result.detail or "extract skipped")
        else:
            manifest.finish_stage(stage, STAGE_DONE, extract_result.detail or "")
        manifest.save(manifest_path)
        _log_stage_end(stage, start)

    # ----- stage 4: decompile -------------------------------------------
    stage = "decompile"
    decompiled_dir = workspace / "decompiled"
    if resume and manifest.stage_is_done(stage):
        info(f"Stage {stage!r} already done; skipping.")
        vmf = find_first(decompiled_dir, ["*.vmf"])
        if vmf is None:
            warn("Manifest says decompile is done but no .vmf found; re-running.")
            start = _log_stage_start("Decompile", 4)
            manifest.start_stage(stage)
            vmf = _decompile(cfg, bsp, decompiled_dir)
            if not vmf:
                manifest.finish_stage(stage, STAGE_FAILED, "no .vmf produced")
                manifest.save(manifest_path)
                return 1
            manifest.finish_stage(stage, STAGE_DONE, str(vmf))
            manifest.save(manifest_path)
            _log_stage_end(stage, start)
    else:
        start = _log_stage_start("Decompile", 4)
        manifest.start_stage(stage)
        vmf = _decompile(cfg, bsp, decompiled_dir)
        if not vmf:
            manifest.finish_stage(stage, STAGE_FAILED, "no .vmf produced")
            manifest.save(manifest_path)
            return 1
        manifest.finish_stage(stage, STAGE_DONE, str(vmf))
        manifest.save(manifest_path)
        _log_stage_end(stage, start)

    # ----- stage 5: analyze and fix vmf ---------------------------------
    stage = "analyze"
    start = _log_stage_start("Analyze and fix VMF", 5)
    manifest.start_stage(stage)
    vmf = _analyze_and_fix(vmf, cfg, manifest, auto=auto, dry_run=dry_run)
    manifest.finish_stage(stage, STAGE_DONE)
    manifest.save(manifest_path)
    _log_stage_end(stage, start)

    # ----- stage 6: import ----------------------------------------------
    stage = "import"
    if skip_import:
        warn("Skipping import as requested. VMF is ready for Windows-side import.")
        manifest.finish_stage(stage, STAGE_SKIPPED, "--skip-import")
        manifest.save(manifest_path)
        info(f"Manifest saved: {manifest_path}")
        return 0

    if dry_run:
        rc = _print_dry_run_plan(
            cfg=cfg,
            vmf=vmf,
            bsp=bsp,
            addon=addon,
            workspace=workspace,
            use_bsp=use_bsp,
            no_merge_instances=no_merge_instances,
            skip_deps=skip_deps,
        )
        manifest.finish_stage(stage, STAGE_SKIPPED, "--dry-run")
        manifest.save(manifest_path)
        info(f"Manifest saved: {manifest_path}")
        return rc

    require_windows("CS2 map import")
    start = _log_stage_start("Import", 6)
    manifest.start_stage(stage)
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

    if rc == 0:
        manifest.finish_stage(stage, STAGE_DONE)
    else:
        manifest.finish_stage(stage, STAGE_FAILED, f"importer rc={rc}")
    _log_stage_end(stage, start, "done" if rc == 0 else "failed")

    if rc == 0 and auto_addoninfo and workshop_meta is not None:
        _populate_addoninfo(cfg, addon, workshop_meta, export_images)

    manifest.save(manifest_path)
    info(f"Manifest saved: {manifest_path}")

    # final summary footer
    _print_stage_summary(manifest)
    return rc


def _print_stage_summary(manifest: PortManifest) -> None:
    rows = []
    for name in PORT_STAGES:
        rec = manifest.stages.get(name)
        if rec is None:
            rows.append((name, "pending", "-"))
            continue
        elapsed = rec.elapsed
        elapsed_s = f"{elapsed:.1f}s" if elapsed is not None else "-"
        rows.append((name, rec.status, elapsed_s))
    info("Stage summary:")
    for name, status, dur in rows:
        print(f"  {name:<10}  {status:<8}  {dur:>7}")


def _resolve_existing_bsp(cfg: Config, workshop_id: str) -> Path | None:
    cmd = SteamCMD(cfg.steamcmd_path)
    scratch = Path(cfg.workspace_dir).expanduser() / workshop_id
    return resolve_downloaded_bsp(cmd, workshop_id, scratch)


# soft-fails: a flaky Steam web call must NOT kill the actual port.
# returns the metadata on success, None on failure.
def _fetch_workshop_meta(workshop_id: str):
    from .utils.workshop_meta import WorkshopMetadataError, fetch_metadata

    info(f"Fetching workshop metadata for {workshop_id}...")
    try:
        return fetch_metadata(workshop_id)
    except WorkshopMetadataError as exc:
        warn(f"workshop metadata fetch skipped: {exc}")
        return None


# write the metadata + preview image to the side dir requested by
# --export-images. failures are warn-only.
def _write_workshop_images(meta, out_dir: str) -> None:
    from .utils.workshop_meta import WorkshopMetadataError, export_to

    try:
        target = export_to(meta, Path(out_dir).expanduser())
    except WorkshopMetadataError as exc:
        warn(f"workshop image export skipped: {exc}")
        return
    title = meta.title or "<no title>"
    success(f"Exported workshop images: {target}/  ({title})")


# write addoninfo.json + addonimage into the imported addon dir,
# pulling values from the workshop metadata. preview is sourced from
# the export-images dir if it's already on disk; otherwise we re-fetch
# it into a tempfile-style location under the workspace dir.
def _populate_addoninfo(cfg: Config, addon: str, meta, export_images_dir: str | None) -> None:
    from .commands.launch_cmd import resolve_addon_dir
    from .utils.addoninfo import copy_thumbnail, write_addoninfo

    addon_dir = resolve_addon_dir(cfg, addon)
    if addon_dir is None:
        warn(f"auto-addoninfo skipped: cannot resolve addon dir for {addon!r}")
        return
    if not addon_dir.exists():
        warn(f"auto-addoninfo skipped: addon dir does not exist: {addon_dir}")
        return

    written = write_addoninfo(meta, addon_dir)
    if written is None:
        info(f"auto-addoninfo: leaving existing addoninfo at {addon_dir} alone")
    else:
        success(f"auto-addoninfo: wrote {written.name}")

    preview_path = None
    if export_images_dir:
        side_dir = Path(export_images_dir).expanduser() / str(meta.workshop_id)
        if side_dir.is_dir():
            for cand in side_dir.glob("preview.*"):
                preview_path = cand
                break

    if preview_path is None and meta.preview_url:
        from .utils.downloader import DownloadError
        from .utils.downloader import fetch as _fetch

        tmp = addon_dir / "_csgo2cs2_preview_dl.tmp"
        try:
            _fetch(meta.preview_url, tmp, name=tmp.name, progress=None)
            preview_path = tmp
        except DownloadError as exc:
            warn(f"auto-addoninfo: preview download failed: {exc}")

    thumb = copy_thumbnail(preview_path, addon_dir)
    if thumb:
        success(f"auto-addoninfo: wrote {thumb.name}")
    if preview_path is not None and preview_path.name.startswith("_csgo2cs2_preview_dl"):
        try:
            preview_path.unlink()
        except OSError:
            pass


def _download(cfg: Config, workshop_id: str) -> Path | None:
    cmd = SteamCMD(cfg.steamcmd_path)
    if not cmd.resolve():
        error("SteamCMD is not configured. Set `steamcmd_path` in config.")
        return None

    expected = cmd.expected_workshop_path(workshop_id)
    scratch = Path(cfg.workspace_dir).expanduser() / workshop_id

    def attempt():
        result = cmd.download_workshop_item(
            workshop_id,
            app_id=CSGO_APP_ID,
            login=cfg.steam_login,
            retries=1,  # retry policy here owns the outer retries
        )
        _record_subprocess(
            "steamcmd",
            ["+workshop_download_item", CSGO_APP_ID, workshop_id],
            result.returncode,
            result.stdout or "",
            result.stderr or "",
        )
        return result

    def is_success(result) -> bool:
        # accept either a raw .bsp (logged-in or s2-era downloads) or
        # a *_legacy.bin (anonymous downloads, every platform).
        # resolve_downloaded_bsp does the unwrap silently.
        try:
            return resolve_downloaded_bsp(cmd, workshop_id, scratch) is not None
        except RuntimeError:
            return False

    policy = RetryPolicy(
        attempts=max(1, cfg.steamcmd_retries),
        base_delay=5.0,
        factor=2.0,
        max_delay=60.0,
    )
    result = retry_until(
        attempt,
        predicate=is_success,
        policy=policy,
        on_retry=lambda i, _r, d: warn(
            f"SteamCMD attempt {i} did not produce a .bsp; retrying in {d:.0f}s..."
        ),
    )
    if result.returncode != 0:
        warn(f"SteamCMD exit code: {result.returncode}")
        _surface_known_error((result.stdout or "") + "\n" + (result.stderr or ""))
    try:
        bsp = resolve_downloaded_bsp(cmd, workshop_id, scratch)
    except RuntimeError as exc:
        error(str(exc))
        return None
    if bsp is None:
        if expected and expected.exists():
            error(
                f"No .bsp or *_legacy.bin found inside {expected} (contents: "
                f"{[p.name for p in sorted(expected.iterdir())]})"
            )
        else:
            error("Workshop content folder not found after SteamCMD run.")
        return None
    success(f"Downloaded: {bsp}")
    return bsp


def _decompile(cfg: Config, bsp: Path, output_dir: Path) -> Path | None:
    bs = BSPSource(cfg.bspsource_path, java_path=cfg.java_path)
    if not bs.resolve():
        error("BSPSource is not configured. Set `bspsource_path` in config.")
        return None
    ensure_dir(output_dir)

    def attempt():
        result = bs.decompile(bsp, output_dir)
        _record_subprocess(
            "bspsource",
            [str(bsp), "->", str(output_dir)],
            result.returncode,
            result.stdout or "",
            result.stderr or "",
        )
        return result

    def looks_ok(result) -> bool:
        vmf = find_first(output_dir, ["*.vmf"])
        return vmf is not None

    policy = RetryPolicy(attempts=2, base_delay=3.0, factor=2.0, max_delay=15.0)
    result = retry_until(
        attempt,
        predicate=looks_ok,
        policy=policy,
        on_retry=lambda i, _r, d: warn(
            f"BSPSource attempt {i} did not produce a .vmf; retrying in {d:.0f}s..."
        ),
    )
    if result.returncode != 0:
        warn(f"BSPSource exit code: {result.returncode}")
        _surface_known_error((result.stdout or "") + "\n" + (result.stderr or ""))
    vmf = find_first(output_dir, ["*.vmf"])
    if not vmf:
        error(
            "No .vmf produced. The map may be bspProtect-protected, or BSPSource may have failed."
        )
        return None
    success(f"VMF written: {vmf}")
    return vmf


# analyze the vmf and write a fixed copy when `--auto` applies fixes.
# in dry_run mode we still surface findings + would-apply fixers but never write.
def _analyze_and_fix(
    vmf: Path,
    cfg: Config,
    manifest: PortManifest,
    auto: bool,
    dry_run: bool = False,
) -> Path:
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

    if dry_run:
        info("Dry run: would apply the following fixes (no .fixed.vmf written):")
        for r in applied:
            info(f"  {r.issue_id}: {r.detail}")
        return vmf

    fixed = vmf.with_name(vmf.stem + ".fixed.vmf")
    fixed.write_text(new_text, encoding="utf-8")
    manifest.record_patch(fixed)
    for r in applied:
        success(f"{r.issue_id}: {r.detail}")
    info(f"Fixed VMF: {fixed}")
    return fixed


def _resolve_importer_path(cfg: Config) -> str | None:
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
    src_dir = vmf.parent
    src_instances = src_dir / "instances"
    if src_instances.is_dir():
        dst = staged_maps / "instances"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_instances, dst)
    return staged_root


_PAKFILE_CONTENT_SUBDIRS = (
    "materials",
    "models",
    "sound",
    "scripts",
    "particles",
    "resource",
)


def _stage_assets(extracted_dir: Path, staged_root: Path) -> int:
    if not extracted_dir.is_dir():
        return 0
    copied = 0
    for sub in _PAKFILE_CONTENT_SUBDIRS:
        src = extracted_dir / sub
        if not src.is_dir():
            continue
        dst = staged_root / sub
        for item in src.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size == item.stat().st_size:
                continue
            shutil.copy2(item, target)
            copied += 1
    return copied


def _rename_csgo_subdirs(staged_root: Path) -> int:
    if not staged_root.is_dir():
        return 0
    touched = 0
    for sub in _PAKFILE_CONTENT_SUBDIRS:
        old = staged_root / sub / "csgo"
        if not old.is_dir():
            continue
        new = staged_root / sub / "csgo_legacy"
        if not new.exists():
            old.rename(new)
            touched += 1
            continue
        for item in old.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(old)
            target = new / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size == item.stat().st_size:
                continue
            shutil.copy2(item, target)
        shutil.rmtree(old)
        touched += 1
    return touched


def _print_dry_run_plan(
    cfg: Config,
    vmf: Path,
    bsp: Path,
    addon: str,
    workspace: Path,
    use_bsp: bool,
    no_merge_instances: bool,
    skip_deps: bool,
) -> int:
    header("Dry run: importer plan")
    if not cfg.csgo_install_path:
        warn("csgo_install_path not set; dry-run cannot resolve the s1/s2 dirs.")
        info("Set csgo_install_path in config to see the full would-run command.")
        return 0
    install = Path(cfg.csgo_install_path)
    s1_gameinfo_dir = install / "csgo"
    s2_gameinfo_dir = install / "game" / "csgo"
    mapname = _derive_mapname(bsp)
    s1_content_dir = workspace / "staged"

    extracted = workspace / "extracted"
    if extracted.is_dir():
        n = sum(1 for p in extracted.rglob("*") if p.is_file())
        info(f"Would pre-copy up to {n} pakfile asset(s) into {s1_content_dir}/")
    else:
        info("No extracted/ dir found; no pakfile assets to pre-copy.")

    importer_path = _resolve_importer_path(cfg) or "<not configured>"
    importer = ImportMapTool(
        importer_path=importer_path if importer_path != "<not configured>" else None,
        python_executable=cfg.python_executable,
    )
    inputs = ImportInputs(
        s1_gameinfo_dir=s1_gameinfo_dir,
        s1_content_dir=s1_content_dir,
        s2_gameinfo_dir=s2_gameinfo_dir,
        s2_addon=addon,
        mapname=mapname,
    )
    if importer.resolve():
        cmd = importer.build_command(
            inputs,
            use_bsp=use_bsp,
            no_merge_instances=no_merge_instances,
            skip_deps=skip_deps,
        )
        info("Would run:")
        quoted = " ".join(_shlex_quote(a) for a in cmd)
        print(f"  {quoted}")
    else:
        info("Importer not resolvable; install via `csgo2cs2 tools install`.")
        info(f"Inputs would be: addon={addon!r}, mapname={mapname!r}")

    info("Dry run complete: nothing was imported and nothing was written.")
    return 0


def _shlex_quote(s: str) -> str:
    if not s or any(c in s for c in (" ", "\t", '"', "'")):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _derive_mapname(bsp: Path) -> str:
    stem = bsp.stem.lower()
    sanitized = re.sub(r"[^a-z0-9_]+", "_", stem)
    if not re.search(r"[a-z0-9]", sanitized):
        return "map"
    return sanitized


def _ensure_addon_scaffold(cfg: Config, addon: str) -> None:
    """Idempotent: scaffold the addon dir iff it's missing. If it exists
    (whether from Workshop Tools, a previous port, or our scaffold), do
    nothing -- the importer will use whatever's there."""
    from .tools.addon_scaffold import addon_dir
    from .tools.addon_scaffold import create as scaffold_create

    target = addon_dir(cfg, addon)
    if target is None or target.exists():
        return
    info(f"Scaffolding addon dir at {target}...")
    scaffold_create(cfg, addon)
    success(f"Created {target} (addoninfo.gi + maps/).")


def _content_addon_maps_dir(cfg: Config, addon: str) -> Path | None:
    """Derive `<install>/content/csgo_addons/<addon>/maps` from the
    configured `cs2_addons_path`. Returns None when the user hasn't
    configured the path or when the derivation would be ambiguous."""
    if not cfg.cs2_addons_path:
        return None
    game_dir = Path(cfg.cs2_addons_path).expanduser()
    # cs2_addons_path is <install>/game/csgo_addons; swap `game` -> `content`
    # to get the parallel content dir. We do this on the path parts so it's
    # robust against trailing slashes and platform separators.
    parts = list(game_dir.parts)
    try:
        idx = len(parts) - 1 - parts[::-1].index("game")
    except ValueError:
        return None
    parts[idx] = "content"
    return Path(*parts) / addon / "maps"


def _ensure_prefab_refs_stub(cfg: Config, addon: str, mapname: str) -> None:
    """Pre-create the post-import files Keller's wrapper reads
    unconditionally. source1import only writes
    `<map>_prefab_refs.txt` for maps that use prefabs -- for ones that
    don't (e.g. recoil_master), the script crashes with FileNotFoundError
    *after* a successful s1->s2 conversion. An empty stub is a well-formed
    no-op for the post-processing chain.

    Idempotent: never overwrites an existing non-empty file; source1import
    will replace empty stubs with its real output when applicable."""
    maps_dir = _content_addon_maps_dir(cfg, addon)
    if maps_dir is None:
        return
    try:
        maps_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # filesystem layout may not be writable yet (steam tools not
        # installed); the importer would surface its own error in that
        # case, so don't fail the pipeline here.
        return
    stub = maps_dir / f"{mapname}_prefab_refs.txt"
    if stub.exists() and stub.stat().st_size > 0:
        return
    try:
        stub.touch(exist_ok=True)
    except OSError:
        return


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
        python_executable=cfg.python_executable,
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

    extracted_dir = workspace / "extracted"
    if extracted_dir.is_dir():
        n = _stage_assets(extracted_dir, s1_content_dir)
        if n:
            success(f"Pre-copied {n} pakfile asset(s) into {s1_content_dir}/")
        else:
            info("No pakfile assets needed pre-copying.")

    renamed = _rename_csgo_subdirs(s1_content_dir)
    if renamed:
        info(f"Renamed `csgo/` -> `csgo_legacy/` under {renamed} staged content bucket(s).")

    # Make sure the target addon dir exists. Valve's importer hangs
    # silently if the dir is missing -- creating an empty WT-style
    # scaffold (addoninfo.gi + maps/) is enough to satisfy it. Safe to
    # call whether or not the dir already exists; scaffold does nothing
    # when the dir has content.
    _ensure_addon_scaffold(cfg, addon)

    inputs = ImportInputs(
        s1_gameinfo_dir=s1_gameinfo_dir,
        s1_content_dir=s1_content_dir,
        s2_gameinfo_dir=s2_gameinfo_dir,
        s2_addon=addon,
        mapname=mapname,
    )

    # Pre-create the file Keller's wrapper script reads unconditionally
    # after import. source1import only writes `<map>_prefab_refs.txt`
    # when the map uses prefabs; for maps without (e.g. recoil_master)
    # the file never exists and StripMDLsFromRefs crashes with
    # FileNotFoundError after a *successful* import. An empty file is a
    # well-formed no-op: SplitMdlFromRefs yields zero models / zero refs
    # and the rest of the post-processing chain handles empties cleanly.
    _ensure_prefab_refs_stub(cfg, addon, mapname)

    info(f"Invoking import_map_community.py for `{addon}` / map `{mapname}`...")
    # Stream importer output so the user sees what resourcecompiler is
    # doing instead of staring at a blank line. The heartbeat fires every
    # ~5s if the subprocess goes quiet, so silent hangs are obvious.
    heartbeat = HeartbeatPrinter(interval=5.0, label="import")

    def _on_line(stream: str, line: str) -> None:
        heartbeat.saw_line()
        sys.stdout.write(line if line.endswith("\n") else line + "\n")
        sys.stdout.flush()

    # Valve's importer shells out to `resourcecompiler.exe` without a
    # full path, so it relies on PATH. The cs2 bin dir is rarely on the
    # user's PATH by default -- ensure it's there for the subprocess.
    extra_path_dirs: list[Path] = []
    if cfg.cs2_bin_path:
        bin_dir = Path(cfg.cs2_bin_path).expanduser()
        if bin_dir.exists():
            extra_path_dirs.append(bin_dir)

    # Valve's importer opens with `WARNING - this will overwrite... Enter to
    # Continue, Esc to Quit` and blocks on stdin. Pre-confirm by feeding a
    # newline; the user has already opted in by running the port command.
    heartbeat.start()
    try:
        result = importer.import_map(
            inputs,
            use_bsp=use_bsp,
            no_merge_instances=no_merge_instances,
            skip_deps=skip_deps,
            stream=True,
            on_line=_on_line,
            extra_path_dirs=extra_path_dirs,
            stdin_input="\n",
        )
    finally:
        heartbeat.stop()
    _record_subprocess(
        "import_map_community",
        [addon, mapname],
        result.returncode,
        result.stdout or "",
        result.stderr or "",
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0:
        # Keller's wrapper exits non-zero when its post-processing chain
        # crashes (e.g. `StripMDLsFromRefs` reading a `<map>_prefab_refs.txt`
        # that source1import never wrote), even after a successful s1->s2
        # conversion. Recognise the success marker -- `OK: <N> imported,
        # 0 failed` -- and treat the post-success crash as a warning so
        # the actual port outcome isn't masked.
        if _importer_logged_successful_import(combined):
            warn(
                f"Importer wrapper exited with code {result.returncode} "
                "during post-processing, but the s1->s2 import itself "
                f"succeeded (OK: <N> imported, 0 failed for `{mapname}`)."
            )
            warn(
                "The .vmap is written; re-run `csgo2cs2 launch` (or open the "
                "addon in CS2 Workshop Tools) to compile and load it."
            )
            success(
                f"Import completed for `{mapname}` (post-process warnings ignored)."
            )
            return 0
        warn(f"Importer exited with code {result.returncode}")
        # stdout/stderr were already streamed in real time; no need to
        # re-print them.
        _surface_known_error(combined)
        return 1

    success("Import completed. Open the addon in CS2 Workshop Tools to compile.")
    return 0


# Pattern emitted by source1import (Valve's own binary, not the python
# wrapper) after every successful import: `OK: 1 imported, 0 failed, 0
# skipped, 0 unknown, 0m:03s`. We anchor to `0 failed` so a partial-failure
# import never satisfies the success check.
_IMPORTER_OK_RE = re.compile(
    r"\bOK:\s+\d+\s+imported,\s+0\s+failed,",
    re.IGNORECASE,
)


def _importer_logged_successful_import(text: str) -> bool:
    return bool(_IMPORTER_OK_RE.search(text or ""))

