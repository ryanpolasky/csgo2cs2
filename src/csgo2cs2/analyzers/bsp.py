# lightweight bsp checks before decompile.

from __future__ import annotations

import io
import struct
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# bspprotect-style tools can break decompilers.
# marker checks catch obvious failures early.
PROTECTION_MARKERS = (
    b"BSPProtect",
    b"bspProtect",
    b"VMEX_Protect",
    b"IIDProtect",
)

# bsp lump layout (vbsp v19-21): 8-byte file header, then 64 lump headers,
# each 16 bytes: i32 fileofs, i32 filelen, i32 version, 4-byte fourCC.
_LUMP_HEADER_SIZE = 16
_LUMP_HEADER_OFFSET = 8
LUMP_PAKFILE = 40

# extensions that are interesting for an embedded-asset audit.
_INTERESTING_EXTENSIONS = (
    ".vmt",
    ".vtf",
    ".mdl",
    ".vvd",
    ".vtx",
    ".phy",
    ".wav",
    ".mp3",
    ".raw",
    ".nut",  # squirrel scripts
    ".lua",
    ".cfg",
)


@dataclass
class PakEntry:
    name: str
    size: int
    compressed_size: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class BspInfo:
    path: Path
    valid_header: bool
    version: int
    suspected_protected: bool
    detected_marker: str = ""
    pakfile_size: int = 0
    pakfile_count: int = 0
    pakfile_entries: List[PakEntry] = field(default_factory=list)
    pakfile_error: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": str(self.path),
            "valid_header": self.valid_header,
            "version": self.version,
            "suspected_protected": self.suspected_protected,
            "detected_marker": self.detected_marker,
            "pakfile_size": self.pakfile_size,
            "pakfile_count": self.pakfile_count,
            "pakfile_error": self.pakfile_error,
            "pakfile_entries": [e.to_dict() for e in self.pakfile_entries],
        }


# read a single lump header (offset, length) from a bsp byte buffer.
def _read_lump_header(data: bytes, lump_id: int) -> Optional[tuple[int, int]]:
    base = _LUMP_HEADER_OFFSET + lump_id * _LUMP_HEADER_SIZE
    if len(data) < base + _LUMP_HEADER_SIZE:
        return None
    fileofs, filelen = struct.unpack_from("<ii", data, base)
    if fileofs <= 0 or filelen <= 0:
        return None
    return fileofs, filelen


# read every file name in a bsp pakfile lump. read_limit caps how many entries
# we keep in memory to avoid pathological cases on enormous embedded zips.
def _read_pakfile(path: Path, read_limit: int = 5000) -> tuple[List[PakEntry], int, str]:
    with path.open("rb") as fh:
        header = fh.read(_LUMP_HEADER_OFFSET + 64 * _LUMP_HEADER_SIZE)
        lump = _read_lump_header(header, LUMP_PAKFILE)
        if lump is None:
            return [], 0, "no pakfile lump"
        offset, length = lump
        fh.seek(offset)
        blob = fh.read(length)
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        return [], length, f"pakfile not a valid zip: {exc}"
    entries: List[PakEntry] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        entries.append(
            PakEntry(
                name=info.filename,
                size=info.file_size,
                compressed_size=info.compress_size,
            )
        )
        if len(entries) >= read_limit:
            break
    return entries, length, ""


# read the header, scan for protection markers, and inventory the pakfile.
def inspect_bsp(path: Path, scan_bytes: int = 1_000_000) -> BspInfo:
    data = path.read_bytes()[:scan_bytes]
    valid_header = len(data) >= 8 and data[:4] == b"VBSP"
    version = struct.unpack_from("<i", data, 4)[0] if len(data) >= 8 else 0

    detected = ""
    for marker in PROTECTION_MARKERS:
        if marker in data:
            detected = marker.decode("ascii", errors="ignore")
            break

    info = BspInfo(
        path=path,
        valid_header=valid_header,
        version=version,
        suspected_protected=bool(detected),
        detected_marker=detected,
    )

    if valid_header:
        try:
            entries, pakfile_size, err = _read_pakfile(path)
        except OSError as exc:
            entries, pakfile_size, err = [], 0, f"read failed: {exc}"
        info.pakfile_entries = entries
        info.pakfile_count = len(entries)
        info.pakfile_size = pakfile_size
        info.pakfile_error = err

    return info


# return only the entries with extensions we care about for porting audits.
def filter_interesting(entries: List[PakEntry]) -> List[PakEntry]:
    return [
        e for e in entries if any(e.name.lower().endswith(ext) for ext in _INTERESTING_EXTENSIONS)
    ]
