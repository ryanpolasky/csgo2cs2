# Windows long-path helpers.
#
# Windows historically caps paths at MAX_PATH (260 chars). Modern
# Windows supports longer paths via the `\\?\` prefix on file APIs, or
# by enabling the "LongPathsEnabled" registry key (requires opt-in per
# app via manifest). Most subprocess tools we shell out to (steamcmd,
# BSPSource via Java, the import script via Python) do NOT have the
# long-path manifest set, so even on a registry-enabled system they
# will reject a 270-char path.
#
# Workshop content paths look like:
#   <steamcmd_root>/steamapps/workshop/content/730/<workshop_id>/<map>.bsp
# Add a workspace_dir on top of that and a long username + a long map
# name and you can hit MAX_PATH on a default install.
#
# Strategy:
#   - `is_too_long(path)` flags paths over a safety budget so the
#     preflight check can warn early.
#   - `extended_path(path)` returns the `\\?\` form for our own file
#     operations; we never pass this to external tools.
#   - The actual fix on Windows is "use a shorter workspace_dir" -- we
#     surface that as the recommendation.

from __future__ import annotations

import sys
from pathlib import Path
from typing import Union

# Windows MAX_PATH minus a small buffer for filenames the importer may
# create relative to a given root. The actual ceiling depends on which
# specific tool fails first; this leaves room for a 60-char child path
# inside whatever root we are checking.
WIN_MAX_PATH = 260
WIN_SAFE_BUDGET = 200


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_too_long(path: Union[str, Path], *, budget: int = WIN_SAFE_BUDGET) -> bool:
    if not is_windows():
        return False
    s = str(path)
    return len(s) >= budget


def extended_path(path: Union[str, Path]) -> str:
    r"""Return the \\?\ extended form of a Windows path for our own I/O.

    On non-Windows the input is returned unchanged. UNC paths get the
    \\?\UNC\ prefix. Already-extended paths are returned unchanged.
    """
    s = str(path)
    if not is_windows():
        return s
    if s.startswith("\\\\?\\"):
        return s
    # Detect UNC purely from the input string: a leading "\\" (and not
    # already a "\\?\" prefix). On Unix os.path.abspath has no notion
    # of UNC and would prepend cwd, so we handle UNC before reaching
    # ntpath.abspath.
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s.lstrip("\\")
    # absolute-path conversion via ntpath so it works under tests on
    # any host (not just real Windows).
    try:
        import ntpath

        abs_path = ntpath.abspath(s)
    except (OSError, ValueError):
        abs_path = s
    return "\\\\?\\" + abs_path


def shorten_for_display(path: Union[str, Path], *, max_len: int = 60) -> str:
    """Truncate a long path for log lines without losing the tail."""
    s = str(path)
    if len(s) <= max_len:
        return s
    head = s[:10]
    tail = s[-(max_len - 14) :]
    return f"{head}...{tail}"
