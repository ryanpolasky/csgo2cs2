# tests for the import_map adapter command construction.
#
# we cannot actually run import_map_community.py from the suite (it's
# windows-only and depends on a real cs2 install), but we can verify the
# command we *would* invoke is shaped correctly.

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from csgo2cs2.platform_check import WindowsRequiredError
from csgo2cs2.tools.import_map import (
    HeartbeatPrinter,
    ImportInputs,
    ImportMapTool,
    _env_with_extra_path,
    _fmt_elapsed,
    _run_streaming,
)


def _inputs(tmp_path: Path) -> ImportInputs:
    return ImportInputs(
        s1_gameinfo_dir=tmp_path / "csgo",
        s1_content_dir=tmp_path / "content",
        s2_gameinfo_dir=tmp_path / "cs2" / "game" / "csgo",
        s2_addon="my_addon",
        mapname="de_example",
    )


def _resolved_importer(tmp_path: Path) -> Path:
    p = tmp_path / "import_map_community.py"
    p.write_text("# stub\n", encoding="utf-8")
    return p


def test_resolve_returns_none_when_unset():
    tool = ImportMapTool()
    assert tool.resolve() is None


def test_resolve_finds_existing_path(tmp_path):
    p = _resolved_importer(tmp_path)
    assert ImportMapTool(importer_path=str(p)).resolve() == p


def test_import_map_requires_windows(tmp_path):
    if sys.platform.startswith("win"):
        pytest.skip("test only applies off-Windows")
    importer = _resolved_importer(tmp_path)
    tool = ImportMapTool(importer_path=str(importer))
    with pytest.raises(WindowsRequiredError):
        tool.import_map(_inputs(tmp_path))


def test_import_map_fails_when_unconfigured(tmp_path):
    tool = ImportMapTool()  # no importer_path
    # patch require_windows so the test runs cross-platform
    with (
        patch("csgo2cs2.tools.import_map.require_windows", lambda *_a, **_k: None),
        pytest.raises(RuntimeError, match="not configured"),
    ):
        tool.import_map(_inputs(tmp_path))


def test_import_map_command_shape_default(tmp_path):
    importer = _resolved_importer(tmp_path)
    tool = ImportMapTool(importer_path=str(importer), python_executable="py3")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with (
        patch("csgo2cs2.tools.import_map.require_windows", lambda *_a, **_k: None),
        patch("csgo2cs2.tools.import_map.subprocess.run", fake_run),
    ):
        tool.import_map(_inputs(tmp_path))

    cmd = captured["cmd"]
    assert cmd[0] == "py3"
    assert cmd[1] == str(importer)
    assert cmd[2] == str(tmp_path / "csgo")
    assert cmd[3] == str(tmp_path / "content")
    assert cmd[4] == str(tmp_path / "cs2" / "game" / "csgo")
    assert cmd[5] == "my_addon"
    assert cmd[6] == "de_example"
    assert "-usebsp" in cmd
    assert "-skipdeps" not in cmd
    assert "-usebsp_nomergeinstances" not in cmd


def test_import_map_command_shape_no_merge_instances(tmp_path):
    importer = _resolved_importer(tmp_path)
    tool = ImportMapTool(importer_path=str(importer))
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with (
        patch("csgo2cs2.tools.import_map.require_windows", lambda *_a, **_k: None),
        patch("csgo2cs2.tools.import_map.subprocess.run", fake_run),
    ):
        tool.import_map(_inputs(tmp_path), no_merge_instances=True, skip_deps=True)

    cmd = captured["cmd"]
    assert "-usebsp_nomergeinstances" in cmd
    assert "-usebsp" not in cmd  # mutually exclusive with the no-merge variant
    assert "-skipdeps" in cmd


def test_import_map_command_shape_no_use_bsp(tmp_path):
    importer = _resolved_importer(tmp_path)
    tool = ImportMapTool(importer_path=str(importer))
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with (
        patch("csgo2cs2.tools.import_map.require_windows", lambda *_a, **_k: None),
        patch("csgo2cs2.tools.import_map.subprocess.run", fake_run),
    ):
        tool.import_map(_inputs(tmp_path), use_bsp=False)

    cmd = captured["cmd"]
    assert "-usebsp" not in cmd
    assert "-usebsp_nomergeinstances" not in cmd


def test_import_map_default_python_executable_is_current_interpreter(tmp_path):
    """Regression for the Windows colorama crash: when the user hasn't
    set `python_executable` in their config, we must NOT shell out as a
    bare `python` (which resolves via PATH, frequently to a different
    interpreter than the one running csgo2cs2). Default to sys.executable
    so the importer inherits our exact site-packages."""
    importer = _resolved_importer(tmp_path)
    tool = ImportMapTool(importer_path=str(importer))
    cmd = tool.build_command(_inputs(tmp_path))
    assert cmd[0] == sys.executable


