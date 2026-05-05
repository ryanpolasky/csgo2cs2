# wrapper around valve's cs2 map importer.

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Sequence

from ..platform_check import require_windows


class ImportMapTool:
    name = "import_map_community"

    def __init__(
        self,
        importer_path: Optional[str] = None,
        python_executable: str = "python",
    ) -> None:
        self.importer_path = importer_path
        self.python_executable = python_executable

    def resolve(self) -> Optional[Path]:
        if not self.importer_path:
            return None
        p = Path(self.importer_path)
        return p if p.exists() else None

    def import_vmf(
        self,
        vmf_path: Path,
        addon_name: str,
        extra_args: Optional[Sequence[str]] = None,
    ) -> subprocess.CompletedProcess:
        require_windows("import_map_community.py")
        importer = self.resolve()
        if not importer:
            raise RuntimeError(
                "import_map_community.py not configured. Set the path in config."
            )
        cmd = [
            self.python_executable,
            str(importer),
            str(vmf_path),
            addon_name,
        ]
        if extra_args:
            cmd.extend(extra_args)
        return subprocess.run(cmd, check=False, capture_output=True, text=True)
