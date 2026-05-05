# vpkedit adapter for packed bsp content.

from __future__ import annotations

import subprocess
from pathlib import Path

from .base import ToolAdapter


class VPKEdit(ToolAdapter):
    name = "vpkedit"

    # extract embedded pakfile content from a bsp.
    def extract(self, bsp_path: Path, output_dir: Path) -> subprocess.CompletedProcess:
        output_dir.mkdir(parents=True, exist_ok=True)
        return self.run(
            [str(bsp_path), "--output", str(output_dir), "--extract"],
            check=False,
        )
