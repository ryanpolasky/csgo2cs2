from __future__ import annotations

import os
from pathlib import Path

from csgo2cs2.utils import run_log


def test_start_logging_writes_a_log_file(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "ws"
    with run_log.start_logging(workspace, "test-cmd") as log:
        assert log is not None
        print("hello from inside the run")

    logs_dir = workspace / "logs"
    files = list(logs_dir.glob("*.log"))
    assert len(files) == 1, f"expected exactly one log, got {files}"
    contents = files[0].read_text(encoding="utf-8")
    assert "hello from inside the run" in contents
    assert "# csgo2cs2 run log" in contents


def test_run_log_strips_ansi_escapes(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    with run_log.start_logging(workspace, "test-ansi") as log:
        assert log is not None
        # write a colored line
        print("\x1b[32mGREEN\x1b[0m text")
    files = list((workspace / "logs").glob("*.log"))
    contents = files[0].read_text(encoding="utf-8")
    assert "GREEN" in contents
    assert "\x1b[" not in contents


def test_disabled_via_env_var(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CSGO2CS2_NO_LOG", "1")
    workspace = tmp_path / "ws"
    with run_log.start_logging(workspace, "test-disabled") as log:
        assert log is None
        print("not captured")
    # no logs dir at all
    assert not (workspace / "logs").exists()


def test_record_subprocess_writes_to_log(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    with run_log.start_logging(workspace, "test-sub") as log:
        assert log is not None
        log.record_subprocess(
            "fake-tool",
            ["fake-tool", "--flag", "value"],
            returncode=1,
            stdout="some stdout output",
            stderr="some stderr output",
        )
    files = list((workspace / "logs").glob("*.log"))
    contents = files[0].read_text(encoding="utf-8")
    assert "subprocess: fake-tool" in contents
    assert "returncode=1" in contents
    assert "some stdout output" in contents
    assert "some stderr output" in contents


def test_log_event_helper_appends(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    with run_log.start_logging(workspace, "test-event") as log:
        assert log is not None
        run_log.log_event("first event")
        run_log.log_event("second event")
    files = list((workspace / "logs").glob("*.log"))
    contents = files[0].read_text(encoding="utf-8")
    assert "first event" in contents
    assert "second event" in contents


def test_prune_old_keeps_n_newest(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    logs_dir = workspace / "logs"
    logs_dir.mkdir(parents=True)

    # create 10 fake logs with increasing mtimes
    for i in range(10):
        f = logs_dir / f"run-{i:02d}.log"
        f.write_text(f"log {i}")
        os.utime(f, (1_000_000 + i, 1_000_000 + i))

    deleted = run_log.prune_old(workspace, keep=3)
    assert deleted == 7
    remaining = sorted(p.name for p in logs_dir.iterdir())
    # the 3 newest are 07, 08, 09
    assert remaining == ["run-07.log", "run-08.log", "run-09.log"]


def test_prune_old_no_logs_dir_is_noop(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-no-logs"
    deleted = run_log.prune_old(workspace, keep=5)
    assert deleted == 0


def test_current_returns_none_outside_context(tmp_path: Path) -> None:
    assert run_log.current() is None


def test_current_returns_log_inside_context(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    with run_log.start_logging(workspace, "test-cur") as log:
        assert run_log.current() is log
    assert run_log.current() is None
