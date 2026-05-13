# Bulk porting: invoke the per-map port pipeline across multiple
# workshop IDs. Serial-only (source1import is single-instance and
# Steam throttles parallel downloads). Stops on first failure by
# default so the first run surfaces problems clearly; switch to
# --continue-on-failure once a manifest of IDs is known-good.

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from ..config import Config, load_config
from ..logging_utils import error, header, info, success, warn
from ..platform_check import WindowsRequiredError
from ..utils.url import parse_workshop_id

_LINE_COMMENT_RE = re.compile(r"\s*#.*$")


@dataclass
class BulkEntry:
    """One row of the bulk-port plan + result."""

    raw: str
    workshop_id: str | None = None
    addon: str | None = None
    map_name: str | None = None
    status: str = "pending"  # pending | skipped | ok | failed
    reason: str = ""
    rc: int | None = None
    elapsed_sec: float | None = None


@dataclass
class BulkResult:
    """Aggregate result of a bulk run."""

    started_at: float
    finished_at: float = 0.0
    template: str = "{map_name}"
    stop_on_failure: bool = True
    entries: List[BulkEntry] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0

    def to_json(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "template": self.template,
            "stop_on_failure": self.stop_on_failure,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "entries": [asdict(e) for e in self.entries],
        }


# parsing ------------------------------------------------------------


def _parse_from_file(path: Path) -> List[str]:
    """Return workshop IDs/URLs from a newline-delimited file.

    Strips `# comments`, blank lines, and surrounding whitespace.
    Preserves order; deduplication happens later against the union of
    sources."""
    out: List[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        cleaned = _LINE_COMMENT_RE.sub("", raw_line).strip()
        if cleaned:
            out.append(cleaned)
    return out


def _collect_inputs(positional: Sequence[str], from_file: Path | None) -> List[str]:
    """Merge positional args + --from-file lines, preserving order
    and removing duplicates by parsed workshop ID. Invalid entries are
    kept so they get reported as failures rather than silently
    dropped."""
    combined: List[str] = list(positional)
    if from_file is not None:
        combined.extend(_parse_from_file(from_file))

    seen: set[str] = set()
    out: List[str] = []
    for raw in combined:
        wid = parse_workshop_id(raw)
        key = wid or raw  # invalid entries still dedupe by raw text
        if key in seen:
            continue
        seen.add(key)
        out.append(raw)
    return out


# addon name resolution ---------------------------------------------


def _bsp_glob(cfg: Config, workshop_id: str) -> Path | None:
    """Best-effort lookup of the downloaded BSP for a workshop ID,
    without invoking SteamCMD. Returns the .bsp Path if we can find
    one under the workspace, otherwise None."""
    workspace = Path(cfg.workspace_dir).expanduser() / workshop_id / "unwrap" / workshop_id
    if not workspace.is_dir():
        return None
    for cand in workspace.glob("*.bsp"):
        return cand
    return None


def _resolve_addon_for(
    workshop_id: str,
    template: str,
    cfg: Config,
    downloader: Callable[[Config, str], Path | None] | None = None,
) -> tuple[str, str | None]:
    """Format `template` with `{workshop_id}` + `{map_name}`. If the
    template needs `{map_name}` and we haven't downloaded the BSP yet,
    call `downloader(cfg, workshop_id)` (typically the pipeline's
    `_download`) to fetch it. Returns (addon_name, map_name).

    `downloader=None` means "don't download; return ('', None) if
    {map_name} is needed but unavailable" -- useful for tests and dry
    runs."""
    needs_map_name = "{map_name}" in template
    map_name: str | None = None
    if needs_map_name:
        bsp = _bsp_glob(cfg, workshop_id)
        if bsp is None and downloader is not None:
            try:
                bsp = downloader(cfg, workshop_id)
            except Exception as exc:  # noqa: BLE001
                # surface upstream; downloader failures shouldn't crash
                # the bulk loop -- the calling code records as failed.
                raise RuntimeError(f"download failed: {exc}") from exc
        if bsp is not None:
            map_name = bsp.stem
    try:
        addon = template.format(workshop_id=workshop_id, map_name=map_name or "")
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"bad --addon-template {template!r}: {exc}") from exc
    return addon, map_name


# already-ported probe ----------------------------------------------


