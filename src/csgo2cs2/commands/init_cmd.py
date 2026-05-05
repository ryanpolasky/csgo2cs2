# create or refresh the user config file.

from __future__ import annotations

import argparse

from ..config import Config, config_path, load_config, save_config
from ..logging_utils import info, success, warn


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "init",
        help="Create a default config file at ~/.csgo2cs2/config.json",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing config file with a fresh default.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    path = config_path(args.config)
    if path.exists() and not args.force:
        warn(f"Config already exists at {path}. Use --force to overwrite.")
        return 0

    cfg = Config() if args.force else load_config(args.config)
    saved = save_config(cfg, args.config)
    success(f"Wrote default config to {saved}")
    info(
        "Edit it to point at your SteamCMD, BSPSource, VPKEdit, and CS2 install. "
        "See config.example.json in the repo for a Windows reference."
    )
    return 0
