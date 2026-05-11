# base class for external cli tools.

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class ToolStatus:
    name: str
    installed: bool
    path: str | None
    detail: str = ""


class ToolNotFoundError(RuntimeError):
    pass


class ToolAdapter:
    name: str = "tool"

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable

    def resolve(self) -> str | None:
        if self.executable:
            p = Path(self.executable)
            if p.exists():
                return str(p)
            found = shutil.which(self.executable)
            if found:
                return found
        return shutil.which(self.name)

    def status(self) -> ToolStatus:
        resolved = self.resolve()
        return ToolStatus(name=self.name, installed=bool(resolved), path=resolved)

    def require(self) -> str:
        resolved = self.resolve()
        if not resolved:
            raise ToolNotFoundError(
                f"{self.name} is not installed or not on PATH "
                f"(configured: {self.executable!r})."
            )
        return resolved

    def run(
        self,
        args: Sequence[str],
        cwd: Path | None = None,
        check: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess:
        exe = self.require()
        cmd = [exe, *args]
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            check=check,
            capture_output=capture_output,
            text=True,
        )
