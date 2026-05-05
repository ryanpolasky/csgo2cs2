# minimal http downloader with optional sha-256 verification.
# uses stdlib only to keep the install footprint tiny.

from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional


class DownloadError(RuntimeError):
    pass


def _progress_default(name: str, downloaded: int, total: int) -> None:
    if not sys.stderr.isatty():
        return
    if total <= 0:
        sys.stderr.write(f"\r{name}: {downloaded // 1024} KiB")
    else:
        pct = downloaded / total
        bar = "#" * int(pct * 30)
        sys.stderr.write(f"\r{name}: [{bar:<30}] {pct * 100:5.1f}%")
    sys.stderr.flush()


def fetch(
    url: str,
    dest: Path,
    sha256: Optional[str] = None,
    name: Optional[str] = None,
    progress: Optional[Callable[[str, int, int], None]] = _progress_default,
    timeout: float = 60.0,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    label = name or dest.name
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", "0") or 0)
            hasher = hashlib.sha256()
            downloaded = 0
            with tmp.open("wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(label, downloaded, total)
            if progress and sys.stderr.isatty():
                sys.stderr.write("\n")
        if sha256:
            digest = hasher.hexdigest().lower()
            if digest != sha256.lower():
                tmp.unlink(missing_ok=True)
                raise DownloadError(f"{label}: sha256 mismatch (expected {sha256}, got {digest})")
        shutil.move(str(tmp), str(dest))
        return dest
    except urllib.error.URLError as exc:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"{label}: download failed: {exc}") from exc
