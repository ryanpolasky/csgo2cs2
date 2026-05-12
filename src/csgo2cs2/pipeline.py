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


class _TeeStream:
    """Write-only file-like wrapper that mirrors every write to BOTH the
    original stream (terminal) and a log file. Used by `_DebugTee` for
    `csgo2cs2 port --debug`."""

    def __init__(self, original, log_fp) -> None:
        self._orig = original
        self._log = log_fp
        # Best-effort encoding for downstream code that inspects
        # `sys.stdout.encoding` (e.g. the rule-char fallback in
        # logging_utils).
        self.encoding = getattr(original, "encoding", "utf-8") or "utf-8"

    def write(self, s):
        # Mirror first to log (UTF-8) so even Windows cp1252 console
        # encode errors don't lose the line from the log. Then write to
        # the original stream; if that raises, swallow + continue so the
        # log stays consistent.
        try:
            self._log.write(s)
        except Exception:  # noqa: BLE001
            pass
        try:
            return self._orig.write(s)
        except UnicodeEncodeError:
            # Console can't encode some chars (rare with cp1252). Strip
            # offending bytes and keep going so the user still sees
            # roughly what's happening.
            safe = s.encode("ascii", errors="replace").decode("ascii")
            return self._orig.write(safe)

    def flush(self):
        try:
            self._log.flush()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._orig.flush()
        except Exception:  # noqa: BLE001
            pass

    def isatty(self):
        return getattr(self._orig, "isatty", lambda: False)()

    def fileno(self):
        return self._orig.fileno()

    def __getattr__(self, name):
        return getattr(self._orig, name)


class _DebugTee:
    """Install/uninstall a tee on sys.stdout + sys.stderr for the
    duration of one port run. Writes to
    `<workspace>/port-<UTC-timestamp>.log` (UTF-8). Subprocess output
    that we already pipe through Python (e.g. source1import via
    `HeartbeatPrinter`) gets captured; subprocesses that write raw bytes
    directly to fd 1/2 are not captured -- those are uncommon in this
    pipeline."""

    def __init__(self, workspace: Path) -> None:
        ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        self.log_path = workspace / f"port-{ts}.log"
        self._fp = None
        self._orig_stdout = None
        self._orig_stderr = None

    def install(self) -> None:
        import sys as _sys

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self._orig_stdout = _sys.stdout
        self._orig_stderr = _sys.stderr
        _sys.stdout = _TeeStream(self._orig_stdout, self._fp)
        _sys.stderr = _TeeStream(self._orig_stderr, self._fp)

    def uninstall(self) -> None:
        import sys as _sys

        if self._orig_stdout is not None:
            _sys.stdout = self._orig_stdout
        if self._orig_stderr is not None:
            _sys.stderr = self._orig_stderr
        if self._fp is not None:
            try:
                self._fp.flush()
                self._fp.close()
            except Exception:  # noqa: BLE001
                pass
            self._fp = None


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
    debug: bool = False,
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
    # --debug: tee stdout+stderr to a per-run log under workspace/.
    # Installed before the body runs so early-stage errors still land in
    # the log. The "log saved to X" line is printed AT THE END so it
    # doesn't get scrolled off-screen by the rest of the port output.
    _debug_tee = _DebugTee(workspace) if debug else None
    if _debug_tee is not None:
        _debug_tee.install()
    try:
        rc = _run_port_pipeline_body(
            cfg=cfg,
            config_path=config_path,
            workshop_id=workshop_id,
            workspace=workspace,
            addon=addon,
            auto=auto,
            skip_import=skip_import,
            local_bsp=local_bsp,
            use_bsp=use_bsp,
            no_merge_instances=no_merge_instances,
            skip_deps=skip_deps,
            dry_run=dry_run,
            export_images=export_images,
            auto_addoninfo=auto_addoninfo,
            resume=resume,
            restart=restart,
            overwrite=overwrite,
            skip_preflight=skip_preflight,
            create_addon=create_addon,
        )
        if _debug_tee is not None:
            # Print AFTER the body finishes so this line is the last
            # thing on the user's screen and they can copy the path
            # without scrolling back through the whole port output.
            info(f"--debug: full transcript saved to {_debug_tee.log_path}")
        return rc
    finally:
        if _debug_tee is not None:
            _debug_tee.uninstall()


