from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from csgo2cs2.utils import atomic


def test_write_bytes_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    atomic.write_bytes(target, b"hello")
    assert target.read_bytes() == b"hello"


def test_write_text_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic.write_text(target, "line one\nline two\n")
    assert target.read_text(encoding="utf-8") == "line one\nline two\n"


def test_write_json_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    payload = {"a": 1, "b": [2, 3], "c": {"nested": True}}
    atomic.write_json(target, payload)
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_write_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("OLD CONTENT", encoding="utf-8")
    atomic.write_text(target, "NEW CONTENT")
    assert target.read_text(encoding="utf-8") == "NEW CONTENT"


def test_write_does_not_leave_temp_files_on_success(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic.write_text(target, "ok")
    # only the target should exist; no stray "out.txt.tmp" / "out.txt.XXX"
    stray = [
        p for p in tmp_path.iterdir() if p.name != target.name and p.name.startswith("out.txt")
    ]
    assert not stray, f"expected no stray temp files, found {stray}"


def test_write_failure_does_not_leave_partial_target(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "out.bin"
    target.write_bytes(b"PREVIOUS")

    # force os.replace to raise -- this simulates a rename failure
    # (e.g. cross-device or permission denied).
    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        atomic.write_bytes(target, b"NEW")

    # the previous content must still be intact (atomic property).
    assert target.read_bytes() == b"PREVIOUS"

    # restore for cleanup
    monkeypatch.setattr(os, "replace", real_replace)


def test_concurrent_writes_do_not_corrupt(tmp_path: Path) -> None:
    target = tmp_path / "concurrent.json"

    payload_a = {"who": "a", "vals": list(range(50))}
    payload_b = {"who": "b", "vals": list(range(50, 100))}

    def writer(payload):
        for _ in range(10):
            atomic.write_json(target, payload)

    t1 = threading.Thread(target=writer, args=(payload_a,))
    t2 = threading.Thread(target=writer, args=(payload_b,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # whatever the final content is, it must be a fully parseable JSON
    # blob -- never a torn half-write.
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed in (payload_a, payload_b)


def test_write_parent_directory_is_created(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "out.txt"
    atomic.write_text(nested, "deep")
    assert nested.read_text(encoding="utf-8") == "deep"
