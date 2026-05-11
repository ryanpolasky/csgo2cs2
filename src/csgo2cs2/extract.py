# extract packed assets from a bsp.
#
# strategy: try vpkedit, then bspzip, then a built-in pure-python
# extractor that reads the BSP's pakfile lump directly. the python
# fallback handles the common case (PKZIP-format pakfile in a CSGO
# v21 BSP) without needing any external binary -- which used to leave
# users with a `[warn] no extraction tool available` and a map full
# of pink-and-black missing-material checkerboards.

from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from .config import Config
from .logging_utils import info, success, warn
from .tools.bspzip import BSPZip
from .tools.vpkedit import VPKEdit
from .utils.paths import ensure_dir

# VBSP header. lumps[40] is the pakfile lump (a standard PKZIP archive)
# for all VBSP versions we care about (v19 CSGO/CS:S, v20 Portal2, v21
# CSGO/Black Mesa). The pakfile contains the map's embedded materials,
# models, soundscapes, etc.
_BSP_PAKFILE_LUMP = 40
_BSP_NUM_LUMPS = 64
_BSP_LUMP_ENTRY_SIZE = 16  # fileofs(i32) filelen(i32) version(i32) fourcc(4b)


@dataclass
class ExtractResult:
    tool_used: str | None
    output_dir: Path
    succeeded: bool
    detail: str = ""


# read the (fileofs, filelen) of the pakfile lump from a VBSP header.
# returns (0, 0) if the bsp isn't recognized or the lump is empty.
def _read_pakfile_lump_offset(bsp_path: Path) -> tuple[int, int]:
    try:
        with bsp_path.open("rb") as f:
            magic = f.read(4)
            if magic != b"VBSP":
                return 0, 0
            # skip version (int32)
            f.read(4)
            # lumps start at offset 8. seek to pakfile lump.
            f.seek(8 + _BSP_PAKFILE_LUMP * _BSP_LUMP_ENTRY_SIZE)
            entry = f.read(_BSP_LUMP_ENTRY_SIZE)
            if len(entry) < _BSP_LUMP_ENTRY_SIZE:
                return 0, 0
            fileofs, filelen, _ver, _fourcc = struct.unpack("<iii4s", entry)
            if fileofs <= 0 or filelen <= 0:
                return 0, 0
            return int(fileofs), int(filelen)
    except OSError:
        return 0, 0


# read the pakfile lump as bytes; returns b'' if the lump is empty,
# missing, or unreadable.
def _read_pakfile_bytes(bsp_path: Path) -> bytes:
    fileofs, filelen = _read_pakfile_lump_offset(bsp_path)
    if filelen <= 0:
        return b""
    try:
        with bsp_path.open("rb") as f:
            f.seek(fileofs)
            return f.read(filelen)
    except OSError:
        return b""


# extract the BSP's pakfile lump (PKZIP-formatted) using stdlib zipfile.
# returns (succeeded, file_count). soft-fails on any I/O or zip error
# instead of raising -- callers fall through to the next strategy.
def extract_pakfile_lump_python(bsp_path: Path, output_dir: Path) -> tuple[bool, int]:
    raw = _read_pakfile_bytes(bsp_path)
    if not raw:
        return False, 0
    try:
        with zipfile.ZipFile(BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if not names:
                return False, 0
            output_dir.mkdir(parents=True, exist_ok=True)
            zf.extractall(output_dir)
            return True, len(names)
    except (zipfile.BadZipFile, OSError):
        return False, 0


# extract assets with vpkedit, then bspzip, then the built-in
# python pakfile extractor. the python fallback covers ~all CSGO
# workshop maps even when neither external tool is configured.
def extract_bsp_assets(cfg: Config, bsp_path: Path, output_dir: Path) -> ExtractResult:
    ensure_dir(output_dir)

    vpkedit = VPKEdit(cfg.vpkedit_path)
    if vpkedit.resolve():
        info(f"Extracting via vpkedit -> {output_dir}")
        result = vpkedit.extract(bsp_path, output_dir)
        if result.returncode == 0:
            success(f"vpkedit extracted assets to {output_dir}")
            return ExtractResult(tool_used="vpkedit", output_dir=output_dir, succeeded=True)
        warn(f"vpkedit exit code {result.returncode}; trying bspzip fallback")

    bspzip = BSPZip(cfg.bspzip_path)
    if bspzip.resolve():
        info(f"Extracting via bspzip -> {output_dir}")
        result = bspzip.extract(bsp_path, output_dir)
        if result.returncode == 0:
            success(f"bspzip extracted assets to {output_dir}")
            return ExtractResult(tool_used="bspzip", output_dir=output_dir, succeeded=True)
        warn(f"bspzip exit code {result.returncode}; trying built-in pakfile extractor")

    info(f"Extracting via built-in pakfile reader -> {output_dir}")
    ok, count = extract_pakfile_lump_python(bsp_path, output_dir)
    if ok:
        success(f"built-in extractor wrote {count} files to {output_dir}")
        return ExtractResult(
            tool_used="builtin_pakfile",
            output_dir=output_dir,
            succeeded=True,
            detail=f"{count} files",
        )

    return ExtractResult(
        tool_used=None,
        output_dir=output_dir,
        succeeded=False,
        detail=(
            "BSP has no embedded pakfile or it could not be read; map may "
            "rely on base CS:GO assets only"
        ),
    )