def _run_port_pipeline_body(
    *,
    cfg: Config,
    config_path: str | None,
    workshop_id: str,
    workspace: Path,
    addon: str,
    auto: bool,
    skip_import: bool,
    local_bsp: Path | None,
    use_bsp: bool,
    no_merge_instances: bool,
    skip_deps: bool,
    dry_run: bool,
    export_images: str | None,
    auto_addoninfo: bool,
    resume: bool,
    restart: bool,
    overwrite: bool,
    skip_preflight: bool,
    create_addon: bool,
) -> int:
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
    vmf = _analyze_and_fix(
        vmf,
        cfg,
        manifest,
        auto=auto,
        dry_run=dry_run,
        extracted_dir=extract_dir,
    )
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

    if rc == 0:
        # Copy-pasteable next-step hint. The addon must be opened in
        # Hammer 2 (Workshop Tools) for the final .vmap -> .vmap_c
        # compile; the port itself only generates the .vmap + .vmat / .vmdl
        # source files. Surfacing the exact command avoids the "now what?"
        # gap users hit when the port finishes.
        success(f"Next: csgo2cs2 launch --hammer {addon}")
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
    extracted_dir: Path | None = None,
) -> Path:
    text = vmf.read_text(encoding="utf-8", errors="ignore")
    custom_skies = _collect_custom_skies(extracted_dir) if extracted_dir else []
    if custom_skies:
        info(
            f"Detected {len(custom_skies)} map-shipped custom skybox file(s); "
            "skybox auto-substitution will skip them."
        )
    analysis = analyze_vmf(
        text,
        default_skybox=cfg.default_skybox,
        custom_skies=custom_skies,
    )

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
    """Idempotent: scaffold the addon dir iff it's missing, then heal
    gameinfo.gi if an older scaffold or a hand-made addon dir is missing
    it. Without gameinfo.gi the addon is isolated (no csgo_imported /
    csgo_core mounting), so resourcecompiler can't find any base CSGO
    asset and every wall/floor/model renders as missing -- see
    `addon_scaffold._GAMEINFO_TEMPLATE` for the why."""
    from .tools.addon_scaffold import (
        addon_dir,
        ensure_gameinfo,
    )
    from .tools.addon_scaffold import (
        create as scaffold_create,
    )

    target = addon_dir(cfg, addon)
    if target is None:
        return
    if not target.exists():
        info(f"Scaffolding addon dir at {target}...")
        scaffold_create(cfg, addon)
        success(f"Created {target} (addoninfo.gi + gameinfo.gi + maps/).")
        return
    healed = ensure_gameinfo(cfg, addon)
    if healed:
        rels = ", ".join(str(p) for p in healed)
        info(
            f"Wrote missing gameinfo.gi: {rels} (without this the addon "
            "can't resolve base CSGO assets at build time)."
        )


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


def _content_addon_dir(cfg: Config, addon: str) -> Path | None:
    """`<install>/content/csgo_addons/<addon>` (the parent of /maps,
    /models, /materials, etc.). Returns None when unconfigured."""
    maps_dir = _content_addon_maps_dir(cfg, addon)
    return maps_dir.parent if maps_dir is not None else None


# `_class = "..."` and a single-line `name = "..."` (both standard
# ModelDoc / KV3 forms). Used by the BodyGroupChoice fixer below.
_VMDL_CLASS_RE = re.compile(r'_class\s*=\s*"([^"]+)"')
_VMDL_NAME_RE = re.compile(r'^\s*name\s*=\s*"([^"]*)"\s*$')


def _vmdl_block_end(lines: list[str], start: int) -> int:
    """Index of the `}` that closes the `{` enclosing `lines[start]`.
    We assume `start` is INSIDE a `{ ... }` block (depth 1) and walk
    forward counting `{`/`}` until we return to depth 0."""
    depth = 1
    for j in range(start, len(lines)):
        for ch in lines[j]:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return j
    return len(lines) - 1


def _vmdl_block_has_name(lines: list[str], start: int, end: int) -> bool:
    """True iff any `name = "..."` KV appears in `lines[start..end]`."""
    return any(_VMDL_NAME_RE.match(lines[j]) for j in range(start, end + 1))


def _fix_vmdl_bodygroup_choices_text(text: str) -> tuple[str, int]:
    """Inject `name = "<bg>_choice_<N>"` on every BodyGroupChoice block
    that lacks a `name` field. cs_mdl_import (Valve's .mdl->.vmdl step)
    omits the field on every choice, which makes resourcecompiler fail
    every CSGO weapon with:

        RESOURCE COMPILE ERROR: BodyGroup: studio : Invalid empty body
        group choice name in bodygroup 'studio'. Non-empty choice names
        are required.

    Preserves the file's original line endings (cs_mdl_import emits
    CRLF on Windows). Returns (new_text, n_fixes). Idempotent: a second
    pass over an already-patched file applies zero fixes."""
    if "\r\n" in text:
        eol = "\r\n"
        body = text.replace("\r\n", "\n")
    else:
        eol = "\n"
        body = text
    lines = body.split("\n")

    # Stack of (parent_bodygroup_name, next_choice_index, parent_end_idx).
    # We pop entries off the stack as we walk past their closing `}`.
    bg_stack: list[tuple[str, int, int]] = []
    edits: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _VMDL_CLASS_RE.search(line)
        if not m:
            continue
        cls = m.group(1)
        if cls == "BodyGroup":
            block_end = _vmdl_block_end(lines, i)
            bg_name = ""
            for j in range(i, block_end + 1):
                nm = _VMDL_NAME_RE.match(lines[j])
                if nm:
                    bg_name = nm.group(1)
                    break
            bg_stack.append((bg_name or "bodygroup", 0, block_end))
        elif cls == "BodyGroupChoice":
            while bg_stack and bg_stack[-1][2] < i:
                bg_stack.pop()
            block_end = _vmdl_block_end(lines, i)
            has_name = _vmdl_block_has_name(lines, i + 1, block_end)
            parent_name, idx, parent_end = bg_stack[-1] if bg_stack else ("orphan", 0, 0)
            if not has_name:
                # Match the indentation of `_class = ...` so the
                # injected KV lines up with the rest of the block.
                indent_len = len(line) - len(line.lstrip(" \t"))
                indent = line[:indent_len]
                edits.append(
                    (i, f'{indent}name = "{parent_name}_choice_{idx}"'),
                )
            if bg_stack:
                bg_stack[-1] = (parent_name, idx + 1, parent_end)

    if not edits:
        return text, 0
    for insert_after, new_line in sorted(edits, reverse=True):
        lines.insert(insert_after + 1, new_line)
    return eol.join(lines), len(edits)


