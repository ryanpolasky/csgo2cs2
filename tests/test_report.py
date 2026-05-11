# tests for the structured report builder + --report-json plumbing.

from __future__ import annotations

import argparse
import io
import json
import struct
from contextlib import redirect_stdout

from csgo2cs2 import __version__
from csgo2cs2.analyzers.bsp import LUMP_PAKFILE, inspect_bsp
from csgo2cs2.analyzers.report import REPORT_SCHEMA_VERSION, build_report, write_report
from csgo2cs2.analyzers.vmf import analyze_vmf
from csgo2cs2.commands import analyze as analyze_cmd

VMF_WITH_ISSUES = """\
world
{
\t"id" "1"
\t"classname" "worldspawn"
\t"skyname" "sky_office_hdr"
}
entity
{
\t"id" "20"
\t"classname" "env_cascade_light"
}
"""


def _bsp_with_pakfile(path) -> None:
    # tiny header + empty pakfile lump pointing at zero-length blob
    header = b"VBSP" + struct.pack("<i", 21)
    lump_table = bytearray(64 * 16)
    pak_offset = 8 + 64 * 16
    struct.pack_into(
        "<iiI4s",
        lump_table,
        LUMP_PAKFILE * 16,
        pak_offset,
        0,  # zero-length means "no pakfile lump"
        0,
        b"\x00\x00\x00\x00",
    )
    path.write_bytes(header + bytes(lump_table))


def test_build_report_summary_counts_severities():
    a = analyze_vmf(VMF_WITH_ISSUES)
    report = build_report(vmf=a)
    s = report["summary"]
    assert s["total"] == len(a.findings)
    assert s["error"] >= 1  # hdr-only sky
    assert s["warn"] >= 1  # entity_unsupported
    assert s["fixable"] >= 1


def test_build_report_includes_schema_and_tool_version():
    report = build_report()
    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["tool_version"] == __version__
    assert report["summary"]["total"] == 0


def test_build_report_includes_bsp_section(tmp_path):
    bsp_path = tmp_path / "tiny.bsp"
    _bsp_with_pakfile(bsp_path)
    a = analyze_vmf(VMF_WITH_ISSUES)
    info = inspect_bsp(bsp_path)
    report = build_report(vmf=a, bsp=info, inputs={"vmf": "x.vmf", "bsp": str(bsp_path)})
    assert report["bsp"]["valid_header"] is True
    assert report["bsp"]["version"] == 21
    assert report["inputs"]["bsp"] == str(bsp_path)


def test_write_report_serializes_pretty_json(tmp_path):
    a = analyze_vmf(VMF_WITH_ISSUES)
    report = build_report(vmf=a)
    dest = tmp_path / "out" / "report.json"
    written = write_report(report, dest)
    assert written == dest
    assert dest.exists()
    raw = dest.read_text()
    parsed = json.loads(raw)
    assert parsed["schema_version"] == REPORT_SCHEMA_VERSION
    # sort_keys is on so the output is byte-identical across runs
    assert raw == json.dumps(parsed, indent=2, sort_keys=True)


def test_analyze_command_report_json_to_stdout(tmp_path):
    vmf_path = tmp_path / "in.vmf"
    vmf_path.write_text(VMF_WITH_ISSUES)
    args = argparse.Namespace(
        config=None,
        vmf=str(vmf_path),
        bsp=None,
        fix=False,
        output=None,
        report_json="-",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = analyze_cmd.run(args)
    parsed = json.loads(buf.getvalue())
    # there are findings, so analyze returns 1 even in --report-json mode
    assert rc == 1
    assert parsed["schema_version"] == REPORT_SCHEMA_VERSION
    issue_ids = {f["issue_id"] for f in parsed["findings"]}
    assert "skybox_hdr_only" in issue_ids
    assert "entity_unsupported" in issue_ids


def test_analyze_command_report_json_to_file(tmp_path):
    vmf_path = tmp_path / "in.vmf"
    vmf_path.write_text(VMF_WITH_ISSUES)
    out = tmp_path / "report.json"
    args = argparse.Namespace(
        config=None,
        vmf=str(vmf_path),
        bsp=None,
        fix=False,
        output=None,
        report_json=str(out),
    )
    rc = analyze_cmd.run(args)
    assert rc == 1
    assert out.exists()
    parsed = json.loads(out.read_text())
    assert parsed["summary"]["total"] >= 2


def test_analyze_command_report_json_zero_findings_returns_zero(tmp_path):
    clean = """\
versioninfo
{
}
visgroups
{
}
viewsettings
{
}
world
{
\t"id" "1"
\t"classname" "worldspawn"
\t"skyname" "sky_csgo_night02"
}
entity
{
\t"classname" "info_player_terrorist"
}
entity
{
\t"classname" "info_player_counterterrorist"
}
"""
    vmf_path = tmp_path / "clean.vmf"
    vmf_path.write_text(clean)
    args = argparse.Namespace(
        config=None,
        vmf=str(vmf_path),
        bsp=None,
        fix=False,
        output=None,
        report_json="-",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = analyze_cmd.run(args)
    parsed = json.loads(buf.getvalue())
    assert rc == 0
    assert parsed["summary"]["total"] == 0

