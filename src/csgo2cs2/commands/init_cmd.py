# create or refresh the user config file.

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from ..config import Config, config_path, load_config, save_config
from ..logging_utils import header, info, success, warn
from ..utils.steam import find_csgo_install, find_steamcmd


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "init",
        help="Create a config file at ~/.csgo2cs2/config.json (auto-detects Steam install).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing config file.",
    )
    p.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Prompt for any paths we cannot auto-detect.",
    )
    p.set_defaults(func=run)


def _autodetect(cfg: Config) -> Config:
    csgo = find_csgo_install()
    if csgo and not cfg.csgo_install_path:
        cfg.csgo_install_path = str(csgo)
        success(f"detected csgo install: {csgo}")
        cs2_addons = csgo / "game" / "csgo_addons"
        cs2_bin = csgo / "game" / "bin" / "win64"
        legacy_bin = csgo / "bin"
        if cs2_addons.exists() and not cfg.cs2_addons_path:
            cfg.cs2_addons_path = str(cs2_addons)
        if cs2_bin.exists() and not cfg.cs2_bin_path:
            cfg.cs2_bin_path = str(cs2_bin)
        if legacy_bin.exists() and not cfg.legacy_csgo_bin_path:
            cfg.legacy_csgo_bin_path = str(legacy_bin)

    sc = find_steamcmd()
    if sc and not cfg.steamcmd_path:
        cfg.steamcmd_path = str(sc)
        success(f"detected steamcmd: {sc}")

    return cfg


def _prompt(field: str, current: str, prompt_fn: Callable[[str], str]) -> str:
    label = current if current else "<empty>"
    raw = prompt_fn(f"{field} [{label}]: ").strip()
    return raw or current


def _interactive(cfg: Config, prompt_fn: Callable[[str], str] = input) -> Config:
    header("Interactive setup")
    info("Press Enter to keep the current value. Empty values stay empty.")
    if not cfg.csgo_install_path:
        cfg.csgo_install_path = (
            _prompt(
                "csgo_install_path (Counter-Strike Global Offensive folder)",
                cfg.csgo_install_path or "",
                prompt_fn,
            )
            or None
        )
    if not cfg.steamcmd_path:
        cfg.steamcmd_path = (
            _prompt(
                "steamcmd_path (path to steamcmd executable)",
                cfg.steamcmd_path or "",
                prompt_fn,
            )
            or None
        )
    if not cfg.bspsource_path:
        cfg.bspsource_path = (
            _prompt(
                "bspsource_path (path to bspsrc.bat / bspsrc.sh / bspsrc.jar)",
                cfg.bspsource_path or "",
                prompt_fn,
            )
            or None
        )
    cfg.steam_login = (
        _prompt(
            "steam_login (username, blank for anonymous)",
            cfg.steam_login or "",
            prompt_fn,
        )
        or None
    )
    cfg.default_skybox = _prompt(
        "default_skybox",
        cfg.default_skybox,
        prompt_fn,
    )
    return cfg


def run(args: argparse.Namespace) -> int:
    path = config_path(args.config)
    if path.exists() and not args.force:
        cfg = load_config(args.config)
        info(f"Loading existing config: {path}")
    elif path.exists() and args.force:
        warn(f"Overwriting {path}")
        cfg = Config()
    else:
        cfg = Config()

    cfg = _autodetect(cfg)

    if args.interactive:
        cfg = _interactive(cfg)

    saved = save_config(cfg, args.config)
    success(f"Wrote config to {saved}")
    info(
        "Next: run `csgo2cs2 tools install` to fetch SteamCMD/BSPSource into a "
        "local cache, then `csgo2cs2 doctor` to verify."
    )
    if not Path(saved).parent.exists():
        warn(f"Workspace dir {Path(saved).parent} does not exist yet.")
    return 0
