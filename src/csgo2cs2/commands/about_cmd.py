# `csgo2cs2 about` --- attribution + version + links.
#
# zero side effects, no config required, exit code always 0. handy as a
# `--version` superset and as a single place to point users when they ask
# "wait, who built this?".

from __future__ import annotations

import argparse

from .. import __version__
from ..logging_utils import Fore, Style

# attribution + repo link. authoritative copy lives here; the README links
# back to the same repo.
AUTHOR = "Ryan Polasky"
AUTHOR_HANDLE = "@ryanpolasky"
REPO_URL = "https://github.com/ryanpolasky/csgo2cs2"
TAGLINE = "Painless CSGO -> CS2 map porting."

# prior-art credits — surfaced both here and in README "Prior art &
# attributions" so the credit shows up wherever a user lands first.
PRIOR_ART = [
    (
        "andreaskeller96/cs2-import-scripts",
        "Py3-fixed `import_map_community.py` + canonical pitfall list.",
    ),
    ("ata4/bspsrc (BSPSource)", "BSP -> VMF decompilation."),
    ("Valve Developer Wiki", "CS2 Sky List, official entity refs."),
]


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "about",
        help="Show authorship, version, and links.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    bright = Style.BRIGHT
    reset = Style.RESET_ALL
    cyan = Fore.CYAN
    yellow = Fore.YELLOW
    dim = Style.DIM

    print(f"{bright}{cyan}csgo2cs2{reset} {bright}v{__version__}{reset}")
    print(f"  {TAGLINE}")
    print()
    print(f"  {dim}Author:{reset}  {AUTHOR} ({yellow}{AUTHOR_HANDLE}{reset})")
    print(f"  {dim}Repo:{reset}    {REPO_URL}")
    print(f"  {dim}Issues:{reset}  {REPO_URL}/issues")
    print()
    print(f"  {bright}Prior art{reset} (full credits in README):")
    for name, blurb in PRIOR_ART:
        print(f"    - {bright}{name}{reset} -- {blurb}")
    print()
    print(f"  {dim}Run `csgo2cs2 --help` for the command list,{reset}")
    print(f"  {dim}or `csgo2cs2 explain --list` for every issue id we detect.{reset}")
    return 0
