# argparse entry point.

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from . import __version__
from .commands import analyze as cmd_analyze
from .commands import cleanup as cmd_cleanup
from .commands import decompile as cmd_decompile
from .commands import doctor as cmd_doctor
from .commands import download as cmd_download
from .commands import init_cmd as cmd_init
from .commands import list_cmd as cmd_list
from .commands import port as cmd_port
from .commands import status_cmd as cmd_status
from .commands import tools_cmd as cmd_tools
from .logging_utils import error, setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csgo2cs2",
        description="Port CS:GO Steam Workshop maps to CS2 via tool orchestration.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config JSON (default: ~/.csgo2cs2/config.json)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    cmd_init.register(sub)
    cmd_doctor.register(sub)
    cmd_tools.register(sub)
    cmd_download.register(sub)
    cmd_decompile.register(sub)
    cmd_analyze.register(sub)
    cmd_port.register(sub)
    cmd_list.register(sub)
    cmd_status.register(sub)
    cmd_cleanup.register(sub)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(verbose=args.verbose)

    try:
        return args.func(args)
    except KeyboardInterrupt:
        error("Interrupted.")
        return 130
    except Exception as exc:  # noqa: BLE001
        error(f"Unexpected error: {exc}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
