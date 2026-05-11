# full pipeline command. import is windows-only.

from __future__ import annotations

import argparse
from pathlib import Path

from ..logging_utils import error, info, warn
from ..platform_check import WindowsRequiredError


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "port",
        help="Full pipeline: download, decompile, analyze, and import.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "url_or_id",
        nargs="?",
        help="Workshop URL or numeric ID",
    )
    src.add_argument(
        "--bsp",
        type=Path,
        help="Skip the SteamCMD download and use a local .bsp file instead.",
    )
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
    p.add_argument(
        "--no-use-bsp",
        action="store_true",
        help="Do not pass `-usebsp` to the importer (rare; default is on).",
    )
    p.add_argument(
        "--no-merge-instances",
        action="store_true",
        help="Pass `-usebsp_nomergeinstances` to preserve func_instance entities.",
    )
    p.add_argument(
        "--skip-deps",
        action="store_true",
        help="Pass `-skipdeps` to the importer (only re-generate the .vmap).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run download/decompile/analyze and print the would-run importer "
            "command, but skip applying fixes and skip the import. Useful for "
            "previewing what `--auto` would change before committing."
        ),
    )
    p.add_argument(
        "--export-images",
        metavar="DIR",
        default=None,
        help=(
            "Also fetch the workshop preview image + metadata.json into "
            "<DIR>/<workshop_id>/ for reuse when re-publishing. Off by default."
        ),
    )
    p.add_argument(
        "--auto-addoninfo",
        action="store_true",
        help=(
            "After import, populate the addon's addoninfo.json + addonimage from "
            "the workshop metadata. Skipped if a user-authored addoninfo already "
            "exists. Off by default; soft-fails if Steam can't be reached."
        ),
    )
    p.add_argument(
        "--restart",
        action="store_true",
        help=(
            "Wipe the prior manifest stage state for this workshop ID and start "
            "from scratch. Default behavior is to resume from the first non-done "
            "stage."
        ),
    )
    p.add_argument(
        "--no-resume",
        action="store_true",
        help=(
            "Re-run every stage even if the manifest marks it done. Does not "
            "wipe the manifest (use --restart for that)."
        ),
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Allow the importer to write into an existing CS2 addon directory "
            "with the same --addon name. Off by default to prevent accidents."
        ),
    )
    p.add_argument(
        "--create-addon",
        action="store_true",
        help=(
            "If the CS2 addon directory does not exist yet, scaffold it "
            "(addoninfo.gi + empty maps/) before importing. Implied by --auto. "
            "Workshop Tools is no longer required for porting -- only for "
            "publishing to Steam Workshop later."
        ),
    )
    p.add_argument(
        "--skip-preflight",
        action="store_true",
        help=(
            "Skip the preflight environment check before downloading. "
            "Equivalent to setting CSGO2CS2_SKIP_PREFLIGHT=1."
        ),
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
            local_bsp=args.bsp,
            use_bsp=not args.no_use_bsp,
            no_merge_instances=args.no_merge_instances,
            skip_deps=args.skip_deps,
            dry_run=args.dry_run,
            export_images=args.export_images,
            auto_addoninfo=args.auto_addoninfo,
            resume=not args.no_resume,
            restart=args.restart,
            overwrite=args.overwrite,
            skip_preflight=args.skip_preflight,
            create_addon=args.create_addon,
        )
    except WindowsRequiredError as exc:
        if args.skip_import:
            warn(str(exc))
            info("Re-run with the actual import step on a Windows machine.")
            return 0
        error(str(exc))
        info("Re-run with --skip-import to do download/decompile/analyze on this OS.")
        return 1

