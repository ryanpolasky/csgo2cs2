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
from csgo2cs2.tools.import_map import ImportInputs, ImportMapTool


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
