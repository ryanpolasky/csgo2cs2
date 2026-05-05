# auto-detect a steam install and the cs:go install folder.
#
# steam stores library folders in `Steam/config/libraryfolders.vdf` and
# `Steam/steamapps/libraryfolders.vdf`. each entry has a `path` we can scan
# for the cs:go install. format excerpt:
#
# "libraryfolders"
# {
#     "0"
#     {
#         "path"   "C:\\Program Files (x86)\\Steam"
#         ...
#     }
#     "1"
#     {
#         "path"   "D:\\SteamLibrary"
#         ...
#     }
# }

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import List, Optional

CSGO_FOLDER_NAME = "Counter-Strike Global Offensive"
_STEAMCMD_FILENAMES = {
    "win32": "steamcmd.exe",
    "darwin": "steamcmd",
    "linux": "steamcmd.sh",
}


def _candidate_steam_roots() -> List[Path]:
    home = Path.home()
    if sys.platform.startswith("win"):
        roots = [
            Path(r"C:\Program Files (x86)\Steam"),
            Path(r"C:\Program Files\Steam"),
        ]
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            v = os.environ.get(env)
            if v:
                roots.append(Path(v) / "Steam")
        return [r for r in roots if r.exists()]
    if sys.platform == "darwin":
        return [r for r in [home / "Library/Application Support/Steam"] if r.exists()]
    # linux + flatpak
    return [
        r
        for r in [
            home / ".steam/steam",
            home / ".local/share/Steam",
            home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        ]
        if r.exists()
    ]


_PATH_RE = re.compile(r'"path"\s*"((?:[^"\\]|\\.)*)"')


def _parse_libraryfolders_vdf(text: str) -> List[Path]:
    paths: List[Path] = []
    for m in _PATH_RE.finditer(text):
        raw = m.group(1).encode("utf-8").decode("unicode_escape", errors="ignore")
        paths.append(Path(raw))
    return paths


def _read_library_folders(steam_root: Path) -> List[Path]:
    libs: List[Path] = [steam_root]
    for rel in ("config/libraryfolders.vdf", "steamapps/libraryfolders.vdf"):
        f = steam_root / rel
        if f.exists():
            try:
                libs.extend(
                    _parse_libraryfolders_vdf(f.read_text(encoding="utf-8", errors="ignore"))
                )
            except OSError:
                continue
    # dedupe while preserving order
    seen: set[str] = set()
    out: List[Path] = []
    for p in libs:
        key = os.path.normcase(str(p))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def find_csgo_install() -> Optional[Path]:
    for root in _candidate_steam_roots():
        for lib in _read_library_folders(root):
            candidate = lib / "steamapps" / "common" / CSGO_FOLDER_NAME
            if candidate.exists():
                return candidate
    return None


def find_steamcmd() -> Optional[Path]:
    # 1. PATH
    import shutil

    plat = (
        "win32"
        if sys.platform.startswith("win")
        else ("darwin" if sys.platform == "darwin" else "linux")
    )
    name = _STEAMCMD_FILENAMES[plat]
    on_path = shutil.which(name)
    if on_path:
        return Path(on_path)
    # 2. typical user installs
    home = Path.home()
    candidates: List[Path] = [
        home / "steamcmd" / name,
        home / ".steam/steamcmd" / name,
        Path("/usr/games") / name,
    ]
    for c in candidates:
        if c.exists():
            return c
    return None
