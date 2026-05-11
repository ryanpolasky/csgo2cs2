# Always-on per-run log capture.
#
# Every csgo2cs2 invocation tees its stdout/stderr (and explicit
# subprocess output) to `<workspace>/logs/<run-id>.log` so that when
# something breaks the user has a single file to share. Older logs
# are pruned to keep the directory size bounded.

from __future__ import annotations

import datetime as _dt
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional, TextIO

# ANSI escape stripper for what we write to the log file. We want
# colored terminal output but plain-text logs so they paste cleanly
# into github issues / chat.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


class _TeeStream:
    """Forward writes to a primary stream and a log file.

    Strips ANSI from the log copy but passes the original through to
    the terminal stream unchanged.
    """

    def __init__(self, primary: TextIO, log_fh: TextIO) -> None:
        self._primary = primary
        self._log = log_fh
        self._lock = threading.Lock()

    def write(self, data: str) -> int:
        with self._lock:
            self._primary.write(data)
            try:
                self._log.write(_strip_ansi(data))
            except Exception:  # noqa: BLE001
                # never let a log-write failure break stdout/stderr.
                pass
        return len(data)

    def flush(self) -> None:
        with self._lock:
            try:
                self._primary.flush()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._log.flush()
            except Exception:  # noqa: BLE001
                pass

    # passthrough helpers a few callers (colorama, pytest capture) rely on
    def isatty(self) -> bool:
        return getattr(self._primary, "isatty", lambda: False)()

    def fileno(self) -> int:
        return self._primary.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._primary, "encoding", "utf-8")


class RunLog:
    """Live run log handle. Opened in `start_logging()`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: Optional[TextIO] = None
        self._orig_stdout: Optional[TextIO] = None
        self._orig_stderr: Optional[TextIO] = None

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # line-buffered so partial output is still on disk when tailing.
        self._fh = self.path.open("w", encoding="utf-8", buffering=1)
        header = [
            "# csgo2cs2 run log",
            f"# started: {_dt.datetime.now().isoformat(timespec='seconds')}",
            f"# argv: {sys.argv}",
            f"# platform: {sys.platform}",
            f"# python: {sys.version.split()[0]}",
            "",
        ]
        self._fh.write("\n".join(header) + "\n")
        self._fh.flush()

    def _install_tees(self) -> None:
        assert self._fh is not None
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = _TeeStream(self._orig_stdout, self._fh)
        sys.stderr = _TeeStream(self._orig_stderr, self._fh)

    def _restore_tees(self) -> None:
        if self._orig_stdout is not None:
            sys.stdout = self._orig_stdout
        if self._orig_stderr is not None:
            sys.stderr = self._orig_stderr
        self._orig_stdout = None
        self._orig_stderr = None

    def close(self) -> None:
        self._restore_tees()
        if self._fh is not None:
            try:
                self._fh.flush()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass
            self._fh = None
        _CURRENT.set(None)

    # explicit subprocess log entry. captured stdout/stderr from a tool
    # never flows through sys.stdout, so the tool adapter has to feed
    # it to the log directly.
    def record_subprocess(
        self,
        tool: str,
        argv: List[str],
        returncode: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        if self._fh is None:
            return
        lines = [
            "",
            f"--- subprocess: {tool} (returncode={returncode}) ---",
            f"argv: {argv}",
        ]
        if stdout:
            lines.append("stdout:")
            lines.append(stdout.rstrip())
        if stderr:
            lines.append("stderr:")
            lines.append(stderr.rstrip())
        lines.append("--- end subprocess ---")
        lines.append("")
        try:
            self._fh.write("\n".join(lines) + "\n")
            self._fh.flush()
        except Exception:  # noqa: BLE001
            pass


# Module-level handle for the active run log so subprocess wrappers
# can fetch it without an explicit threading. Set in `start_logging()`.
class _Current:
    def __init__(self) -> None:
        self._log: Optional[RunLog] = None

    def set(self, log: Optional[RunLog]) -> None:
        self._log = log

    def get(self) -> Optional[RunLog]:
        return self._log


_CURRENT = _Current()


def current() -> Optional[RunLog]:
    return _CURRENT.get()


def _run_id(command: str) -> str:
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    pid = os.getpid()
    safe_cmd = re.sub(r"[^a-zA-Z0-9_-]+", "_", command or "csgo2cs2") or "csgo2cs2"
    return f"{stamp}-{safe_cmd}-{pid}"


def _logs_dir(workspace_dir: Path) -> Path:
    return Path(workspace_dir).expanduser() / "logs"


def prune_old(workspace_dir: Path, keep: int = 25) -> int:
    """Delete the oldest logs over `keep`. Returns the number deleted."""
    d = _logs_dir(workspace_dir)
    if not d.is_dir():
        return 0
    entries = [p for p in d.iterdir() if p.is_file() and p.suffix == ".log"]
    if len(entries) <= keep:
        return 0
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    deleted = 0
    for p in entries[keep:]:
        try:
            p.unlink()
            deleted += 1
        except OSError:
            pass
    return deleted


def is_disabled() -> bool:
    return bool(os.environ.get("CSGO2CS2_NO_LOG"))


@contextmanager
def start_logging(
    workspace_dir: Path, command: str, *, keep: int = 25
) -> Iterator[Optional[RunLog]]:
    """Open the run log, tee stdout/stderr to it, and yield the handle.

    No-ops (yields None) when:
      - CSGO2CS2_NO_LOG is set in the environment
      - workspace_dir cannot be written to (e.g. read-only fs in tests)
    """
    if is_disabled():
        yield None
        return

    path = _logs_dir(workspace_dir) / f"{_run_id(command)}.log"
    log = RunLog(path)
    try:
        log._open()
    except OSError:
        # log dir not writable; degrade silently rather than failing the run.
        yield None
        return

    log._install_tees()
    _CURRENT.set(log)
    try:
        yield log
    finally:
        log.close()
        try:
            prune_old(workspace_dir, keep=keep)
        except OSError:
            pass


# Convenience: write an arbitrary entry to the active log, if any.
def log_event(message: str) -> None:
    log = current()
    if log is None or log._fh is None:
        return
    try:
        ts = _dt.datetime.now().isoformat(timespec="seconds")
        log._fh.write(f"[{ts}] {message}\n")
        log._fh.flush()
    except Exception:  # noqa: BLE001
        pass
