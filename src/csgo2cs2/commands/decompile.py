# run bspsource on a bsp.

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_config
from ..logging_utils import error, info, success, warn
from ..tools.bspsource import BSPSource
from ..utils.paths import ensure_dir, find_first


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "decompile",
        help="Decompile a `.bsp` into a `.vmf` using BSPSource.",
    )
    p.add_argument("bsp", help="Path to the .bsp file")
    p.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output directory for the VMF (default: alongside the BSP).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    bsp = Path(args.bsp).expanduser()
    if not bsp.exists():
        error(f"BSP not found: {bsp}")
        return 2

    output_dir = Path(args.output).expanduser() if args.output else bsp.parent / "decompiled"
    ensure_dir(output_dir)

    bs = BSPSource(cfg.bspsource_path, java_path=cfg.java_path)
    if not bs.resolve():
        error("BSPSource is not configured. Set `bspsource_path` in config.")
        return 1

    info(f"Decompiling {bsp.name} -> {output_dir}")
    result = bs.decompile(bsp, output_dir)
    if result.returncode != 0:
        warn(f"BSPSource exited with code {result.returncode}")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)

    vmf = find_first(output_dir, ["*.vmf"])
    if vmf:
        success(f"VMF written: {vmf}")
        return 0
    error("No .vmf produced. Map may be bspProtect-protected or BSPSource may have failed.")
    return 1
