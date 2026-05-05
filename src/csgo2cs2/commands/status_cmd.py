# `csgo2cs2 status <id>` --- show one prior port's manifest in human form.

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_config
from ..logging_utils import error, header, info, success, warn
from ..utils.manifest import PortManifest
from ..utils.url import parse_workshop_id


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "status",
        help="Show details of a prior port (manifest contents).",
    )
    p.add_argument("url_or_id", help="Workshop URL/ID or 'local-<name>' for local ports.")
    p.set_defaults(func=run)


def _resolve_workshop_id(value: str) -> str:
    if value.startswith("local-"):
        return value
    parsed = parse_workshop_id(value)
    return parsed or value


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    workspace = Path(cfg.workspace_dir).expanduser()
    workshop_id = _resolve_workshop_id(args.url_or_id)
    manifest_path = workspace / workshop_id / "manifest.json"
    if not manifest_path.exists():
        error(f"No manifest found for {workshop_id} at {manifest_path}")
        return 1

    m = PortManifest.load(manifest_path)
    header(f"{m.workshop_id} ({m.addon_name})")
    info(f"manifest: {manifest_path}")

    header("Copied files")
    if not m.copied_files:
        info("(none)")
    for c in m.copied_files:
        marker = "!" if c.overwrote_existing else " "
        info(f" {marker} {c.dest}  <- {c.src}")
    if any(c.overwrote_existing for c in m.copied_files):
        warn("'!' = overwrote a pre-existing file; cleanup will skip these")

    header("Renamed files")
    if not m.renamed_files:
        info("(none)")
    for r in m.renamed_files:
        info(f"   {r.original} -> {r.renamed_to}")

    header("Patched files")
    if not m.patched_files:
        info("(none)")
    for p in m.patched_files:
        info(f"   {p}")

    success("Manifest read OK.")
    return 0