def test_import_map_explicit_python_executable_wins(tmp_path):
    """An explicit `python_executable` (config override) is preserved."""
    importer = _resolved_importer(tmp_path)
    tool = ImportMapTool(importer_path=str(importer), python_executable="C:/Other/python.exe")
    cmd = tool.build_command(_inputs(tmp_path))
    assert cmd[0] == "C:/Other/python.exe"


def test_import_map_none_python_executable_falls_back(tmp_path):
    """Passing explicit None (e.g. cfg.python_executable when unset)
    should be treated the same as omitting the arg."""
    importer = _resolved_importer(tmp_path)
    tool = ImportMapTool(importer_path=str(importer), python_executable=None)
    cmd = tool.build_command(_inputs(tmp_path))
    assert cmd[0] == sys.executable


def test_env_with_extra_path_prepends(tmp_path):
    """cs2_bin_path must be prepended to subprocess PATH so Valve's
    importer can find resourcecompiler.exe without the user having
    edited their system PATH."""
    import os

    env = _env_with_extra_path([tmp_path])
    assert env is not None
    assert env["PATH"].startswith(str(tmp_path) + os.pathsep)


def test_env_with_extra_path_none_returns_none():
    """No extra dirs -> no env override, subprocess inherits."""
    assert _env_with_extra_path(None) is None
    assert _env_with_extra_path([]) is None


def test_fmt_elapsed_renders_units():
    assert _fmt_elapsed(0) == "0s"
    assert _fmt_elapsed(45) == "45s"
    assert _fmt_elapsed(60) == "1m00s"
    assert _fmt_elapsed(3725) == "1h02m"


def test_run_streaming_relays_each_line():
    """Each subprocess output line must hit the callback once, in order,
    and the final captured stdout/stderr must contain everything."""
    lines: list[tuple[str, str]] = []

    def collector(stream: str, line: str) -> None:
        lines.append((stream, line))

    # Use the python interpreter as the subprocess so this works
    # cross-platform without external tools.
    result = _run_streaming(
        [sys.executable, "-c", "print('a'); print('b'); print('c')"],
        on_line=collector,
    )
    assert result.returncode == 0
    relayed = [line for _stream, line in lines]
    assert "a\n" in relayed
    assert "b\n" in relayed
    assert "c\n" in relayed
    assert "a\nb\nc\n" in result.stdout


def test_run_streaming_isolates_stdout_and_stderr():
    streams: list[str] = []

    def collector(stream: str, line: str) -> None:
        streams.append(stream)

    result = _run_streaming(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr)",
        ],
        on_line=collector,
    )
    assert result.returncode == 0
    assert "stdout" in streams
    assert "stderr" in streams


def test_run_streaming_propagates_returncode():
    result = _run_streaming(
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        on_line=lambda *_a: None,
    )
    assert result.returncode == 7


def test_heartbeat_can_start_and_stop_without_subprocess():
    """Smoke test: the heartbeat thread must not deadlock on stop()
    even if it never had a chance to fire."""
    hb = HeartbeatPrinter(interval=10.0, label="t")
    hb.start()
    hb.saw_line()
    hb.stop()  # would deadlock if the thread didn't exit on event


def test_run_streaming_feeds_stdin_input():
    """The importer waits on `Enter to Continue, Esc to Quit` -- the
    subprocess must receive the newline we feed it, otherwise it hangs."""
    # echo what we read from stdin back on stdout so we can assert.
    result = _run_streaming(
        [
            sys.executable,
            "-c",
            "import sys; print('read=' + repr(sys.stdin.read()))",
        ],
        on_line=lambda *_a: None,
        stdin_input="\n",
    )
    assert result.returncode == 0
    assert "read=" in result.stdout
    assert "\\n" in result.stdout  # the newline we piped, repr'd


def test_import_map_passes_stdin_input_through_run(tmp_path):
    """Non-streaming path also has to honor stdin_input, since we use it
    for unit tests that call import_map() directly."""
    importer = _resolved_importer(tmp_path)
    tool = ImportMapTool(importer_path=str(importer), python_executable="py3")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["input"] = kwargs.get("input")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with (
        patch("csgo2cs2.tools.import_map.require_windows", lambda *_a, **_k: None),
        patch("csgo2cs2.tools.import_map.subprocess.run", fake_run),
    ):
        tool.import_map(_inputs(tmp_path), stdin_input="\n")

    assert captured["input"] == "\n"