def _patch_vmdl_bodygroup_choices(cfg: Config, addon: str) -> tuple[int, int]:
    """Walk every `.vmdl` under `<content>/csgo_addons/<addon>/models/`
    and inject missing BodyGroupChoice names. Returns (n_files_patched,
    n_choices_patched). Safe to call multiple times; skips files that
    don't need fixing."""
    addon_dir = _content_addon_dir(cfg, addon)
    if addon_dir is None:
        return (0, 0)
    models_dir = addon_dir / "models"
    if not models_dir.is_dir():
        return (0, 0)
    files_patched = 0
    choices_patched = 0
    for vmdl in models_dir.rglob("*.vmdl"):
        try:
            raw = vmdl.read_bytes()
        except OSError:
            continue
        text = raw.decode("utf-8", errors="replace")
        new_text, n = _fix_vmdl_bodygroup_choices_text(text)
        if n > 0:
            try:
                vmdl.write_bytes(new_text.encode("utf-8"))
            except OSError:
                continue
            files_patched += 1
            choices_patched += n
    return (files_patched, choices_patched)


# Subdirectories under staged/ that hold asset sources convertible by
# source1import. .vmt -> .vmat (materials), .mdl -> .vmdl (models). Other
# pakfile dirs (sound, particles, ...) ship loose at runtime and don't
# need a per-asset conversion pass, so we skip them.
_REFS_ASSET_EXTS: tuple[tuple[str, str], ...] = (
    ("materials", ".vmt"),
    ("models", ".mdl"),
)


def _collect_staged_refs(staged_root: Path) -> list[str]:
    """Return forward-slash relative paths to every convertible asset
    under `staged_root` -- materials (.vmt) and models (.mdl). Sorted
    for deterministic output. Used to drive Keller's per-asset s1->s2
    conversion phase via the refs file format."""
    refs: list[str] = []
    for subdir, ext in _REFS_ASSET_EXTS:
        d = staged_root / subdir
        if not d.is_dir():
            continue
        for p in sorted(d.rglob(f"*{ext}")):
            if not p.is_file():
                continue
            rel = p.relative_to(staged_root).as_posix()
            refs.append(rel)
    return refs


def _collect_custom_skies(extracted_dir: Path) -> list[str]:
    """Return basenames (no extension) of skybox materials shipped in
    the BSP pakfile. Detected by scanning `extracted_dir/materials/skybox/`
    for .vmt / .vmat files. These are author-shipped customs and should
    NOT be substituted with stock CS2 skies. Returned as lower-case
    basenames, plus their suffix-stripped variants
    (`sky_dust_up.vmt` -> {`sky_dust_up`, `sky_dust`}) so the analyzer
    can match the worldspawn `skyname` value even when it points at
    a face-less canonical form."""
    out: set[str] = set()
    if not extracted_dir.is_dir():
        return []
    skyroot = extracted_dir / "materials" / "skybox"
    if not skyroot.is_dir():
        return []
    # Skybox face suffixes used by Source 1 / CSGO. Strip them so the
    # canonical sky basename matches a worldspawn `"skyname" "sky_xyz"`.
    face_suffixes = ("up", "dn", "lf", "rt", "ft", "bk")
    for p in skyroot.rglob("*"):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix not in (".vmt", ".vmat"):
            continue
        stem = p.stem.lower()
        out.add(stem)
        # also add stem with face suffix removed:
        #   sky_dust_up -> sky_dust   (snake-case faces)
        #   sky_dustup  -> sky_dust   (concat faces)
        for fs in face_suffixes:
            if stem.endswith(f"_{fs}") and len(stem) > len(fs) + 1:
                out.add(stem[: -len(fs) - 1])
                break
            if stem.endswith(fs) and len(stem) > len(fs) + 3:  # sky_<x>up
                base = stem[: -len(fs)]
                if base.startswith("sky_"):
                    out.add(base)
                    break
    return sorted(out)


# `"material" "..."` and `"model" "..."` KV pairs in a .vmf. Material
# values are bare paths relative to materials/ with no extension (e.g.
# `metal/metalcombine002`); model values are full paths under models/
# with a .mdl extension (e.g. `models/weapons/w_pist_glock18.mdl`).
_VMF_MATERIAL_RE = re.compile(r'"material"\s*"([^"\n]+)"', re.IGNORECASE)
_VMF_MODEL_RE = re.compile(r'"model"\s*"([^"\n]+)"', re.IGNORECASE)
_VMF_SKYNAME_RE = re.compile(r'"skyname"\s*"([^"\n]+)"', re.IGNORECASE)

