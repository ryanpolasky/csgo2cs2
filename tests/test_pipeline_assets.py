# tests for the PR4 pipeline additions: asset pre-copy + dry-run helpers.

from __future__ import annotations

from pathlib import Path

from csgo2cs2.pipeline import _stage_assets


def _touch(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# --- _stage_assets ----------------------------------------------------------


def test_stage_assets_copies_known_subdirs(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    staged = tmp_path / "staged"
    _touch(extracted / "materials" / "custom" / "wall.vmt", b"vmt")
    _touch(extracted / "materials" / "custom" / "wall.vtf", b"vtf")
    _touch(extracted / "models" / "props" / "thing.mdl", b"mdl")
    _touch(extracted / "sound" / "ambient" / "hum.wav", b"wav")
    _touch(extracted / "scripts" / "soundscapes_de_aztec.txt", b"sndscp")
    _touch(extracted / "particles" / "thing.pcf", b"pcf")
    _touch(extracted / "resource" / "overviews" / "de_aztec_radar.dds", b"radar")
    # not a known subdir; should be skipped
    _touch(extracted / "junk" / "ignore.bin", b"junk")

    n = _stage_assets(extracted, staged)
    assert n == 7

    assert (staged / "materials" / "custom" / "wall.vmt").read_bytes() == b"vmt"
    assert (staged / "materials" / "custom" / "wall.vtf").read_bytes() == b"vtf"
    assert (staged / "models" / "props" / "thing.mdl").read_bytes() == b"mdl"
    assert (staged / "sound" / "ambient" / "hum.wav").read_bytes() == b"wav"
    assert (staged / "scripts" / "soundscapes_de_aztec.txt").read_bytes() == b"sndscp"
    assert (staged / "particles" / "thing.pcf").read_bytes() == b"pcf"
    assert (staged / "resource" / "overviews" / "de_aztec_radar.dds").read_bytes() == b"radar"

    # unknown subdir not copied
    assert not (staged / "junk").exists()


def test_stage_assets_returns_zero_for_missing_extracted(tmp_path: Path) -> None:
    # extracted dir doesn't exist at all
    n = _stage_assets(tmp_path / "does-not-exist", tmp_path / "staged")
    assert n == 0


def test_stage_assets_skips_already_present_files(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    staged = tmp_path / "staged"
    _touch(extracted / "materials" / "a.vmt", b"hello")
    # pre-populate destination with identical content (same size)
    _touch(staged / "materials" / "a.vmt", b"hello")

    n = _stage_assets(extracted, staged)
    # no copy because file already exists at same size
    assert n == 0
    assert (staged / "materials" / "a.vmt").read_bytes() == b"hello"


def test_stage_assets_overwrites_when_size_differs(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    staged = tmp_path / "staged"
    _touch(extracted / "materials" / "a.vmt", b"longer-content")
    _touch(staged / "materials" / "a.vmt", b"old")  # different size

    n = _stage_assets(extracted, staged)
    assert n == 1
    assert (staged / "materials" / "a.vmt").read_bytes() == b"longer-content"


def test_stage_assets_with_no_known_subdirs(tmp_path: Path) -> None:
    # extracted dir exists but has only unknown subdirs
    extracted = tmp_path / "extracted"
    staged = tmp_path / "staged"
    _touch(extracted / "weird" / "x.bin", b"x")

    n = _stage_assets(extracted, staged)
    assert n == 0
    assert not staged.exists() or not any(staged.iterdir())
