# lightweight bsp checks before decompile.

from __future__ import annotations

import io
import struct
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List

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
def _read_lump_header(data: bytes, lump_id: int) -> tuple[int, int] | None:
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


# turn a BspInfo into vmf-style Findings so the analyze command can surface
# bsp-side pitfalls in the same flow. imported lazily to avoid a circular
# import (vmf.py imports nothing from bsp; we mirror that direction here).
def analyze_bsp_findings(info: BspInfo) -> List[object]:
    from .vmf import Finding  # local import keeps vmf.py the canonical Finding home

    findings: List[Finding] = []

    if not info.valid_header:
        findings.append(
            Finding(
                issue_id="bsp_invalid_header",
                severity="error",
                message=f"`{info.path.name}` does not start with VBSP magic; not a Source 1 bsp.",
                fixable=False,
                context={"path": str(info.path)},
            )
        )
        return findings

    if info.suspected_protected:
        findings.append(
            Finding(
                issue_id="bsp_protected",
                severity="error",
                message=(
                    f"`{info.path.name}` shows a `{info.detected_marker}` marker; "
                    "decompile may fail or produce broken geometry."
                ),
                fixable=False,
                context={"marker": info.detected_marker},
            )
        )

    if info.pakfile_error:
        findings.append(
            Finding(
                issue_id="pakfile_error",
                severity="warn",
                message=f"Could not read embedded pakfile: {info.pakfile_error}",
                fixable=False,
                context={"error": info.pakfile_error},
            )
        )
        return findings

    names = [e.name for e in info.pakfile_entries]
    lower = [n.lower() for n in names]

    # nav meshes don't carry over to cs2 (different format); flag if embedded.
    nav = [n for n in names if n.lower().endswith(".nav")]
    if nav:
        findings.append(
            Finding(
                issue_id="manual_rebuild_nav",
                severity="info",
                message=(
                    f"{len(nav)} nav file(s) embedded; cs2 uses a different nav format. "
                    "Regenerate with `nav_generate` after import."
                ),
                fixable=False,
                context={"files": nav[:5], "count": len(nav)},
            )
        )

    # radar overviews are in a new format in cs2 (vmat + dds replaced by .png/.vmat).
    radar = [n for n in names if "overviews/" in n.lower() and ("radar" in n.lower())]
    if radar:
        findings.append(
            Finding(
                issue_id="manual_rebuild_radar",
                severity="info",
                message=(
                    f"{len(radar)} radar overview asset(s) embedded; the cs2 radar "
                    "pipeline uses a different format and the editor `Generate Radar` step."
                ),
                fixable=False,
                context={"files": radar[:5], "count": len(radar)},
            )
        )

    # soundscape txt is csgo-only; cs2 uses .vsndevts.
    soundscape = [n for n in names if "soundscape" in n.lower() and n.lower().endswith(".txt")]
    if soundscape:
        findings.append(
            Finding(
                issue_id="manual_review_soundscapes",
                severity="info",
                message=(
                    f"{len(soundscape)} embedded soundscape txt file(s); cs2 expects "
                    "`scripts/soundevents/*.vsndevts` instead. Re-author after import."
                ),
                fixable=False,
                context={"files": soundscape[:5], "count": len(soundscape)},
            )
        )

    # lua / squirrel script blobs won't run in cs2 (vscript surface differs).
    scripts = [n for n in names if n.lower().endswith((".lua", ".nut"))]
    if scripts:
        findings.append(
            Finding(
                issue_id="pakfile_scripts",
                severity="warn",
                message=(
                    f"{len(scripts)} embedded script file(s) (lua/nut). cs2 vscript "
                    "is incompatible; behavior won't carry over."
                ),
                fixable=False,
                context={"files": scripts[:5], "count": len(scripts)},
            )
        )

    # files under a literal `csgo/` subfolder bite the importer (per upstream
    # pitfall #9). pakfile entries with that prefix are a strong signal.
    csgo_pathed = [n for n in names if n.lower().startswith("materials/csgo/")]
    if csgo_pathed:
        findings.append(
            Finding(
                issue_id="pakfile_csgo_subfolder",
                severity="warn",
                message=(
                    f"{len(csgo_pathed)} embedded asset(s) live under `materials/csgo/`; "
                    "the cs2 importer special-cases that folder name."
                ),
                fixable=False,
                context={"files": csgo_pathed[:5], "count": len(csgo_pathed)},
            )
        )

    # cubemaps embedded in the pakfile (.hdr.vtf etc) need a rebuild in cs2.
    cubemaps = [n for n in lower if "/cubemap" in n or n.startswith("cubemap")]
    if cubemaps:
        findings.append(
            Finding(
                issue_id="manual_rebuild_cubemaps",
                severity="info",
                message=(
                    f"{len(cubemaps)} embedded cubemap asset(s); run `buildcubemaps` "
                    "in cs2 after import. Source 2 envmaps are not compatible."
                ),
                fixable=False,
                context={"count": len(cubemaps)},
            )
        )

    return findings
