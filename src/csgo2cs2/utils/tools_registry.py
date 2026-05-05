# registry of pinned external-tool downloads. version-pinned for stability;
# pass --version to override at install time.
#
# resources we know how to fetch:
#   - bspsource (ata4/bspsrc): per-platform standalone with bundled jre
#   - steamcmd (valve cdn): per-platform installer
#   - import_map_community (andreaskeller96/cs2-import-scripts): py3 fork
#     of valve's official csgo->cs2 importer

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ToolDownload:
    # url to fetch
    url: str
    # filename to write the download as
    filename: str
    # treat the download as an archive to extract (zip or tar.gz/tgz)
    extract: bool = False
    # the entry inside the extracted tree to point a tool path at
    # (relative to the extraction root). None for stand-alone files.
    binary_subpath: Optional[str] = None


# return the platform key used in the registry below.
def current_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


# pinned versions. bump these to upgrade the default install.
PINNED_VERSIONS: Dict[str, str] = {
    "bspsource": "1.4.8",
    "steamcmd": "latest",
    "import_map_community": "main",
}


def bspsource_download(version: str = "") -> Dict[str, ToolDownload]:
    v = version or PINNED_VERSIONS["bspsource"]
    base = f"https://github.com/ata4/bspsrc/releases/download/v{v}"
    return {
        "windows": ToolDownload(
            url=f"{base}/bspsrc-windows.zip",
            filename=f"bspsrc-windows-{v}.zip",
            extract=True,
            binary_subpath="bspsrc.bat",
        ),
        "linux": ToolDownload(
            url=f"{base}/bspsrc-linux.zip",
            filename=f"bspsrc-linux-{v}.zip",
            extract=True,
            binary_subpath="bspsrc.sh",
        ),
        "macos": ToolDownload(
            # no native macos build; fall back to jar-only (needs java)
            url=f"{base}/bspsrc-jar-only.zip",
            filename=f"bspsrc-jar-only-{v}.zip",
            extract=True,
            binary_subpath="bspsrc.jar",
        ),
    }


def steamcmd_download() -> Dict[str, ToolDownload]:
    return {
        "windows": ToolDownload(
            url="https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip",
            filename="steamcmd-win.zip",
            extract=True,
            binary_subpath="steamcmd.exe",
        ),
        "linux": ToolDownload(
            url="https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz",
            filename="steamcmd-linux.tar.gz",
            extract=True,
            binary_subpath="steamcmd.sh",
        ),
        "macos": ToolDownload(
            url="https://steamcdn-a.akamaihd.net/client/installer/steamcmd_osx.tar.gz",
            filename="steamcmd-osx.tar.gz",
            extract=True,
            binary_subpath="steamcmd.sh",
        ),
    }


def import_map_community_download(ref: str = "") -> ToolDownload:
    r = ref or PINNED_VERSIONS["import_map_community"]
    return ToolDownload(
        url=f"https://raw.githubusercontent.com/andreaskeller96/cs2-import-scripts/{r}/import_map_community.py",
        filename="import_map_community.py",
        extract=False,
    )


def import_map_community_repo_archive(ref: str = "") -> ToolDownload:
    # fetched alongside the script for the `utils/utlc.py` dependency.
    r = ref or PINNED_VERSIONS["import_map_community"]
    return ToolDownload(
        url=f"https://github.com/andreaskeller96/cs2-import-scripts/archive/refs/heads/{r}.zip",
        filename=f"cs2-import-scripts-{r}.zip",
        extract=True,
        binary_subpath="import_map_community.py",
    )
