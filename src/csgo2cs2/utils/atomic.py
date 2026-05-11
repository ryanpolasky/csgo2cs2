# Atomic file writes.
#
# Write-temp-then-rename so a power loss, Ctrl-C, or a crashed Python
# can't leave a half-written manifest / config / state file on disk.
# The temp file lives in the same directory as the target so the
# os.replace() at the end is a real atomic rename on every supported
# filesystem (cross-filesystem renames are not atomic).

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_bytes(path: Path, data: bytes, *, mode: int = 0o644) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync isn't supported on some filesystems (e.g. tmpfs).
                # the rename is still atomic; durability is best-effort.
                pass
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        os.replace(tmp, path)
        return path
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_text(path: Path, text: str, *, encoding: str = "utf-8", mode: int = 0o644) -> Path:
    return write_bytes(path, text.encode(encoding), mode=mode)


def write_json(
    path: Path,
    obj: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
    mode: int = 0o644,
) -> Path:
    text = json.dumps(obj, indent=indent, sort_keys=sort_keys)
    if not text.endswith("\n"):
        text += "\n"
    return write_text(path, text, mode=mode)
