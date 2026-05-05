# tests for the bsp pakfile inventory.

from __future__ import annotations

import io
import struct
import zipfile

from csgo2cs2.analyzers.bsp import (
    LUMP_PAKFILE,
    PROTECTION_MARKERS,
    analyze_bsp_findings,
    filter_interesting,
    inspect_bsp,
)


def _write_synthetic_bsp(path, pakfile_blob: bytes, version: int = 21) -> None:
    # 8-byte file header + 64 16-byte lump headers + pakfile blob.
    header = b"VBSP" + struct.pack("<i", version)
    lump_table = bytearray(64 * 16)
    pak_offset = 8 + 64 * 16
    pak_length = len(pakfile_blob)
    struct.pack_into(
        "<iiI4s",
        lump_table,
        LUMP_PAKFILE * 16,
        pak_offset,
        pak_length,
        0,
        b"\x00\x00\x00\x00",
    )
    path.write_bytes(header + bytes(lump_table) + pakfile_blob)


def _zip_blob(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_inspect_bsp_reports_valid_header_and_no_pakfile(tmp_path):
    bsp = tmp_path / "empty.bsp"
    bsp.write_bytes(b"VBSP" + struct.pack("<i", 21) + b"\x00" * (64 * 16))
    info = inspect_bsp(bsp)
    assert info.valid_header
    assert info.version == 21
    assert info.pakfile_count == 0
    assert info.pakfile_error == "no pakfile lump"


def test_inspect_bsp_reads_pakfile_inventory(tmp_path):
    blob = _zip_blob(
        {
            "materials/wall.vmt": b"vmt body",
            "models/box.mdl": b"mdl body",
            "scripts/notes.txt": b"notes",
        }
    )
    bsp = tmp_path / "with_pak.bsp"
    _write_synthetic_bsp(bsp, blob)

    info = inspect_bsp(bsp)
    assert info.valid_header
    assert info.pakfile_count == 3
    assert info.pakfile_error == ""
    names = sorted(e.name for e in info.pakfile_entries)
    assert names == ["materials/wall.vmt", "models/box.mdl", "scripts/notes.txt"]


def test_filter_interesting_only_keeps_known_extensions(tmp_path):
    blob = _zip_blob(
        {
            "materials/wall.vmt": b"x",
            "scripts/notes.txt": b"x",
            "models/box.mdl": b"x",
        }
    )
    bsp = tmp_path / "filter.bsp"
    _write_synthetic_bsp(bsp, blob)
    info = inspect_bsp(bsp)
    interesting = sorted(e.name for e in filter_interesting(info.pakfile_entries))
    assert interesting == ["materials/wall.vmt", "models/box.mdl"]


def test_inspect_bsp_handles_corrupt_pakfile(tmp_path):
    bsp = tmp_path / "corrupt.bsp"
    _write_synthetic_bsp(bsp, b"NOTAZIP\x00\x00\x00\x00")
    info = inspect_bsp(bsp)
    assert info.valid_header
    assert info.pakfile_count == 0
    assert "not a valid zip" in info.pakfile_error


def test_inspect_bsp_detects_protection_marker(tmp_path):
    bsp = tmp_path / "protected.bsp"
    bsp.write_bytes(
        b"VBSP" + struct.pack("<i", 21) + b"\x00" * 100 + PROTECTION_MARKERS[0] + b"\x00" * 1000
    )
    info = inspect_bsp(bsp)
    assert info.suspected_protected
    assert info.detected_marker == PROTECTION_MARKERS[0].decode("ascii")


def test_inspect_bsp_invalid_header(tmp_path):
    bsp = tmp_path / "bad.bsp"
    bsp.write_bytes(b"NOPE" + b"\x00" * 100)
    info = inspect_bsp(bsp)
    assert info.valid_header is False
    # we don't try to parse the pakfile when the header is invalid
    assert info.pakfile_count == 0
    assert info.pakfile_entries == []


# ---------------------------------------------------------------------------
# pr3: bsp pakfile -> findings
# ---------------------------------------------------------------------------


def test_analyze_bsp_findings_invalid_header_emits_error(tmp_path):
    bsp = tmp_path / "bad.bsp"
    bsp.write_bytes(b"NOPE" + b"\x00" * 100)
    info = inspect_bsp(bsp)
    findings = analyze_bsp_findings(info)
    ids = [f.issue_id for f in findings]
    assert ids == ["bsp_invalid_header"]
    assert findings[0].severity == "error"


def test_analyze_bsp_findings_protected_emits_finding(tmp_path):
    bsp = tmp_path / "protected.bsp"
    bsp.write_bytes(
        b"VBSP" + struct.pack("<i", 21) + b"\x00" * 100 + PROTECTION_MARKERS[0] + b"\x00" * 1000
    )
    info = inspect_bsp(bsp)
    findings = analyze_bsp_findings(info)
    assert any(f.issue_id == "bsp_protected" for f in findings)


def test_analyze_bsp_findings_emits_nav_radar_soundscape_lua_csgo(tmp_path):
    blob = _zip_blob(
        {
            "maps/de_dust2.nav": b"nav",
            "resource/overviews/de_dust2_radar.dds": b"radar",
            "scripts/soundscapes_de_dust2.txt": b"soundscape",
            "scripts/vscripts/foo.nut": b"squirrel",
            "scripts/vscripts/bar.lua": b"lua",
            "materials/csgo/de_dust2/wall.vmt": b"vmt",
            "materials/maps/cubemap_001.hdr.vtf": b"cube",
        }
    )
    bsp = tmp_path / "rich.bsp"
    _write_synthetic_bsp(bsp, blob)
    info = inspect_bsp(bsp)
    findings = analyze_bsp_findings(info)
    ids = {f.issue_id for f in findings}
    assert {
        "manual_rebuild_nav",
        "manual_rebuild_radar",
        "manual_review_soundscapes",
        "pakfile_scripts",
        "pakfile_csgo_subfolder",
        "manual_rebuild_cubemaps",
    }.issubset(ids)


def test_analyze_bsp_findings_clean_pakfile_emits_no_findings(tmp_path):
    blob = _zip_blob(
        {
            "materials/maps/dust2/floor.vmt": b"vmt",
            "models/de_dust2/box.mdl": b"mdl",
        }
    )
    bsp = tmp_path / "clean.bsp"
    _write_synthetic_bsp(bsp, blob)
    info = inspect_bsp(bsp)
    findings = analyze_bsp_findings(info)
    assert findings == []
