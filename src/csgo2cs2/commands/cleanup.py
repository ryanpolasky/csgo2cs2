# undo install-side changes recorded by a port manifest.

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_config
from ..logging_utils import error, header, info, success, warn
from ..utils.backup import backup_path_for, restore_file
from ..utils.manifest import PortManifest
from ..utils.url import parse_workshop_id


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "cleanup",
        help="Undo install-side mutations recorded by a prior port.",
    )
    p.add_argument(
        "url_or_id",
        help="Workshop URL or numeric ID of the prior port to clean up.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without changing anything.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    workshop_id = parse_workshop_id(args.url_or_id)
    if not workshop_id:
        error(f"Could not extract a Workshop ID from {args.url_or_id!r}")
        return 2

    workspace = Path(cfg.workspace_dir).expanduser() / workshop_id
    manifest_path = workspace / "manifest.json"
    if not manifest_path.exists():
        error(f"No manifest found for {workshop_id} at {manifest_path}")
        return 1

    manifest = PortManifest.load(manifest_path)
    info(f"Workshop ID: {manifest.workshop_id}")
    info(f"Addon:       {manifest.addon_name}")
    info(f"Manifest:    {manifest_path}")

    issues = 0

    header("Copied files")
    if not manifest.copied_files:
        info("(none recorded)")
    for c in manifest.copied_files:
        dest = Path(c.dest)
        if not dest.exists():
            warn(f"already gone: {dest}")
            continue
        if c.overwrote_existing:
            warn(
                f"skipped (would clobber pre-existing file): {dest}; "
                "manual review needed"
            )
            issues += 1
            continue
        if args.dry_run:
            info(f"[dry-run] would delete: {dest}")
        else:
            try:
                dest.unlink()
                success(f"deleted: {dest}")
            except OSError as exc:
                error(f"failed to delete {dest}: {exc}")
                issues += 1

    header("Renamed files")
    if not manifest.renamed_files:
        info("(none recorded)")
    for r in manifest.renamed_files:
        original = Path(r.original)
        renamed = Path(r.renamed_to)
        if original.exists():
            warn(f"original already restored: {original}")
            continue
        if not renamed.exists():
            warn(f"renamed copy missing: {renamed}")
            issues += 1
            continue
        if args.dry_run:
            info(f"[dry-run] would rename {renamed} -> {original}")
        else:
            try:
                renamed.rename(original)
                success(f"restored: {original}")
            except OSError as exc:
                error(f"failed to restore {original}: {exc}")
                issues += 1

    header("Patched files")
    if not manifest.patched_files:
        info("(none recorded)")
    for p in manifest.patched_files:
        path = Path(p)
        backup = backup_path_for(path)
        if not backup.exists():
            warn(f"no backup beside {path}; cannot restore")
            issues += 1
            continue
        if args.dry_run:
            info(f"[dry-run] would restore {path} from {backup.name}")
        else:
            if restore_file(path):
                success(f"restored: {path}")
            else:
                error(f"failed to restore {path}")
                issues += 1

    header("Summary")
    if issues:
        warn(f"{issues} item(s) need manual review.")
        return 1
    if args.dry_run:
        info("Dry run complete. Re-run without --dry-run to apply.")
    else:
        success("Cleanup complete.")
    return 0
