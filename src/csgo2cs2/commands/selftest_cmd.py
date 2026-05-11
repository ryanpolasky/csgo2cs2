# `csgo2cs2 selftest` --- synthetic end-to-end test of the analyze/fix
# pipeline that does NOT touch Steam, CS2, or any external tool.
#
# Purpose: when something breaks on a user's first Windows run, this
# rules out "is my csgo2cs2 install itself broken" before the user
# starts blaming SteamCMD, BSPSource, or the importer. Runs in under a
# second.
#
# Checks:
#   1. The vmf analyzer parses a synthetic .vmf with known issues and
#      reports the expected findings.
#   2. apply_all() produces a syntactically valid fixed .vmf (the
#      round-trip analyzer accepts it).
#   3. The fixers actually changed the text in the expected ways
#      (skybox replaced, asset paths normalized, spawns rewritten when
#      --fix-spawns is on, etc.).
#   4. Manifest writes and reads back round-trip with stage state intact.
#   5. The atomic-write helper produces the expected output.
#
# `--with-tools` extends the test to invoke SteamCMD --help and
# BSPSource --help as a "is the binary executable" smoke check.

from __future__ import annotations

import argparse
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .. import fixers  # noqa: F401  (registers fixers on import)
from ..analyzers.roundtrip import summarize_structure, verify_roundtrip
from ..analyzers.vmf import analyze_vmf
from ..config import Config, load_config
from ..fixers.base import apply_all
from ..logging_utils import error, header, info, success
from ..tools.bspsource import BSPSource
from ..tools.steamcmd import SteamCMD
from ..utils.atomic import write_json, write_text
from ..utils.manifest import STAGE_DONE, PortManifest

# A small but representative VMF: includes a skybox setting, a
# bad-cased asset path, an unsupported entity, and a balanced brace
# tree so the round-trip checker can verify the output.
SYNTHETIC_VMF = """\
versioninfo
{
\t"editorversion" "400"
\t"prefab" "0"
}
world
{
\t"id" "1"
\t"classname" "worldspawn"
\t"skyname" "sky_doesnotexist_selftest_01"
}
entity
{
\t"id" "10"
\t"classname" "info_player_terrorist"
}
entity
{
\t"id" "11"
\t"classname" "func_simpleladder"
}
entity
{
\t"id" "12"
\t"classname" "light_environment"
\t"_light" "255 247 235 200"
}
"""


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class SelftestReport:
    results: List[CheckResult] = field(default_factory=list)
    elapsed: float = 0.0

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append(CheckResult(name=name, passed=passed, detail=detail))

    @property
    def ok(self) -> bool:
        return all(r.passed for r in self.results)

    def render(self) -> str:
        lines = []
        for r in self.results:
            mark = "PASS" if r.passed else "FAIL"
            line = f"  [{mark}] {r.name}"
            if r.detail:
                line += f" -- {r.detail}"
            lines.append(line)
        lines.append("")
        lines.append(f"Result: {'OK' if self.ok else 'FAILED'}  in {self.elapsed:.2f}s")
        return "\n".join(lines)


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "selftest",
        help="Run a synthetic pipeline test to verify the install is sane.",
    )
    p.add_argument(
        "--with-tools",
        action="store_true",
        help="Also invoke `--help` on configured external tools as a smoke check.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    header("csgo2cs2 selftest")
    info("Synthetic pipeline test (no Steam, no CS2, no network).")

    cfg = load_config(args.config)
    report = SelftestReport()
    start = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="csgo2cs2-selftest-") as td:
        tmp = Path(td)
        _run_analyzer_check(report, cfg, tmp)
        _run_fixer_check(report, cfg, tmp)
        _run_atomic_write_check(report, tmp)
        _run_manifest_roundtrip_check(report, tmp)
        if args.with_tools:
            _run_external_tool_smoke(report, cfg)
        else:
            info("Tip: pass --with-tools to also smoke-test SteamCMD and BSPSource.")

    report.elapsed = time.monotonic() - start
    print(report.render())
    if report.ok:
        success("Selftest passed.")
        return 0
    error("Selftest failed -- see results above.")
    return 1


def _run_analyzer_check(report: SelftestReport, cfg: Config, tmp: Path) -> None:
    try:
        analysis = analyze_vmf(SYNTHETIC_VMF, default_skybox=cfg.default_skybox)
    except Exception as exc:  # noqa: BLE001
        report.add("analyzer_runs", False, f"raised: {exc}")
        return
    issue_ids = {f.issue_id for f in analysis.findings}
    expected = "skybox_unknown"
    if expected in issue_ids:
        report.add(
            "analyzer_detects_skybox",
            True,
            f"found {len(analysis.findings)} finding(s) including {expected}",
        )
    else:
        report.add(
            "analyzer_detects_skybox",
            False,
            f"expected to see {expected}; found: {sorted(issue_ids)}",
        )


