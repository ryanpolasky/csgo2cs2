# `csgo2cs2 launch <addon>` --- open cs2 with the addon active and the
# imported map loaded.
#
# windows-only because cs2.exe is windows-native; on linux/macos we print
# the command we would have run so users can paste it into a windows
# shell or a wine launcher of their choice.

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

from ..config import Config, load_config
from ..logging_utils import error, info, success, warn
from ..platform_check import is_windows


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "launch",
        help="Open Counter-Strike 2 with an imported addon active.",
    )
    p.add_argument("addon", help="cs2 addon directory name (under csgo_addons/).")
    p.add_argument(
        "--map",
        dest="mapname",
        default=None,
        help="Map name (default: auto-detect from the addon's maps/*.vmap).",
    )
    p.add_argument(
        "--hammer",
        action="store_true",
        help="Open Hammer 2 instead of running the game.",
    )
    p.add_argument(
        "--print-only",
        action="store_true",
        help="Print the command line we would run, but don't actually run it.",
    )
    p.set_defaults(func=run)


# resolve `<install>/game/csgo_addons/<addon>` from config, taking the
# explicit `cs2_addons_path` if set, otherwise deriving it from the
# canonical install layout under `cs2_bin_path` (which is what most
# users have configured via `csgo2cs2 init`).
def resolve_addon_dir(cfg: Config, addon: str) -> Path | None:
    if cfg.cs2_addons_path:
        return Path(cfg.cs2_addons_path).expanduser() / addon
    if cfg.cs2_bin_path:
        bin_path = Path(cfg.cs2_bin_path).expanduser()
        # cs2_bin_path == <install>/game/bin/win64
        # cs2_addons   == <install>/game/csgo_addons
        if bin_path.name == "win64" and bin_path.parent.name == "bin":
            install_game = bin_path.parent.parent  # <install>/game
            return install_game / "csgo_addons" / addon
    return None


# the parallel `<install>/content/csgo_addons/<addon>` dir, where Hammer
# stores the editable source .vmap. cs2 itself can only load the compiled
# `.vmap_c` under `game/`, but we look at the content side too so we can
# tell a user whose import succeeded that their map exists but hasn't
# been compiled yet -- instead of the misleading `No .vmap files found`
# error.
def resolve_content_addon_dir(cfg: Config, addon: str) -> Path | None:
    game_addon_dir = resolve_addon_dir(cfg, addon)
    if game_addon_dir is None:
        return None
    parts = list(game_addon_dir.parts)
    try:
        idx = len(parts) - 1 - parts[::-1].index("game")
    except ValueError:
        return None
    parts[idx] = "content"
    return Path(*parts)


def resolve_cs2_executable(cfg: Config) -> Path | None:
    if not cfg.cs2_bin_path:
        return None
    bin_dir = Path(cfg.cs2_bin_path).expanduser()
    if not bin_dir.is_dir():
        return None
    candidates = [bin_dir / "cs2.exe", bin_dir / "cs2"]
    for c in candidates:
        if c.exists():
            return c
    return None


# returns the first map stem found under `<addon>/maps/`. when the
# user's addon has multiple maps we still pick the first deterministic
# one and surface the alternatives via a warn, so they know to use
# `--map <name>` if it's wrong. `content_addon_dir` is the parallel
# editable-source dir under `content/` -- we union the two so a map
# that's been imported but not yet compiled (no `.vmap_c` under `game/`)
# still gets autodetected.
def autodetect_mapname(
    addon_dir: Path,
    content_addon_dir: Path | None = None,
) -> Tuple[str | None, List[str]]:
    stems: set[str] = set()
    maps_dir = addon_dir / "maps"
    if maps_dir.is_dir():
        # .vmap_c is the compiled form cs2 loads at runtime; .vmap is the
        # editable source that Hammer compiles from. Either is a valid
        # signal that this map belongs to the addon.
        for ext in ("*.vmap_c", "*.vmap"):
            stems.update(p.stem for p in maps_dir.glob(ext))
    if content_addon_dir is not None:
        content_maps = content_addon_dir / "maps"
        if content_maps.is_dir():
            stems.update(p.stem for p in content_maps.glob("*.vmap"))
    vmaps = sorted(stems)
    if not vmaps:
        return None, []
    return vmaps[0], vmaps


