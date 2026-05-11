# path discovery and filesystem helpers.

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# return the first matching file under root.
def find_first(root: Path, patterns: Iterable[str]) -> Path | None:
    for pattern in patterns:
        for path in root.rglob(pattern):
            if path.is_file():
                return path
    return None


def find_all(root: Path, patterns: Iterable[str]) -> List[Path]:
    matches: List[Path] = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            if path.is_file():
                matches.append(path)
    return matches