# Source 1 skyboxes are 6 .vmts named `<skyname>_<face>.vmt` under
# `materials/skybox/`. Map's worldspawn carries `"skyname" "<name>"`;
# the engine resolves all six faces at runtime.
_SKYBOX_FACES = ("up", "dn", "lf", "rt", "ft", "bk")


def _collect_vmf_refs(vmf_path: Path) -> list[str]:
    """Return refs-file format paths for every material/model the .vmf
    references. Filters out tools/* materials (they're cs2-native, no
    conversion needed) and obvious non-asset values. Sorted, deduped.

    Source1import looks each ref up in the import-game search path
    (== <csgo_install>/csgo/, which transparently mounts pak01_*.vpk).
    Refs that resolve get converted to .vmat / .vmdl; refs that don't
    print an error but don't block the rest of the batch."""
    try:
        text = vmf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    refs: set[str] = set()
    for m in _VMF_MATERIAL_RE.finditer(text):
        val = m.group(1).strip().replace("\\", "/").lower()
        if not val:
            continue
        # tools/ materials ship with cs2; never need s1->s2 conversion.
        if val.startswith("tools/"):
            continue
        # a small number of .vmf assets reference the .vmt by extension.
        if val.endswith(".vmt"):
            val = val[:-4]
        if not val:
            continue
        refs.add(f"materials/{val}.vmt")
    for m in _VMF_MODEL_RE.finditer(text):
        val = m.group(1).strip().replace("\\", "/").lower()
        if not val:
            continue
        # env_sprite / env_glow / point_spotlight entities reuse the
        # `"model"` key for sprite refs whose value is a .vmt material or
        # .spr Source-1 sprite path. Neither is a model and neither
        # converts via the .mdl pipeline -- blindly appending .mdl yields
        # bogus paths like `models/sprites/glow04.vmt.mdl` that the
        # importer chokes on.
        if val.endswith((".vmt", ".spr")):
            continue
        # entity-brush refs ("*0", "*1", ...) point at an embedded brush
        # volume rather than a model file.
        if val.startswith("*"):
            continue
        # only accept refs that are clearly under models/. Don't try to
        # auto-prefix arbitrary values -- they're almost always something
        # weird (skybox names, env_sprite sprites we missed, etc.) that
        # produces a junk path source1import can't find.
        if not val.endswith(".mdl"):
            if not val.startswith("models/"):
                continue
            val = f"{val}.mdl"
        if not val.startswith("models/"):
            continue
        refs.add(val)
    for m in _VMF_SKYNAME_RE.finditer(text):
        sky = m.group(1).strip().replace("\\", "/").lower()
        if not sky:
            continue
        # worldspawn may carry `"skyname" "skybox/dust"` or just `"dust"`;
        # normalise to bare basename so we can build the per-face refs.
        sky = sky.rsplit("/", 1)[-1]
        if sky.endswith(".vmt"):
            sky = sky[:-4]
        if not sky:
            continue
        # Skybox face files in source-1 are named `<skyname><face>.vmt`
        # in older Valve content (hl2: `sky_day01_01up.vmt`) and
        # `<skyname>_<face>.vmt` in newer CSGO content (`sky_dust_up.vmt`).
        # Emitting both is safe -- source1import skips refs it can't
        # resolve, and the ones that DO match the actual files in
        # pak01_*.vpk get converted to the single composite .vmat CS2
        # expects.
        for face in _SKYBOX_FACES:
            refs.add(f"materials/skybox/{sky}{face}.vmt")
            refs.add(f"materials/skybox/{sky}_{face}.vmt")
        # CS2 also asks for the *combined* skybox material at
        # `materials/skybox/<skyname>.vmt` (no face suffix) -- e.g.
        # `materials/skybox/sky_dust.vmt`. Source-1 didn't ship a real
        # .vmt at that path, but pak01_*.vpk in modern CSGO sometimes
        # carries one for the HDR cubemap reference. Emit both the
        # `sky_<name>` and bare-name variants for source1import to try.
        refs.add(f"materials/skybox/{sky}.vmt")
        if not sky.startswith("sky_"):
            refs.add(f"materials/skybox/sky_{sky}.vmt")
    return sorted(refs)


def _format_refs_kv(refs: list[str]) -> str:
    """Serialise refs in the `importfilelist { "file" "..." }` KV format
    Keller's `ListStringFromRefs` expects. Always emits a syntactically
    valid file (an empty refs list -> empty KV block)."""
    body = ["importfilelist", "{"]
    for r in refs:
        body.append(f'\t"file" "{r}"')
    body.append("}")
    return "\n".join(body) + "\n"