def _already_ported(cfg: Config, addon: str, map_name: str | None) -> bool:
    """Return True if `<cs2_addons_path>/<addon>/maps/<map_name>.vmap`
    exists. If `cs2_addons_path` is unset or `map_name` is unknown,
    return False (we can't tell, so we play it safe and re-port)."""
    if not cfg.cs2_addons_path or not map_name:
        return False
    addon_dir = Path(cfg.cs2_addons_path) / addon
    vmap = addon_dir / "maps" / f"{map_name}.vmap"
    return vmap.is_file()


# argparse + run ----------------------------------------------------


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "port-bulk",
        help="Run the full `port` pipeline across multiple workshop IDs.",
        description=(
            "Serial bulk porter. Pass workshop URLs/IDs as positional "
            "arguments and/or in a newline-delimited file via "
            "--from-file. Each map is run through the standard `port` "
            "pipeline. Stops on the first failure by default; pass "
            "--continue-on-failure to keep going."
        ),
    )
    p.add_argument(
        "ids",
        nargs="*",
        help="Workshop URLs or numeric IDs.",
    )
    p.add_argument(
        "--from-file",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Read additional workshop URLs/IDs from PATH, one per line. "
            "`# comments` and blank lines are skipped."
        ),
    )
    p.add_argument(
        "--addon-template",
        default="{map_name}",
        help=(
            "Template for each map's CS2 addon name. Supports "
            "`{workshop_id}` and `{map_name}` placeholders. Default: "
            "`{map_name}` (uses the BSP filename stem -- the map's "
            "internal name -- so 'jungle.bsp' goes into addon 'jungle')."
        ),
    )
    p.add_argument(
        "--continue-on-failure",
        action="store_true",
        help=(
            "Don't stop the bulk run when a map fails. Default is to "
            "stop on the first failure so unknown errors surface fast."
        ),
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Re-port even if the destination addon already has a "
            "<map_name>.vmap. Default behavior is to skip "
            "already-ported entries (cheap resume after a crash)."
        ),
    )
    p.add_argument(
        "--auto",
        action="store_true",
        help="Forwarded to each `port` invocation (apply known fixes silently).",
    )
    p.add_argument(
        "--skip-import",
        action="store_true",
        help="Forwarded to each `port` invocation.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Forwarded to each `port` invocation.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Resolve workshop IDs + addon names but don't actually run "
            "the port pipeline. Useful for previewing a bulk plan."
        ),
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Write a JSON summary of the run to PATH. Default: "
            "`<workspace>/bulk-<timestamp>.json`."
        ),
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ..pipeline import _download as pipeline_download
    from ..pipeline import run_port_pipeline

    return run_bulk(
        positional=args.ids,
        from_file=args.from_file,
        addon_template=args.addon_template,
        continue_on_failure=args.continue_on_failure,
        overwrite=args.overwrite,
        auto=args.auto,
        skip_import=args.skip_import,
        debug=args.debug,
        dry_run=args.dry_run,
        manifest_path=args.manifest,
        config_path=args.config,
        downloader=pipeline_download,
        runner=run_port_pipeline,
    )


# core loop ---------------------------------------------------------
#
# `runner` and `downloader` are injection points so unit tests can
# stub them out without spinning up SteamCMD / source1import.