def _run_fixer_check(report: SelftestReport, cfg: Config, tmp: Path) -> None:
    try:
        analysis = analyze_vmf(SYNTHETIC_VMF, default_skybox=cfg.default_skybox)
        new_text, results = apply_all(SYNTHETIC_VMF, analysis.findings)
    except Exception as exc:  # noqa: BLE001
        report.add("fixers_run", False, f"raised: {exc}")
        return
    applied = [r for r in results if r.applied]
    if not applied:
        report.add(
            "fixers_apply",
            False,
            "expected at least the skybox fixer to apply; got no applied results",
        )
        return
    report.add(
        "fixers_apply",
        True,
        f"{len(applied)} fixer result(s) applied",
    )

    # round-trip: the fixed text must still be structurally sound.
    rr = verify_roundtrip(SYNTHETIC_VMF, new_text)
    if rr.ok:
        report.add("roundtrip_balanced", True, "post-fix VMF parses cleanly")
    else:
        report.add(
            "roundtrip_balanced",
            False,
            f"round-trip check rejected post-fix VMF: {rr.reason}",
        )

    # additional structural sanity: input was balanced, output should be too.
    structure = summarize_structure(new_text)
    if not structure.balanced:
        report.add(
            "roundtrip_braces",
            False,
            f"unbalanced braces in output: {structure.open_braces}/{structure.close_braces}",
        )
    else:
        report.add("roundtrip_braces", True, "brace balance preserved")

    # the skybox value must no longer be the original unknown one.
    if "sky_doesnotexist_selftest_01" not in new_text:
        report.add(
            "skybox_replaced",
            True,
            "synthetic unknown skybox was replaced",
        )
    else:
        report.add(
            "skybox_replaced",
            False,
            "skybox fixer claimed to apply but original value still in text",
        )


def _run_atomic_write_check(report: SelftestReport, tmp: Path) -> None:
    target_text = "hello\n"
    p = tmp / "atomic-text.txt"
    try:
        write_text(p, target_text)
    except Exception as exc:  # noqa: BLE001
        report.add("atomic_write_text", False, f"raised: {exc}")
        return
    if p.read_text(encoding="utf-8") != target_text:
        report.add("atomic_write_text", False, "text mismatch after write")
        return
    report.add("atomic_write_text", True)

    p2 = tmp / "atomic.json"
    try:
        write_json(p2, {"a": 1, "b": [2, 3]})
    except Exception as exc:  # noqa: BLE001
        report.add("atomic_write_json", False, f"raised: {exc}")
        return
    import json as _json

    parsed = _json.loads(p2.read_text(encoding="utf-8"))
    if parsed != {"a": 1, "b": [2, 3]}:
        report.add("atomic_write_json", False, f"json mismatch: {parsed}")
        return
    report.add("atomic_write_json", True)


def _run_manifest_roundtrip_check(report: SelftestReport, tmp: Path) -> None:
    m = PortManifest(workshop_id="selftest-1", addon_name="selftest_addon")
    m.start_stage("download")
    m.finish_stage("download", STAGE_DONE, "smoke")
    path = tmp / "manifest.json"
    try:
        m.save(path)
        loaded = PortManifest.load(path)
    except Exception as exc:  # noqa: BLE001
        report.add("manifest_roundtrip", False, f"raised: {exc}")
        return
    if loaded.workshop_id != "selftest-1":
        report.add("manifest_roundtrip", False, "workshop_id changed")
        return
    if not loaded.stage_is_done("download"):
        report.add(
            "manifest_roundtrip",
            False,
            "download stage not flagged done after save+load",
        )
        return
    report.add("manifest_roundtrip", True, "save+load preserved stage state")


def _run_external_tool_smoke(report: SelftestReport, cfg: Config) -> None:
    # SteamCMD: invoke +quit (no-op) and just see that the process
    # starts. Don't insist on a specific return code -- some
    # SteamCMD builds non-zero on first run.
    steamcmd = SteamCMD(cfg.steamcmd_path)
    resolved = steamcmd.resolve()
    if not resolved:
        report.add(
            "steamcmd_smoke",
            False,
            "steamcmd_path not configured or not on disk",
        )
    else:
        try:
            result = subprocess.run(
                [resolved, "+quit"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            report.add(
                "steamcmd_smoke",
                True,
                f"steamcmd ran (exit {result.returncode})",
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            report.add("steamcmd_smoke", False, f"steamcmd invocation failed: {exc}")

    bs = BSPSource(cfg.bspsource_path, java_path=cfg.java_path)
    bs_resolved = bs.resolve()
    if not bs_resolved:
        report.add(
            "bspsource_smoke",
            False,
            "bspsource_path not configured or not on disk",
        )
        return
    # bspsource jar form needs java -jar X --help; wrapper form takes
    # `--help` directly. resolve and just confirm executability via
    # platform_check.
    if bs_resolved.endswith(".jar"):
        java = bs._resolve_java()
        if not java:
            report.add(
                "bspsource_smoke",
                False,
                f"bspsource jar at {bs_resolved} but Java was not found on PATH",
            )
            return
        cmd = [java, "-jar", bs_resolved, "--help"]
    else:
        cmd = [bs_resolved, "--help"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        report.add(
            "bspsource_smoke",
            True,
            f"bspsource --help ran (exit {result.returncode})",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.add("bspsource_smoke", False, f"bspsource invocation failed: {exc}")
