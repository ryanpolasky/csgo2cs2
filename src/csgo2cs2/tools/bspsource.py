# bspsource adapter.

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .base import ToolAdapter, ToolNotFoundError


class BSPSource(ToolAdapter):
    name = "bspsource"

    def __init__(
        self,
        executable: Optional[str] = None,
        java_path: Optional[str] = None,
    ) -> None:
        super().__init__(executable)
        self.java_path = java_path

    def _resolve_java(self) -> Optional[str]:
        if self.java_path and Path(self.java_path).exists():
            return self.java_path
        return shutil.which(self.java_path or "java")

    def status_detail(self) -> str:
        resolved = self.resolve()
        if not resolved:
            return "not configured"
        if resolved.endswith(".jar"):
            java = self._resolve_java()
            return "ready (jar)" if java else "jar found but Java not on PATH"
        return "ready (wrapper script)"

    # decompile a bsp into a vmf.
    def decompile(self, bsp_path: Path, output_dir: Path) -> subprocess.CompletedProcess:
        resolved = self.resolve()
        if not resolved:
            raise ToolNotFoundError("BSPSource is not configured. Set `bspsource_path` in config.")
        output_dir.mkdir(parents=True, exist_ok=True)

        # bspsource's `-o` is treated as the *output file path* when only
        # one BSP is provided (per `bspsrc --help`). Passing a directory
        # silently produces no output. Compose the target VMF explicitly
        # so the result lands at a predictable path on every platform.
        out_vmf = output_dir / f"{bsp_path.stem}.vmf"
        bsp_str = str(bsp_path)
        out_str = str(out_vmf)

        if resolved.endswith(".jar"):
            java = self._resolve_java()
            if not java:
                raise ToolNotFoundError("Java is required to run BSPSource jar but was not found.")
            cmd = [java, "-jar", resolved, "-o", out_str, bsp_str]
        else:
            # wrapper script form, usually bspsrc.bat or bspsrc.sh
            cmd = [resolved, "-o", out_str, bsp_str]

        return subprocess.run(cmd, check=False, capture_output=True, text=True)
