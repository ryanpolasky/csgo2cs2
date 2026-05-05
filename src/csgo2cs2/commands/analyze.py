# analyze a vmf and optionally apply safe text fixes.

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from .. import fixers  # noqa: F401  (registers fixers on import)
from ..analyzers import explain as explain_mod
from ..analyzers.bsp import analyze_bsp_findings, inspect_bsp
from ..analyzers.report import build_report, write_report
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
        "--bsp",
        default=None,
        help="Optional .bsp to include in the report (header + pakfile inventory).",
    )
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
    p.add_argument(
        "--report-json",
        nargs="?",
        const="-",
        default=None,
        metavar="PATH",
        help=(
            "Emit a structured JSON report. With no argument, prints to stdout; "
            "with a path, writes there."
        ),
    )
    p.add_argument(
        "--explain",
        action="store_true",
        help="After listing findings, print a curated what/why/fix block per issue_id.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "With --fix, print the unified diff of what would change without "
            "writing the file or its backup. Use this to preview fixer output."
        ),
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    vmf = Path(args.vmf).expanduser()
    if not vmf.exists():
        error(f"VMF not found: {vmf}")
        return 2

    text = vmf.read_text(encoding="utf-8", errors="ignore")
    analysis = analyze_vmf(
        text,
        default_skybox=cfg.default_skybox,
        cs2_sky_list=cfg.cs2_sky_list,
        extra_unsupported_entities=cfg.extra_unsupported_entities,
    )

    bsp_info = None
    if args.bsp:
        bsp_path = Path(args.bsp).expanduser()
        if not bsp_path.exists():
            error(f"BSP not found: {bsp_path}")
            return 2
        bsp_info = inspect_bsp(bsp_path)
        # bsp findings join the vmf findings list so report/explain handle them.
        analysis.findings.extend(analyze_bsp_findings(bsp_info))

    if args.report_json is not None:
        report = build_report(
            vmf=analysis,
            bsp=bsp_info,
            inputs={"vmf": str(vmf), "bsp": str(args.bsp or "")},
        )
        if args.report_json == "-":
            json.dump(report, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
        else:
            dest = write_report(report, Path(args.report_json))
            info(f"Report written: {dest}")
        # in --report-json mode we still surface a non-zero exit when issues
        # exist so callers can pipe + branch on it.
        return 0 if not analysis.findings else 1

    header("Skybox")
    if analysis.skyname:
        info(f"skyname = {analysis.skyname}")
    else:
        warn("skyname not present in worldspawn")

    header("Entities")
    info(f"Total entities: {analysis.total_entities}")
    info(f"Unique classes: {len(analysis.class_counts)}")

    if bsp_info is not None:
        header("BSP")
        info(f"version: {bsp_info.version}, valid_header: {bsp_info.valid_header}")
        if bsp_info.suspected_protected:
            warn(f"suspected protection marker: {bsp_info.detected_marker}")
        if bsp_info.pakfile_error:
            warn(f"pakfile: {bsp_info.pakfile_error}")
        else:
            info(f"pakfile: {bsp_info.pakfile_count} files, {bsp_info.pakfile_size} bytes")

    header("Findings")
    if not analysis.findings:
        success("No blocking issues detected.")
        return 0

    for f in analysis.findings:
        marker = "[fix]" if f.fixable else "[ ]"
        warn(f"{marker} {f.issue_id}: {f.message}")

    if args.explain:
        header("Explanations")
        seen: set[str] = set()
        for f in analysis.findings:
            if f.issue_id in seen:
                continue
            seen.add(f.issue_id)
            exp = explain_mod.get(f.issue_id)
            if exp is None:
                info(f"{f.issue_id}: (no curated explanation; message: {f.message})")
                continue
            print()
            print(explain_mod.render(exp))
        print()

    if not args.fix:
        info("Re-run with `--fix` to apply auto-fixes for entries marked [fix].")
        return 1

    header("Applying fixes" if not args.dry_run else "Computing fixes (dry run)")
    new_text, results = apply_all(text, analysis.findings)
    applied = [r for r in results if r.applied]
    if not applied:
        warn("No fixes applied (no fixers matched the findings).")
        return 1

    if args.dry_run:
        # show the unified diff, do not write anything
        for r in applied:
            info(f"{r.issue_id}: {r.detail}")
        diff = "".join(
            difflib.unified_diff(
                text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(vmf),
                tofile=str(vmf) + " (after --fix)",
                n=2,
            )
        )
        if diff:
            print()
            sys.stdout.write(diff)
            if not diff.endswith("\n"):
                sys.stdout.write("\n")
        info("Dry run: no files written. Re-run without `--dry-run` to apply.")
        return 0

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