def _write_prefab_refs_from_staged(
    cfg: Config,
    addon: str,
    mapname: str,
    staged_root: Path | None = None,
    vmf_path: Path | None = None,
) -> int:
    """Generate the `<map>_prefab_refs.txt` Keller's import wrapper reads
    after the initial source1import pass. The wrapper walks this file to
    drive per-asset s1->s2 conversion (`source1import -usefilelist`) and
    s2 compilation (`resourcecompiler -filelist`).

    source1import only writes this file when the source map uses prefabs,
    so for non-prefab maps with custom textures (e.g. recoil_master) the
    per-asset conversion never runs and the map ships without .vmat_c for
    any of its workshop materials -- every face renders as a missing
    checkerboard at runtime.

    Two ref sources are merged into the output:
      1. files found under `staged_root` -- workshop content extracted
         from the .bsp pakfile.
      2. `"material"` / `"model"` values read straight out of the .vmf --
         every asset the map *references*, including base CSGO assets
         (metalcombine002, w_pist_glock18, etc.) and external dependency
         packs (hr_metal, gg_tibet, ...) that aren't part of the .bsp
         pakfile but *are* on disk inside `<csgo>/pak01_*.vpk`.
    Source1import resolves each ref against the import-game search path
    (which mounts the csgo install's vpks transparently); whatever it
    finds becomes a .vmat / .vmdl in the addon, whatever it can't print
    a per-ref error and the rest of the batch continues.

    Returns the number of refs written. An empty refs list still produces
    a well-formed empty KV stub for the no-prefab + no-pakfile-content
    case (matches the prior `_ensure_prefab_refs_stub` behaviour).

    Overwrites any pre-existing file. We re-run on every `csgo2cs2 port`,
    so refreshing the refs is correct -- the .vmf may have changed, the
    staged set may have changed, or this script may have learned to emit
    new ref kinds since the last run. (Source1import overwrites this
    file later in the importer for prefab maps anyway, so we never race
    with its output -- we always run *before* the importer.)"""
    maps_dir = _content_addon_maps_dir(cfg, addon)
    if maps_dir is None:
        return 0
    try:
        maps_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # filesystem layout may not be writable yet (steam tools not
        # installed); the importer would surface its own error in that
        # case, so don't fail the pipeline here.
        return 0
    out = maps_dir / f"{mapname}_prefab_refs.txt"
    refs = _build_refs_for_addon(staged_root, vmf_path)
    try:
        out.write_text(_format_refs_kv(refs), encoding="utf-8")
    except OSError:
        return 0
    return len(refs)


def _build_refs_for_addon(
    staged_root: Path | None,
    vmf_path: Path | None,
) -> list[str]:
    """Merge staged-content refs + .vmf-scanned refs into the sorted
    ref list we feed to source1import. Exposed separately from
    `_write_prefab_refs_from_staged` so other stages (e.g. the pak01
    case-fix preprocessor) can see the same view of refs without
    re-deriving the merge logic."""
    merged: set[str] = set()
    if staged_root is not None and staged_root.is_dir():
        merged.update(_collect_staged_refs(staged_root))
    if vmf_path is not None and vmf_path.is_file():
        merged.update(_collect_vmf_refs(vmf_path))
    return sorted(merged)


def _ensure_prefab_refs_stub(cfg: Config, addon: str, mapname: str) -> None:
    """Back-compat wrapper around `_write_prefab_refs_from_staged` for
    callers that don't have a staged root or .vmf handy (tests, dry-runs).
    Writes an empty KV stub."""
    _write_prefab_refs_from_staged(cfg, addon, mapname, staged_root=None)


# -- Keller script content-dir fix ------------------------------------------
# Earlier iterations injected `-src1contentdir <staged>` into Keller's
# `-usefilelist` invocations on the theory that source1import wouldn't
# find the staged .vmts otherwise. That theory was wrong: source1import
# DOES find the file via the import-content search path, but its
# CONVERSION step then looks up dependencies (proxy shaders, parent .vmt
# refs, .tga/.vtf fallbacks) on the import-GAME path (the CS:GO mod
# dir). With `-src1contentdir` pointing at staged/, the file is found
# but conversion fails silently with `*** Error Importing`.
#
# Per Valve's official import-tool docs[1], custom .vmt/.vtf/.mdl files
# must live under `<csgo_install>/csgo/materials/...` and
# `<csgo_install>/csgo/models/...`. We mirror staged content into the
# CS:GO tree before invoking source1import (see _mirror_into_csgo) and
# leave Keller's script unpatched.
#
# We also actively REVERT the old patch if a previous run of csgo2cs2
# applied it, so the user doesn't have to `tools install` to recover.
#
# [1]: https://developer.valvesoftware.com/wiki/Source_2/Docs/Level_Design/Import_Tool_Documentation

_CONTENTDIR_MARKER = "# csgo2cs2: patched -src1contentdir into -usefilelist"

_KELLER_USEFILELIST_MDLS = (
    'importRefsCmd = "source1import -retail -nop4 -nop4sync '
    '-src1gameinfodir \\"%s\\" -s2addon %s -game csgo '
    '-usefilelist \\"%s\\"" % ( s1gamecsgo, s2addon, temp_refs )'
)
_KELLER_USEFILELIST_MDLS_FIXED = (
    'importRefsCmd = "source1import -retail -nop4 -nop4sync '
    '-src1gameinfodir \\"%s\\" -src1contentdir \\"%s\\" -s2addon %s -game csgo '
    '-usefilelist \\"%s\\"" % ( s1gamecsgo, s1contentcsgo, s2addon, temp_refs )'
)

