"""Tests for the built-in BSP pakfile extractor.

The fallback path is what unblocks users who don't have vpkedit/bspzip
installed -- without it, maps with embedded materials/models came out
as pink-and-black checkerboards after import.
"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

from csgo2cs2.config import Config
from csgo2cs2.extract import (
    _read_pakfile_lump_offset,
    extract_bsp_assets,
    extract_pakfile_lump_python,
)

_BSP_PAKFILE_LUMP = 40
_BSP_NUM_LUMPS = 64
_BSP_LUMP_ENTRY_SIZE = 16
_BSP_HEADER_BYTES = 8 + _BSP_NUM_LUMPS * _BSP_LUMP_ENTRY_SIZE  # = 1032


def _write_fake_bsp(
    path: Path,
    pakfile_payload: bytes,
    magic: bytes = b"VBSP",
    version: int = 21,
) -> None:
    """Craft a minimal VBSP file with a single populated pakfile lump.

    The pakfile lump points at `pakfile_payload` placed immediately
    after the header. All other lumps are zero-sized."""
    with path.open("wb") as f:
        f.write(magic)  # 4 bytes
        f.write(struct.pack("<i", version))  # 4 bytes
        for i in range(_BSP_NUM_LUMPS):
            if i == _BSP_PAKFILE_LUMP:
                fileofs = _BSP_HEADER_BYTES
                filelen = len(pakfile_payload)
                f.write(struct.pack("<iii4s", fileofs, filelen, 0, b"\x00\x00\x00\x00"))
            else:
                f.write(struct.pack("<iii4s", 0, 0, 0, b"\x00\x00\x00\x00"))
        # payload starts at _BSP_HEADER_BYTES (verified above).
        f.write(pakfile_payload)


def _make_zip_bytes(entries: dict[str, bytes]) -> bytes:
    """Build an in-memory PKZIP archive with the given entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


# -------- _read_pakfile_lump_offset ----------------------------------


def test_read_pakfile_lump_offset_returns_zero_for_nonvbsp(tmp_path: Path) -> None:
    p = tmp_path / "not.bsp"
    p.write_bytes(b"NOPE" + b"\x00" * 100)
    assert _read_pakfile_lump_offset(p) == (0, 0)


def test_read_pakfile_lump_offset_returns_zero_for_empty_lump(tmp_path: Path) -> None:
    p = tmp_path / "empty.bsp"
    _write_fake_bsp(p, b"")
    # _write_fake_bsp puts (fileofs=header, filelen=0); filelen <= 0
    # short-circuits to (0, 0) per the helper's contract.
    assert _read_pakfile_lump_offset(p) == (0, 0)


def test_read_pakfile_lump_offset_returns_offsets_for_real_pakfile(tmp_path: Path) -> None:
    p = tmp_path / "real.bsp"
    payload = _make_zip_bytes({"materials/foo.vmt": b"// hi\n"})
    _write_fake_bsp(p, payload)
    fileofs, filelen = _read_pakfile_lump_offset(p)
    assert fileofs == _BSP_HEADER_BYTES
    assert filelen == len(payload)


def test_read_pakfile_lump_offset_returns_zero_for_missing_file(tmp_path: Path) -> None:
    assert _read_pakfile_lump_offset(tmp_path / "absent.bsp") == (0, 0)


# -------- extract_pakfile_lump_python --------------------------------


def test_extract_pakfile_lump_python_writes_files(tmp_path: Path) -> None:
    bsp = tmp_path / "map.bsp"
    out = tmp_path / "out"
    payload = _make_zip_bytes(
        {
            "materials/foo/red.vmt": b'"VertexLitGeneric" { "$basetexture" "foo/red" }',
            "materials/foo/red.vtf": b"VTF\x00fakeheader",
            "models/foo.mdl": b"IDST\x00fakemodel",
        }
    )
    _write_fake_bsp(bsp, payload)
    ok, count = extract_pakfile_lump_python(bsp, out)
    assert ok is True
    assert count == 3
    assert (out / "materials" / "foo" / "red.vmt").is_file()
    assert (out / "materials" / "foo" / "red.vtf").is_file()
    assert (out / "models" / "foo.mdl").is_file()


