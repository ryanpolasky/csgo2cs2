# wrapper around valve's cs2 map importer.

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Callable, Sequence

from ..platform_check import require_windows


@dataclass
class ImportInputs:
    # path to a folder that contains gameinfo.txt for the s1 (csgo) install,
    # and any compiled .mdl/.vmt/.vtf the map references.
    s1_gameinfo_dir: Path
    # path to a folder containing source content. the importer expects the
    # map at <s1_content_dir>/maps/<mapname>.vmf and instances/prefabs in the
    # same maps/ subtree. paths must not contain spaces.
    s1_content_dir: Path
    # path to a folder containing gameinfo.gi for the s2 (cs2) install.
    s2_gameinfo_dir: Path
    # name of an existing cs2 workshop addon. content lands under
    # <s2_install>/game/csgo_addons/<s2_addon>/.
    s2_addon: str
    # map name without .vmf extension. may include a subdir relative to
    # <s1_content_dir>/maps/, e.g. "my_maps/de_examplemap".
    mapname: str


class ImportMapTool:
    name = "import_map_community"

    def __init__(
        self,
        importer_path: str | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.importer_path = importer_path
        # Default to the *same* Python that's running csgo2cs2. The previous
        # default ("python") leaned on $PATH resolution, which on Windows
        # routinely picked up the Store stub or a system 3.11 lacking our
        # deps -- the importer would crash on `import colorama` before it
        # could do anything useful.
        self.python_executable = python_executable or sys.executable

    def resolve(self) -> Path | None:
        if not self.importer_path:
            return None
        p = Path(self.importer_path)
        return p if p.exists() else None

    # build the importer command line without running it. exposed so the
    # `port --dry-run` path can show users exactly what would execute.
    def build_command(
        self,
        inputs: ImportInputs,
        use_bsp: bool = True,
        no_merge_instances: bool = False,
        skip_deps: bool = False,
        extra_args: Sequence[str] | None = None,
    ) -> list[str]:
        importer = self.resolve()
        if not importer:
            raise RuntimeError("import_map_community.py not configured. Set the path in config.")
        cmd = [
            self.python_executable,
            str(importer),
            str(inputs.s1_gameinfo_dir),
            str(inputs.s1_content_dir),
            str(inputs.s2_gameinfo_dir),
            inputs.s2_addon,
            inputs.mapname,
        ]
        if use_bsp and no_merge_instances:
            cmd.append("-usebsp_nomergeinstances")
        elif use_bsp:
            cmd.append("-usebsp")
        if skip_deps:
            cmd.append("-skipdeps")
        if extra_args:
            cmd.extend(extra_args)
        return cmd

    # invoke the importer with the canonical 5 positional args plus optional flags.
    # see https://github.com/andreaskeller96/cs2-import-scripts (essentially valve's
    # script with python 3 fixes).
    def import_map(
        self,
        inputs: ImportInputs,
        use_bsp: bool = True,
        no_merge_instances: bool = False,
        skip_deps: bool = False,
        extra_args: Sequence[str] | None = None,
        stream: bool = False,
        on_line: Callable[[str, str], None] | None = None,
        extra_path_dirs: Sequence[Path] | None = None,
        stdin_input: str | None = None,
    ) -> subprocess.CompletedProcess:
        """Invoke the importer. When `stream=True`, stdout/stderr are
        relayed to `on_line(stream_name, line)` as they arrive (default
        callback prints to sys.stdout). Otherwise output is buffered and
        returned only on completion.

        `extra_path_dirs` is prepended to the subprocess PATH. Use this
        to make sure resourcecompiler.exe (which Valve's script invokes
        unqualified) is on PATH even if the user hasn't added cs2_bin_path
        to their system PATH.

        `stdin_input` is fed to the importer's stdin and stdin is then
        closed. Valve's importer issues an `Enter to Continue, Esc to
        Quit` prompt on startup -- without piping a newline the process
        blocks forever waiting on a TTY that's never going to type back.
        """
        require_windows("import_map_community.py")
        cmd = self.build_command(
            inputs,
            use_bsp=use_bsp,
            no_merge_instances=no_merge_instances,
            skip_deps=skip_deps,
            extra_args=extra_args,
        )
        env = _env_with_extra_path(extra_path_dirs)
        if not stream:
            return subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                env=env,
                input=stdin_input,
            )
        return _run_streaming(
            cmd, on_line=on_line, env=env, stdin_input=stdin_input
        )


def _env_with_extra_path(
    extra_path_dirs: Sequence[Path] | None,
) -> dict[str, str] | None:
    if not extra_path_dirs:
        return None
    env = os.environ.copy()
    extra = os.pathsep.join(str(p) for p in extra_path_dirs if p)
    if not extra:
        return env
    env["PATH"] = extra + os.pathsep + env.get("PATH", "")
    return env


def _run_streaming(
    cmd: Sequence[str],
    on_line: Callable[[str, str], None] | None,
    env: dict[str, str] | None = None,
    stdin_input: str | None = None,
) -> subprocess.CompletedProcess:
    """Spawn a subprocess and relay each line of stdout/stderr to
    `on_line(stream, line)` as it arrives, while also capturing the
    full output into the returned CompletedProcess. This is what makes
    a long-running importer feel like it's actually doing something
    -- without it the user stares at a blank line for 3 minutes."""
    if on_line is None:
        def _default_on_line(stream: str, line: str) -> None:
            # write to stdout regardless of stream so order is preserved.
            sys.stdout.write(line)
            sys.stdout.flush()

        on_line = _default_on_line

    proc = subprocess.Popen(
        list(cmd),
        stdin=subprocess.PIPE if stdin_input is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # line-buffered
        env=env,
    )
    if stdin_input is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin_input)
            proc.stdin.flush()
        finally:
            proc.stdin.close()

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def _reader(stream: IO[str], name: str, sink: list[str]) -> None:
        for line in iter(stream.readline, ""):
            sink.append(line)
            try:
                on_line(name, line)
            except Exception:  # noqa: BLE001 -- never let a callback kill the subprocess
                pass
        stream.close()

    assert proc.stdout is not None and proc.stderr is not None
    t_out = threading.Thread(
        target=_reader, args=(proc.stdout, "stdout", stdout_chunks), daemon=True
    )
    t_err = threading.Thread(
        target=_reader, args=(proc.stderr, "stderr", stderr_chunks), daemon=True
    )
    t_out.start()
    t_err.start()
    returncode = proc.wait()
    t_out.join()
    t_err.join()
    return subprocess.CompletedProcess(
        args=list(cmd),
        returncode=returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )


class HeartbeatPrinter:
    """Print a 'still running' heartbeat to stdout when the subprocess
    has been silent for a while. Useful for resourcecompiler.exe, which
    can spend minutes inside a single asset with no output. Threaded so
    it doesn't interfere with the subprocess readers."""

    def __init__(self, interval: float = 5.0, label: str = "importer") -> None:
        self.interval = interval
        self.label = label
        self._last_line_at = time.monotonic()
        self._start = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def saw_line(self) -> None:
        with self._lock:
            self._last_line_at = time.monotonic()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 1)

    def _tick(self) -> None:
        while not self._stop.wait(self.interval):
            with self._lock:
                idle = time.monotonic() - self._last_line_at
                elapsed = time.monotonic() - self._start
            if idle >= self.interval:
                sys.stdout.write(
                    f"[{self.label}] still running ({_fmt_elapsed(elapsed)} elapsed, "
                    f"{_fmt_elapsed(idle)} since last output)...\n"
                )
                sys.stdout.flush()


def _fmt_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"

