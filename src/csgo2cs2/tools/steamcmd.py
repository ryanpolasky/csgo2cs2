# steamcmd adapter.

from __future__ import annotations

import subprocess
import time
import zipfile
from pathlib import Path
from typing import List

from .base import ToolAdapter

CSGO_APP_ID = "730"


class SteamCMD(ToolAdapter):
    name = "steamcmd"

    # return the folder containing the steamcmd executable.
    def steamcmd_root(self) -> Path | None:
        resolved = self.resolve()
        if not resolved:
            return None
        return Path(resolved).parent

    def expected_workshop_path(self, workshop_id: str, app_id: str = CSGO_APP_ID) -> Path | None:
        root = self.steamcmd_root()
        if not root:
            return None
        return root / "steamapps" / "workshop" / "content" / app_id / workshop_id

    # run steamcmd to download one workshop item, retrying on transient
    # failures. anonymous workshop_download_item is famously flaky.
    def download_workshop_item(
        self,
        workshop_id: str,
        app_id: str = CSGO_APP_ID,
        login: str | None = None,
        retries: int = 3,
        backoff_seconds: float = 5.0,
    ) -> subprocess.CompletedProcess:
        login_arg = login or "anonymous"
        args = [
            "+login",
            login_arg,
            "+workshop_download_item",
            app_id,
            workshop_id,
            "+quit",
        ]
        attempts = max(1, retries)
        last: subprocess.CompletedProcess | None = None
        expected = self.expected_workshop_path(workshop_id, app_id)
        for i in range(attempts):
            last = self.run(args, check=False)
            # success heuristic: the expected workshop path now contains either
            # a .bsp (s2-era / steam logged-in) or a *_legacy.bin wrapper
            # (anonymous downloads on most platforms wrap the BSP in a zip).
            if expected and expected.exists() and any(_workshop_payloads(expected)):
                return last
            if i < attempts - 1:
                time.sleep(backoff_seconds * (i + 1))
        assert last is not None
        return last


def _workshop_payloads(dir_: Path) -> List[Path]:
    """Anything in `dir_` that could plausibly be a downloaded workshop
    BSP, raw or wrapped."""
    return sorted(dir_.glob("*.bsp")) + sorted(dir_.glob("*_legacy.bin"))


def candidate_workshop_dirs(steam: SteamCMD, workshop_id: str) -> List[Path]:
    """Where SteamCMD might have dropped the workshop item, in order of
    likelihood. SteamCMD's Linux build defaults to ~/Steam/ for data
    storage even when its binary lives elsewhere; the Windows build
    keeps everything under its install dir. We probe both."""
    candidates: List[Path] = []
    expected = steam.expected_workshop_path(workshop_id)
    if expected:
        candidates.append(expected)
    candidates.append(
        Path.home() / "Steam" / "steamapps" / "workshop" / "content" / CSGO_APP_ID / workshop_id
    )
    seen: set = set()
    out: List[Path] = []
    for c in candidates:
        s = str(c.resolve()) if c.exists() else str(c)
        if s in seen:
            continue
        seen.add(s)
        out.append(c)
    return out


def unwrap_legacy_bin(legacy_bin: Path, extract_dir: Path) -> Path:
    """SteamCMD's anonymous CS:GO workshop downloads come down as a
    `<numeric_id>_legacy.bin` -- usually a ZIP container holding the
    actual `.bsp`, occasionally a renamed raw BSP. Unwrap so callers
    get a real `.bsp` path to hand to BSPSource."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    if not zipfile.is_zipfile(legacy_bin):
        head = legacy_bin.read_bytes()[:4]
        if head == b"VBSP":
            target = extract_dir / (legacy_bin.stem + ".bsp")
            target.write_bytes(legacy_bin.read_bytes())
            return target
        raise RuntimeError(f"{legacy_bin} is neither a zip nor a raw BSP (magic={head!r})")
    with zipfile.ZipFile(legacy_bin) as zf:
        zf.extractall(extract_dir)
    bsps = sorted(extract_dir.rglob("*.bsp"))
    if not bsps:
        with zipfile.ZipFile(legacy_bin) as zf:
            names = zf.namelist()[:8]
        raise RuntimeError(f"{legacy_bin} unwrapped but contained no .bsp (sample: {names})")
    return max(bsps, key=lambda p: p.stat().st_size)


def resolve_downloaded_bsp(
    steam: SteamCMD,
    workshop_id: str,
    scratch_root: Path,
) -> Path | None:
    """Find the .bsp SteamCMD dropped on disk, unwrapping the legacy
    ZIP wrapper if needed. Returns None when no plausible payload is
    present at any candidate path."""
    for d in candidate_workshop_dirs(steam, workshop_id):
        if not d.exists():
            continue
        bsps = sorted(d.glob("*.bsp"))
        if bsps:
            return max(bsps, key=lambda p: p.stat().st_size)
        legacy_bins = sorted(d.glob("*_legacy.bin")) + sorted(d.glob("*.bin"))
        if legacy_bins:
            target_dir = scratch_root / "unwrap" / workshop_id
            return unwrap_legacy_bin(
                max(legacy_bins, key=lambda p: p.stat().st_size),
                target_dir,
            )
    return None