def test_extract_pakfile_lump_python_handles_missing_pakfile(tmp_path: Path) -> None:
    bsp = tmp_path / "nopak.bsp"
    out = tmp_path / "out"
    _write_fake_bsp(bsp, b"")
    ok, count = extract_pakfile_lump_python(bsp, out)
    assert ok is False
    assert count == 0
    assert not out.exists() or not any(out.iterdir())


def test_extract_pakfile_lump_python_rejects_garbage_payload(tmp_path: Path) -> None:
    bsp = tmp_path / "broken.bsp"
    out = tmp_path / "out"
    _write_fake_bsp(bsp, b"not-a-zip-archive-at-all-12345")
    ok, count = extract_pakfile_lump_python(bsp, out)
    assert ok is False
    assert count == 0


def test_extract_pakfile_lump_python_rejects_nonvbsp(tmp_path: Path) -> None:
    bsp = tmp_path / "wrong.bsp"
    bsp.write_bytes(b"PSBV" + b"\x00" * 100)
    out = tmp_path / "out"
    ok, count = extract_pakfile_lump_python(bsp, out)
    assert ok is False
    assert count == 0


# -------- extract_bsp_assets (integration) ----------------------------


def test_extract_bsp_assets_falls_back_to_builtin_when_no_tools(tmp_path: Path) -> None:
    """When neither vpkedit nor bspzip are configured, the built-in
    extractor takes over. This is the path that fixes the
    recoil_master "no extraction tool available" warning."""
    bsp = tmp_path / "map.bsp"
    out = tmp_path / "extracted"
    payload = _make_zip_bytes({"materials/foo.vmt": b'"vertexlitgeneric" {}'})
    _write_fake_bsp(bsp, payload)
    cfg = Config()  # vpkedit_path/bspzip_path are both None
    result = extract_bsp_assets(cfg, bsp, out)
    assert result.succeeded is True
    assert result.tool_used == "builtin_pakfile"
    assert (out / "materials" / "foo.vmt").is_file()


def test_extract_bsp_assets_reports_failure_when_bsp_has_no_pakfile(tmp_path: Path) -> None:
    bsp = tmp_path / "nopak.bsp"
    out = tmp_path / "extracted"
    _write_fake_bsp(bsp, b"")
    cfg = Config()
    result = extract_bsp_assets(cfg, bsp, out)
    assert result.succeeded is False
    assert result.tool_used is None
    assert "rely on base CS:GO" in result.detail


def test_extract_bsp_assets_builtin_handles_subdirs(tmp_path: Path) -> None:
    """Real CSGO map pakfiles contain deeply-nested paths under
    `materials/<addon>/<category>/...`. Verify zipfile.extractall keeps
    that structure intact so source1import can locate the .vmt files."""
    bsp = tmp_path / "map.bsp"
    out = tmp_path / "extracted"
    payload = _make_zip_bytes(
        {
            "materials/recoil_master/banners/sticker.vmt": b"sticker\n",
            "materials/recoil_master/banners/sticker.vtf": b"vtf\n",
            "materials/recoil_master/icons/ghosthair.vmt": b"ghosthair\n",
            "sound/recoil_master/click.wav": b"riff",
        }
    )
    _write_fake_bsp(bsp, payload)
    cfg = Config()
    result = extract_bsp_assets(cfg, bsp, out)
    assert result.succeeded is True
    assert (out / "materials" / "recoil_master" / "banners" / "sticker.vmt").is_file()
    assert (out / "materials" / "recoil_master" / "icons" / "ghosthair.vmt").is_file()
    assert (out / "sound" / "recoil_master" / "click.wav").is_file()