_KELLER_USEFILELIST_REFS = (
    'importcmd = "source1import -retail -nop4 -nop4sync '
    '-src1gameinfodir \\"" + s1gamecsgo + "\\" -s2addon " '
    '+ s2addon + " -game csgo -usefilelist \\"" + refsFile + "\\""'
)
_KELLER_USEFILELIST_REFS_FIXED = (
    'importcmd = "source1import -retail -nop4 -nop4sync '
    '-src1gameinfodir \\"" + s1gamecsgo + "\\" -src1contentdir \\"" '
    '+ s1contentcsgo + "\\" -s2addon " '
    '+ s2addon + " -game csgo -usefilelist \\"" + refsFile + "\\""'
)


def _unpatch_importer_contentdir(script_path: Path) -> bool:
    """Reverse an old (incorrect) `-src1contentdir` injection if a
    previous csgo2cs2 run left the marker. No-op if the script is
    already pristine. Idempotent. Returns True iff we changed anything.

    The mirror-into-csgo approach (see _mirror_into_csgo) is the real
    fix; this function exists to heal scripts patched by older builds.
    """
    try:
        text = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if _CONTENTDIR_MARKER not in text:
        return False
    changed = False
    if _KELLER_USEFILELIST_MDLS_FIXED in text:
        text = text.replace(_KELLER_USEFILELIST_MDLS_FIXED, _KELLER_USEFILELIST_MDLS)
        changed = True
    if _KELLER_USEFILELIST_REFS_FIXED in text:
        text = text.replace(_KELLER_USEFILELIST_REFS_FIXED, _KELLER_USEFILELIST_REFS)
        changed = True
    # Strip the trailing marker line (with or without a leading newline).
    text = text.replace(f"\n{_CONTENTDIR_MARKER}\n", "")
    text = text.replace(f"{_CONTENTDIR_MARKER}\n", "")
    text = text.replace(_CONTENTDIR_MARKER, "")
    if not changed:
        return False
    try:
        script_path.write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


# -- mirror staged content into CS:GO csgo/ ---------------------------------
# Valve's source1import looks for custom .vmt/.vtf/.mdl files under the
# `-src1gameinfodir` (== `<csgo_install>/csgo/`), not under a separate
# `-src1contentdir`. Without mirroring, every workshop .vmt is rejected
# with `*** Error Importing` and no per-file detail.
#
# We refuse to overwrite anything that already exists in the CS:GO tree
# (those are the user's base CSGO assets) and record the list of newly
# created files to a manifest so cleanup can target only files we wrote.

_CSGO_MIRROR_SUBDIRS = ("materials", "models")
_CSGO_MIRROR_MANIFEST = ".csgo_mirror_manifest"


def _append_mirror_manifest(workspace: Path, new_files: list[str]) -> None:
    """Append `new_files` to the mirror manifest at
    `<workspace>/.csgo_mirror_manifest`. Used by both the staged-content
    mirror and the pak01 case-fix extractor so the cleanup pass removes
    every loose file we wrote regardless of which step wrote it."""
    if not new_files:
        return
    manifest_path = workspace / _CSGO_MIRROR_MANIFEST
    existing = ""
    if manifest_path.is_file():
        try:
            existing = manifest_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    manifest_path.write_text(existing + "\n".join(new_files) + "\n", encoding="utf-8")


def _mirror_into_csgo(
    staged_root: Path,
    s1_gameinfo_dir: Path,
    workspace: Path,
) -> int:
    """Mirror `<staged>/materials` and `<staged>/models` into the user's
    `<csgo>/materials` and `<csgo>/models` trees so source1import can
    find them. Per Valve's import-tool docs, this is where the importer
    expects pre-compiled custom content (vmt/vtf/mdl) to live.

    Skips files that already exist on the target side (preserves base
    CSGO content). Appends newly-written paths to
    `<workspace>/.csgo_mirror_manifest` so a later `unmirror` pass can
    roll back just the files we created.
    """
    if not staged_root.is_dir() or not s1_gameinfo_dir.is_dir():
        return 0
    new_files: list[str] = []
    for sub in _CSGO_MIRROR_SUBDIRS:
        src_root = staged_root / sub
        if not src_root.is_dir():
            continue
        dst_root = s1_gameinfo_dir / sub
        for item in src_root.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(src_root)
            target = dst_root / rel
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            new_files.append(str(target))
    _append_mirror_manifest(workspace, new_files)
    return len(new_files)


