# `csgo2cs2 list` --- enumerate prior ports under the workspace dir.

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Tuple

from ..config import load_config
from ..logging_utils import info, warn
from ..utils.manifest import PortManifest


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "list",
        help="List prior ports tracked under workspace_dir.",
    )
    p.add_argument(
        "--paths-only",
        action="store_true",
        help="Print bare manifest paths only (one per line).",
    )
    p.set_defaults(func=run)


def _scan(workspace: Path) -> List[Tuple[Path, PortManifest]]:
    out: List[Tuple[Path, PortManifest]] = []
    if not workspace.exists():
        return out
    for entry in sorted(workspace.iterdir()):
        if not entry.is_dir():
            continue
        manifest = entry / "manifest.json"
        if not manifest.exists():
            continue
        try:
            out.append((manifest, PortManifest.load(manifest)))
        except Exception as exc:  # noqa: BLE001
            warn(f"skipping unreadable manifest {manifest}: {exc}")
    return out


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    workspace = Path(cfg.workspace_dir).expanduser()
    rows = _scan(workspace)
    if not rows:
        info(f"No ports found under {workspace}.")
        return 0
    if args.paths_only:
        for manifest_path, _ in rows:
            print(manifest_path)
        return 0
    info(f"Workspace: {workspace}")
    for _manifest_path, m in rows:
        copied = len(m.copied_files)
        renamed = len(m.renamed_files)
        patched = len(m.patched_files)
        info(
            f"  {m.workshop_id:<14} addon={m.addon_name:<24} "
            f"copied={copied} renamed={renamed} patched={patched}"
        )
    return 0
