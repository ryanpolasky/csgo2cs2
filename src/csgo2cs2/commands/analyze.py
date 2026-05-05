# analyze a vmf and optionally apply safe text fixes.

from __future__ import annotations

import argparse
from pathlib import Path

from .. import fixers  # noqa: F401  (registers fixers on import)
from ..analyzers.vmf import analyze_vmf
from ..config import load_config
from ..fixers.base import apply_all
from ..logging_utils import error, header, info, success, warn


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "analyze",
        help="Report known issues in a VMF and optionally apply fixes.",
    )
    p.add_argument("vmf", help="Path to the .vmf file")
    p.add_argument(
        "--fix",
        action="store_true",
        help="Apply auto-fixes in place (writes a `.csgo2cs2.bak` backup first).",
    )
    p.add_argument(
        "--output",
        "-o",
        default=None,
        help="With --fix, write to a different path instead of overwriting.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    vmf = Path(args.vmf).expanduser()
    if not vmf.exists():
        error(f"VMF not found: {vmf}")
        return 2

    text = vmf.read_text(encoding="utf-8", errors="ignore")
    analysis = analyze_vmf(text, default_skybox=cfg.default_skybox)

    header("Skybox")
    if analysis.skyname:
        info(f"skyname = {analysis.skyname}")
    else:
        warn("skyname not present in worldspawn")

    header("Entities")
    info(f"Total entities: {analysis.total_entities}")
    info(f"Unique classes: {len(analysis.class_counts)}")

    header("Findings")
    if not analysis.findings:
        success("No blocking issues detected.")
        return 0

    for f in analysis.findings:
        marker = "[fix]" if f.fixable else "[ ]"
        warn(f"{marker} {f.issue_id}: {f.message}")

    if not args.fix:
        info("Re-run with `--fix` to apply auto-fixes for entries marked [fix].")
        return 1

    header("Applying fixes")
    new_text, results = apply_all(text, analysis.findings)
    applied = [r for r in results if r.applied]
    if not applied:
        warn("No fixes applied (no fixers matched the findings).")
        return 1

    out_path = Path(args.output).expanduser() if args.output else vmf
    if out_path == vmf:
        backup = vmf.with_name(vmf.name + ".csgo2cs2.bak")
        if not backup.exists():
            backup.write_bytes(vmf.read_bytes())
            info(f"Backup written: {backup}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(new_text, encoding="utf-8")

    for r in applied:
        success(f"{r.issue_id}: {r.detail}")
    info(f"Wrote: {out_path}")
    return 0