# Source 1 .vmts use loose `$<param>` directives whose values are paths
# (case-folded on Windows fs but case-sensitive against pak01_*.vpk's
# index). The CSGO ship .vmts sometimes have a mismatched case in their
# $basetexture / $bumpmap / etc. values (e.g. `"$basetexture"
# "Dev/dev_hazzardstripe01a"` vs pak01's lowercase
# `materials/dev/dev_hazzardstripe01a.vtf`). Source1import's case-
# sensitive VPK lookup then fails silently and the .vmat is never
# written. We sidestep this by pre-extracting the .vmt + dependent
# .vtf(s) from pak01 to LOOSE files under `<csgo>/materials/...` --
# Windows fs is case-insensitive so source1import resolves them no
# matter what case the .vmt uses internally.
_VMT_TEX_PARAM_RE = re.compile(
    r'"?\$(\w+)"?\s+"([^"\r\n]+)"',
    re.IGNORECASE,
)


def _extract_case_fixed_pak01_assets(
    refs: list[str],
    install_dir: Path,
    workspace: Path,
) -> int:
    """For each .vmt ref in `refs` whose source .vmt in pak01_*.vpk has
    a `$<param>` texture value with case-mismatched pak01 entries,
    extract the .vmt + its dependent .vtf(s) to LOOSE files under
    `<install>/csgo/materials/...`. Source1import resolves loose files
    case-insensitively via Windows fs, so the case mismatch is no
    longer fatal.

    The `vpk` PyPI package is an optional runtime dependency; if it's
    not installed we no-op and warn. Records new loose files to the
    mirror manifest so cleanup removes them too.
    """
    if not refs:
        return 0
    pak01 = install_dir / "csgo" / "pak01_dir.vpk"
    if not pak01.is_file():
        return 0
    try:
        import vpk as _vpk  # type: ignore[import-not-found]
    except ImportError:
        warn(
            "Skipping pak01 .vmt case-fix preprocessor: `vpk` package "
            "not installed. Run `pip install vpk` to enable. Base-CSGO "
            "materials with mixed-case $basetexture paths may render as "
            "checkerboards."
        )
        return 0

    try:
        archive = _vpk.VPK(str(pak01))
        case_map: dict[str, str] = {}
        for path in archive:
            case_map[path.lower().replace("\\", "/")] = path
    except Exception as exc:  # noqa: BLE001
        warn(f"Skipping pak01 case-fix: couldn't read pak01_dir.vpk ({exc}).")
        return 0

    csgo_root = install_dir / "csgo"
    new_files: list[str] = []
    for ref in refs:
        if not ref.lower().endswith(".vmt"):
            continue
        ref_key = ref.lower().replace("\\", "/")
        real_vmt = case_map.get(ref_key)
        if real_vmt is None:
            continue
        try:
            vmt_bytes = archive.get_file(real_vmt).read()
        except Exception:  # noqa: BLE001
            continue
        try:
            vmt_text = vmt_bytes.decode("latin-1", errors="replace")
        except Exception:  # noqa: BLE001
            continue

        # Find all $-prefixed texture-path values that could resolve to
        # a pak01 entry under materials/. Skip non-path values (e.g.
        # "$surfaceprop" "concrete", "$envmap" "env_cubemap").
        candidates: set[str] = set()
        has_case_mismatch = False
        for m in _VMT_TEX_PARAM_RE.finditer(vmt_text):
            value = m.group(2).strip()
            if not value or "/" not in value and "\\" not in value:
                continue
            v = value.replace("\\", "/")
            for ext in (".vtf",):
                cand = f"materials/{v}{ext}".lower()
                if cand in case_map:
                    real = case_map[cand]
                    candidates.add(real)
                    if real.lower() != f"materials/{v}{ext}".lower() or (
                        real != f"materials/{v}{ext}"
                    ):
                        # Real-case path differs from literal value's
                        # case -> source1import's VPK lookup will fail.
                        if real != f"materials/{v}{ext}":
                            has_case_mismatch = True
                    break
        if not has_case_mismatch:
            continue

        # Stage the .vmt loose (Windows fs is case-insensitive, so
        # source1import resolves the $basetexture via fs even if the
        # .vmt's literal path differs from the .vtf's actual filename).
        loose_vmt = csgo_root / real_vmt
        if not loose_vmt.exists():
            try:
                loose_vmt.parent.mkdir(parents=True, exist_ok=True)
                loose_vmt.write_bytes(vmt_bytes)
                new_files.append(str(loose_vmt))
            except OSError:
                continue

        # Stage each dependent .vtf loose, too. If a .vtf was already
        # staged by the workshop mirror we leave it alone.
        for vtf_pak_path in candidates:
            loose_vtf = csgo_root / vtf_pak_path
            if loose_vtf.exists():
                continue
            try:
                vtf_bytes = archive.get_file(vtf_pak_path).read()
                loose_vtf.parent.mkdir(parents=True, exist_ok=True)
                loose_vtf.write_bytes(vtf_bytes)
                new_files.append(str(loose_vtf))
            except Exception:  # noqa: BLE001
                continue

    _append_mirror_manifest(workspace, new_files)
    return len(new_files)


