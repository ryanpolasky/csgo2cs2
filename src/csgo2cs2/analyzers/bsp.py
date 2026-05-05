# lightweight bsp checks before decompile.

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

# bspprotect-style tools can break decompilers.
# marker checks catch obvious failures early.
PROTECTION_MARKERS = (
    b"BSPProtect",
    b"bspProtect",
    b"VMEX_Protect",
    b"IIDProtect",
)


@dataclass
class BspInfo:
    path: Path
    valid_header: bool
    version: int
    suspected_protected: bool
    detected_marker: str = ""


# read the header and scan for known protection markers.
def inspect_bsp(path: Path, scan_bytes: int = 1_000_000) -> BspInfo:
    data = path.read_bytes()[:scan_bytes]
    valid_header = len(data) >= 8 and data[:4] == b"VBSP"
    version = struct.unpack_from("<i", data, 4)[0] if len(data) >= 8 else 0

    detected = ""
    for marker in PROTECTION_MARKERS:
        if marker in data:
            detected = marker.decode("ascii", errors="ignore")
            break

    return BspInfo(
        path=path,
        valid_header=valid_header,
        version=version,
        suspected_protected=bool(detected),
        detected_marker=detected,
    )
