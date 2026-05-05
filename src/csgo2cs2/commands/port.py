# full pipeline command. import is windows-only.

from __future__ import annotations

import argparse

from ..logging_utils import error, info, warn
from ..platform_check import WindowsRequiredError


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "port",
        help="Full pipeline: download, decompile, analyze, and import.",
    )
    p.add_argument("url_or_id", help="Workshop URL or numeric ID")
    p.add_argument("--addon", required=True, help="CS2 addon name to import into")
    p.add_argument(
        "--auto",
        action="store_true",
        help="Apply known fixes automatically without prompting.",
    )
    p.add_argument(
        "--skip-import",
        action="store_true",
        help="Run download/decompile/analyze only; skip the Windows-only import step.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ..pipeline import run_port_pipeline

    try:
        return run_port_pipeline(
            url_or_id=args.url_or_id,
            addon=args.addon,
            auto=args.auto,
            skip_import=args.skip_import,
            config_path=args.config,
        )
    except WindowsRequiredError as exc:
        if args.skip_import:
            warn(str(exc))
            info("Re-run with the actual import step on a Windows machine.")
            return 0
        error(str(exc))
        info("Re-run with --skip-import to do download/decompile/analyze on this OS.")
        return 1