def _unmirror_from_csgo(workspace: Path) -> int:
    """Remove files written by an earlier `_mirror_into_csgo` call,
    using the manifest under `<workspace>/.csgo_mirror_manifest`. Does
    NOT touch any other files in the CS:GO tree. Best-effort cleanup of
    now-empty parent dirs. Idempotent."""
    manifest_path = workspace / _CSGO_MIRROR_MANIFEST
    if not manifest_path.is_file():
        return 0
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    paths = [Path(line.strip()) for line in raw.splitlines() if line.strip()]
    removed = 0
    for p in paths:
        try:
            if p.is_file():
                p.unlink()
                removed += 1
        except OSError:
            continue
    # Walk parent dirs bottom-up and remove now-empty ones.
    parents = sorted({p.parent for p in paths}, key=lambda d: -len(d.parts))
    for parent in parents:
        try:
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            continue
    try:
        manifest_path.unlink()
    except OSError:
        pass
    return removed


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
    resolved = importer.resolve()
    if not resolved:
        error(
            "import_map_community.py was not found. Run `csgo2cs2 tools install` "
            "to fetch a known-good copy, or set `import_script_path` in config."
        )
        return 1
    if _unpatch_importer_contentdir(resolved):
        info(
            "Reverted stale -src1contentdir injection in "
            "import_map_community.py from an older csgo2cs2 build."
        )

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

    # Per Valve's import-tool docs, source1import expects custom
    # vmt/vtf/mdl content to live under `<csgo_install>/csgo/materials/`
    # and `<csgo_install>/csgo/models/`. Without mirroring staged content
    # there, every workshop .vmt is silently rejected during the
    # per-asset conversion phase. We refuse to overwrite anything that
    # already exists in CS:GO csgo/ (those are the user's base assets)
    # and record what we wrote so `csgo2cs2 cleanup-mirror` can roll it
    # back later without touching base content.
    mirrored = _mirror_into_csgo(s1_content_dir, s1_gameinfo_dir, workspace)
    if mirrored:
        success(
            f"Mirrored {mirrored} workshop asset(s) into "
            f"{s1_gameinfo_dir} for source1import to find."
        )

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

    # Pre-build the refs file Keller's wrapper reads after the initial
    # source1import pass. source1import only writes `<map>_prefab_refs.txt`
    # for maps with prefabs; for non-prefab maps the file never appears
    # and (a) the wrapper crashes with FileNotFoundError, OR (b) we ship
    # a stub but the per-asset conversion phase no-ops -- yielding a map
    # whose textures all render as missing checkerboards in CS2.
    # Populating it from staged/ + the .vmf's material/model references
    # drives the real .vmt->.vmat->.vmat_c conversion + .mdl->.vmdl->.vmdl_c
    # conversion the map needs. The .vmf refs catch base CSGO assets the
    # map uses (metalcombine002, wood_int_10, w_pist_*, ...) that aren't
    # in the .bsp pakfile but live in the user's csgo/pak01_*.vpk -- so
    # source1import resolves them against the import-game search path and
    # converts them too.
    vmf_for_refs = s1_content_dir / "maps" / f"{mapname}.vmf"
    if not vmf_for_refs.is_file():
        vmf_for_refs = None  # type: ignore[assignment]
    n_refs = _write_prefab_refs_from_staged(cfg, addon, mapname, s1_content_dir, vmf_for_refs)
    if n_refs:
        info(
            f"Wrote {n_refs} ref(s) to {mapname}_prefab_refs.txt for "
            "per-asset s1->s2 conversion (staged content + .vmf material "
            "+ model references)."
        )

    # Case-fix pre-extract: for each .vmt ref whose source in pak01_*.vpk
    # has a case-mismatched $basetexture / $bumpmap / etc. (e.g.
    # `Dev/dev_hazzardstripe01a` vs pak01's `dev/dev_hazzardstripe01a`),
    # stage the .vmt + dependent .vtfs as LOOSE files under <csgo>/. The
    # Windows fs is case-insensitive, so source1import resolves them
    # regardless of the .vmt's literal path case -- whereas its
    # case-SENSITIVE pak01 lookup would otherwise drop the .vmt silently.
    refs_for_fix = _build_refs_for_addon(s1_content_dir, vmf_for_refs)
    n_case_fixed = _extract_case_fixed_pak01_assets(refs_for_fix, install, workspace)
    if n_case_fixed:
        success(
            f"Pre-extracted {n_case_fixed} pak01 asset(s) with mixed-case "
            "$basetexture paths to loose files (workaround for "
            "source1import's case-sensitive VPK lookup)."
        )

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

    # cs_mdl_import emits .vmdl files where every BodyGroupChoice block
    # is missing its `name = "..."` field, which makes resourcecompiler
    # fail every CSGO weapon model. Patch all .vmdls under the addon
    # before resourcecompiler / Hammer Build sees them.
    n_vmdl_files, n_vmdl_choices = _patch_vmdl_bodygroup_choices(cfg, addon)
    if n_vmdl_files:
        info(
            f"Patched {n_vmdl_choices} BodyGroupChoice block(s) across "
            f"{n_vmdl_files} .vmdl file(s) (cs_mdl_import omits the "
            "`name` field, resourcecompiler rejects empty names)."
        )

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
            success(f"Import completed for `{mapname}` (post-process warnings ignored).")
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
