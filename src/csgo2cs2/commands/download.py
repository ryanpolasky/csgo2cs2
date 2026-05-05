# download a workshop item with steamcmd.

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_config
from ..logging_utils import error, info, success, warn
from ..tools.steamcmd import CSGO_APP_ID, SteamCMD
from ..utils.paths import find_first
from ..utils.url import parse_workshop_id


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "download",
        help="Download a Workshop item via SteamCMD.",
    )
    p.add_argument("url_or_id", help="Workshop URL or numeric ID")
    p.add_argument(
        "--app-id",
        default=CSGO_APP_ID,
        help=f"Steam app ID (default: {CSGO_APP_ID})",
    )
    p.add_argument(
        "--login",
        default=None,
        help="Steam login username (overrides config). Anonymous if unset.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    workshop_id = parse_workshop_id(args.url_or_id)
    if not workshop_id:
        error(f"Could not extract a Workshop ID from {args.url_or_id!r}")
        return 2

    info(f"Workshop ID: {workshop_id}")
    info(f"App ID:      {args.app_id}")

    cmd = SteamCMD(cfg.steamcmd_path)
    if not cmd.resolve():
        error("SteamCMD is not configured. Set `steamcmd_path` in config or add it to PATH.")
        return 1

    login = args.login or cfg.steam_login
    if not login:
        warn(
            "No Steam login configured; using anonymous. Anonymous Workshop downloads "
            "for app 730 are unreliable and may fail."
        )

    info("Running SteamCMD...")
    result = cmd.download_workshop_item(workshop_id, app_id=args.app_id, login=login)
    if result.returncode != 0:
        warn(f"SteamCMD exited with code {result.returncode}")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)

    expected = cmd.expected_workshop_path(workshop_id, app_id=args.app_id)
    if expected and expected.exists():
        bsp = find_first(expected, ["*.bsp"])
        if bsp:
            success(f"Downloaded: {bsp}")
        else:
            warn(f"Workshop folder exists but no .bsp found: {expected}")
        return 0

    error(
        "Workshop content folder not found after SteamCMD run. "
        "Check the SteamCMD output above; you may need an authenticated login."
    )
    return 1
