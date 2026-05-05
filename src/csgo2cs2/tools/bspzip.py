# bspzip adapter for packed bsp content.

from __future__ import annotations

import subprocess
from pathlib import Path

from .base import ToolAdapter


class BSPZip(ToolAdapter):
    name = "bspzip"

    def list_files(self, bsp_path: Path) -> subprocess.CompletedProcess:
        return self.run(["-extractfilelist", str(bsp_path)], check=False)

    # extract pakfile contents from a bsp.
    def extract(self, bsp_path: Path, output_dir: Path) -> subprocess.CompletedProcess:
        output_dir.mkdir(parents=True, exist_ok=True)
        return self.run(
            ["-extractall", str(bsp_path), str(output_dir)],
            check=False,
        )
