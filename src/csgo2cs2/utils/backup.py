# reversible install-file changes.

from __future__ import annotations

import shutil
from pathlib import Path

BACKUP_SUFFIX = ".csgo2cs2.bak"


def backup_path_for(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


# create a backup if one does not already exist.
def backup_file(path: Path) -> Path:
    backup = backup_path_for(path)
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


# restore from a backup if one exists.
def restore_file(path: Path) -> bool:
    backup = backup_path_for(path)
    if backup.exists():
        shutil.copy2(backup, path)
        return True
    return False


def has_marker(path: Path, marker: str) -> bool:
    if not path.exists():
        return False
    return marker in path.read_text(encoding="utf-8", errors="ignore")