def run_bulk(
    *,
    positional: Sequence[str],
    from_file: Path | None,
    addon_template: str,
    continue_on_failure: bool,
    overwrite: bool,
    auto: bool,
    skip_import: bool,
    debug: bool,
    dry_run: bool,
    manifest_path: Path | None,
    config_path: str | None,
    downloader: Callable[[Config, str], Path | None] | None,
    runner: Callable[..., int],
) -> int:
    cfg = load_config(config_path)

    inputs = _collect_inputs(positional, from_file)
    if not inputs:
        error("No workshop IDs provided. Pass IDs as args and/or --from-file PATH.")
        return 2

    result = BulkResult(
        started_at=time.time(),
        template=addon_template,
        stop_on_failure=not continue_on_failure,
    )
    header(f"Bulk port: {len(inputs)} item(s)")
    info(f"Template: addon = {addon_template!r}")
    info(f"Mode: {'continue-on-failure' if continue_on_failure else 'stop-on-failure'}")
    if dry_run:
        info("--dry-run: resolution only; nothing will be ported.")

    for idx, raw in enumerate(inputs, start=1):
        entry = BulkEntry(raw=raw)
        result.entries.append(entry)
        header(f"[{idx}/{len(inputs)}] {raw}")

        wid = parse_workshop_id(raw)
        if not wid:
            entry.status = "failed"
            entry.reason = "could not parse workshop ID"
            result.failed += 1
            error(f"Invalid workshop ID/URL: {raw!r}")
            if not continue_on_failure:
                break
            continue
        entry.workshop_id = wid

        try:
            addon, map_name = _resolve_addon_for(
                wid,
                addon_template,
                cfg,
                downloader=None if dry_run else downloader,
            )
        except RuntimeError as exc:
            entry.status = "failed"
            entry.reason = f"addon resolution failed: {exc}"
            result.failed += 1
            error(str(exc))
            if not continue_on_failure:
                break
            continue
        entry.addon = addon
        entry.map_name = map_name

        if not addon:
            entry.status = "failed"
            entry.reason = "empty addon name after template expansion"
            result.failed += 1
            error(
                f"Addon template {addon_template!r} expanded to empty "
                f"string for {wid} (likely missing map_name; check the "
                "download)."
            )
            if not continue_on_failure:
                break
            continue

        info(f"workshop_id={wid} -> addon={addon!r} (map_name={map_name or '?'})")

        if not overwrite and _already_ported(cfg, addon, map_name):
            entry.status = "skipped"
            entry.reason = "already ported (pass --overwrite to re-run)"
            result.skipped += 1
            success(f"{addon}: already ported; skipping (--overwrite to re-run).")
            continue

        if dry_run:
            entry.status = "ok"
            entry.reason = "dry-run"
            result.succeeded += 1
            success(f"would port {wid} -> {addon}")
            continue

        # actual port
        t0 = time.monotonic()
        rc: int
        try:
            rc = runner(
                url_or_id=raw,
                addon=addon,
                auto=auto,
                skip_import=skip_import,
                config_path=config_path,
                debug=debug,
                overwrite=overwrite,
                create_addon=True,
            )
        except WindowsRequiredError as exc:
            entry.elapsed_sec = time.monotonic() - t0
            entry.status = "failed"
            entry.reason = f"windows required: {exc}"
            result.failed += 1
            error(str(exc))
            if not continue_on_failure:
                break
            continue
        except Exception as exc:  # noqa: BLE001
            entry.elapsed_sec = time.monotonic() - t0
            entry.status = "failed"
            entry.reason = f"unhandled: {exc!r}"
            result.failed += 1
            error(f"Port crashed for {wid}: {exc!r}")
            if not continue_on_failure:
                break
            continue

        entry.rc = rc
        entry.elapsed_sec = time.monotonic() - t0
        if rc == 0:
            entry.status = "ok"
            result.succeeded += 1
            success(f"{addon}: ported in {entry.elapsed_sec:.1f}s")
        else:
            entry.status = "failed"
            entry.reason = f"port returned rc={rc}"
            result.failed += 1
            error(f"{addon}: port failed with rc={rc}")
            if not continue_on_failure:
                break

    result.finished_at = time.time()
    _print_summary(result, len(inputs))
    _write_manifest(result, cfg, manifest_path)

    if result.failed > 0:
        return 1
    return 0


def _print_summary(result: BulkResult, total_planned: int) -> None:
    header("Bulk summary")
    info(
        f"Planned: {total_planned}  "
        f"ok: {result.succeeded}  "
        f"failed: {result.failed}  "
        f"skipped: {result.skipped}"
    )
    failures = [e for e in result.entries if e.status == "failed"]
    if failures:
        warn(f"{len(failures)} failure(s):")
        for entry in failures:
            label = entry.addon or entry.workshop_id or entry.raw
            warn(f"  - {label}: {entry.reason}")


def _write_manifest(result: BulkResult, cfg: Config, manifest_path: Path | None) -> Optional[Path]:
    if manifest_path is None:
        ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(result.started_at))
        manifest_path = Path(cfg.workspace_dir).expanduser() / f"bulk-{ts}.json"
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(result.to_json(), indent=2), encoding="utf-8")
        info(f"Bulk manifest written to {manifest_path}")
        return manifest_path
    except OSError as exc:
        warn(f"could not write bulk manifest to {manifest_path}: {exc}")
        return None
