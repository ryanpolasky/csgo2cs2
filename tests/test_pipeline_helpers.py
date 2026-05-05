# tests for pure helpers in pipeline.py: mapname derivation and
# vmf staging into the importer's required <s1contentdir>/maps/<name>.vmf
# layout.

from __future__ import annotations

from pathlib import Path

import pytest

from csgo2cs2.pipeline import _derive_mapname, _stage_vmf


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("de_dust2.bsp", "de_dust2"),
        ("de Dust 2!.bsp", "de_dust_2_"),
        ("UPPERCASE.bsp", "uppercase"),
        ("---.bsp", "map"),
    ],
)
def test_derive_mapname(filename: str, expected: str):
    assert _derive_mapname(Path(filename)) == expected


def test_stage_vmf_basic(tmp_path: Path):
    src = tmp_path / "src" / "de_example.vmf"
    src.parent.mkdir(parents=True)
    src.write_text("// vmf content\n", encoding="utf-8")

    workspace = tmp_path / "ws"
    workspace.mkdir()

    s1_content_dir = _stage_vmf(src, workspace, "de_example")
    assert s1_content_dir == workspace / "staged"
    staged = s1_content_dir / "maps" / "de_example.vmf"
    assert staged.exists()
    assert staged.read_text(encoding="utf-8") == "// vmf content\n"


def test_stage_vmf_copies_instances(tmp_path: Path):
    # bspsource emits instances/ next to the .vmf when the map uses
    # func_instance entities. the importer needs them to live alongside
    # the staged copy.
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "de_example.vmf").write_text("// vmf\n", encoding="utf-8")
    inst_dir = src_dir / "instances"
    inst_dir.mkdir()
    (inst_dir / "spawn.vmf").write_text("// instance\n", encoding="utf-8")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    s1_content_dir = _stage_vmf(src_dir / "de_example.vmf", workspace, "de_example")

    staged_inst = s1_content_dir / "maps" / "instances" / "spawn.vmf"
    assert staged_inst.exists()
    assert staged_inst.read_text(encoding="utf-8") == "// instance\n"


def test_stage_vmf_missing_source_raises(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(FileNotFoundError):
        _stage_vmf(tmp_path / "missing.vmf", workspace, "x")
