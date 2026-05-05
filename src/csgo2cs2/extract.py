# extract packed assets from a bsp.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import Config
from .logging_utils import info, success, warn
from .tools.bspzip import BSPZip
from .tools.vpkedit import VPKEdit
from .utils.paths import ensure_dir


@dataclass
class ExtractResult:
    tool_used: Optional[str]
    output_dir: Path
    succeeded: bool
    detail: str = ""


# extract assets with vpkedit first, then bspzip.
def extract_bsp_assets(cfg: Config, bsp_path: Path, output_dir: Path) -> ExtractResult:
    ensure_dir(output_dir)

    vpkedit = VPKEdit(cfg.vpkedit_path)
    if vpkedit.resolve():
        info(f"Extracting via vpkedit -> {output_dir}")
        result = vpkedit.extract(bsp_path, output_dir)
        if result.returncode == 0:
            success(f"vpkedit extracted assets to {output_dir}")
            return ExtractResult(
                tool_used="vpkedit", output_dir=output_dir, succeeded=True
            )
        warn(f"vpkedit exit code {result.returncode}; trying bspzip fallback")

    bspzip = BSPZip(cfg.bspzip_path)
    if bspzip.resolve():
        info(f"Extracting via bspzip -> {output_dir}")
        result = bspzip.extract(bsp_path, output_dir)
        if result.returncode == 0:
            success(f"bspzip extracted assets to {output_dir}")
            return ExtractResult(
                tool_used="bspzip", output_dir=output_dir, succeeded=True
            )
        warn(f"bspzip exit code {result.returncode}")

    return ExtractResult(
        tool_used=None,
        output_dir=output_dir,
        succeeded=False,
        detail="no extraction tool available; map may rely on base CS:GO assets only",
    )