# True iff the compiled `<addon>/maps/<map>.vmap_c` exists under `game/`.
# cs2.exe `+map <name>` can only load a compiled .vmap_c -- the source
# .vmap is editable-only and Hammer must compile it first.
def compiled_vmap_exists(addon_dir: Path, mapname: str) -> bool:
    return (addon_dir / "maps" / f"{mapname}.vmap_c").is_file()


# True iff the editable `<content>/<addon>/maps/<map>.vmap` exists.
def source_vmap_exists(content_addon_dir: Path | None, mapname: str) -> bool:
    if content_addon_dir is None:
        return False
    return (content_addon_dir / "maps" / f"{mapname}.vmap").is_file()


def build_cmdline(exe: Path, addon: str, mapname: str | None, hammer: bool) -> List[str]:
    cmd: List[str] = [str(exe)]
    if hammer:
        # workshop tools mode opens hammer; +map is ignored. cs2 ships
        # the tools binary alongside cs2.exe; we just toggle the flag.
        cmd += ["-tools", "-game", "csgo", "-addon", addon]
        return cmd
    cmd += ["-game", "csgo", "-addon", addon]
    if mapname:
        cmd += ["+map", mapname]
    return cmd


# minimal shell-style quoting good enough for the info() one-liner.
# we deliberately don't use shlex.quote because that's posix-only and
# the user is most likely on windows anyway.
def _quote(s: str) -> str:
    if any(c.isspace() for c in s):
        return f'"{s}"'
    return s


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)

    if not cfg.cs2_bin_path:
        error("`cs2_bin_path` is not configured. Run `csgo2cs2 init --interactive`.")
        return 2

    exe = resolve_cs2_executable(cfg)
    if exe is None:
        error(
            f"Could not find cs2.exe under {cfg.cs2_bin_path}. "
            "Verify your cs2 install path and `csgo2cs2 doctor`."
        )
        return 2

    addon = args.addon
    addon_dir = resolve_addon_dir(cfg, addon)
    if addon_dir is None or not addon_dir.is_dir():
        error(
            f"Addon directory not found: {addon_dir}. "
            "Run `csgo2cs2 list` to see what's installed, or pass --map to override."
        )
        return 2

    content_addon_dir = resolve_content_addon_dir(cfg, addon)

    mapname = args.mapname
    if mapname is None and not args.hammer:
        detected, alternatives = autodetect_mapname(addon_dir, content_addon_dir)
        if detected is None:
            error(
                f"No .vmap or .vmap_c files found under "
                f"{addon_dir / 'maps'}/ or "
                f"{(content_addon_dir / 'maps') if content_addon_dir else '<content>'}/. "
                "Pass --map <name> explicitly or run `csgo2cs2 verify` to debug."
            )
            return 2
        mapname = detected
        if len(alternatives) > 1:
            warn(
                f"Multiple maps found ({', '.join(alternatives)}); "
                f"launching `{detected}`. Use --map to override."
            )

    # Surface a clear, actionable error if the .vmap exists but hasn't
    # been compiled yet. Without `.vmap_c`, `+map <name>` is a silent
    # no-op in cs2 (the game starts on the main menu, looks confusing).
    if (
        mapname is not None
        and not args.hammer
        and not compiled_vmap_exists(addon_dir, mapname)
        and source_vmap_exists(content_addon_dir, mapname)
    ):
        warn(
            f"`{mapname}.vmap` exists but `{mapname}.vmap_c` (the compiled "
            "form cs2 loads) has not been built. cs2 can't load the source "
            ".vmap directly."
        )
        info(
            f"To compile + load: `csgo2cs2 launch --hammer {addon}`, then "
            "in Hammer open the map and use Map -> Build Map. cs2 will "
            "launch with the compiled .vmap_c."
        )
        return 2

    cmd = build_cmdline(exe, addon, mapname, hammer=args.hammer)
    pretty = " ".join(_quote(a) for a in cmd)
    info(f"Launch command: {pretty}")

    if args.print_only:
        return 0

    if not is_windows():
        warn(
            "Launching cs2 requires Windows. Detected non-windows host; "
            "printed the command above for you to paste into a windows shell."
        )
        return 0

    if shutil.which(str(exe)) is None and not exe.exists():
        error(f"cs2 executable is not runnable: {exe}")
        return 2

    # detach: cs2 takes a long time to start; we don't want to block here.
    try:
        subprocess.Popen(cmd, close_fds=True)
    except OSError as exc:
        error(f"Failed to launch cs2: {exc}")
        return 1
    success(f"Launched cs2 (`{addon}`{' / ' + mapname if mapname else ''}).")
    return 0

