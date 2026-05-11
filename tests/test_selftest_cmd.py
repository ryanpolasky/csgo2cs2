from __future__ import annotations

import argparse
import json
from pathlib import Path

from csgo2cs2.commands import selftest_cmd


def _make_args(tmp_path: Path, **overrides) -> argparse.Namespace:
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"workspace_dir": str(tmp_path / "ws")}),
        encoding="utf-8",
    )
    ns = argparse.Namespace(
        config=str(cfg),
        verbose=False,
        command="selftest",
        with_tools=False,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def test_selftest_passes_with_synthetic_pipeline(tmp_path: Path, capsys) -> None:
    args = _make_args(tmp_path)
    rc = selftest_cmd.run(args)
    out = capsys.readouterr().out
    assert "Result: OK" in out
    assert rc == 0


def test_selftest_skips_tool_smoke_by_default(tmp_path: Path, capsys) -> None:
    args = _make_args(tmp_path)
    selftest_cmd.run(args)
    out = capsys.readouterr().out
    # without --with-tools, no smoke test result lines for steamcmd/bspsource
    assert "steamcmd_smoke" not in out
    assert "bspsource_smoke" not in out


def test_selftest_with_tools_runs_tool_checks(tmp_path: Path, capsys) -> None:
    # neither tool is configured; we expect FAIL lines but the test
    # itself should run them.
    args = _make_args(tmp_path, with_tools=True)
    selftest_cmd.run(args)
    out = capsys.readouterr().out
    assert "steamcmd_smoke" in out
    assert "bspsource_smoke" in out


def test_selftest_report_render_format() -> None:
    rep = selftest_cmd.SelftestReport()
    rep.add("alpha", True, "ok")
    rep.add("beta", False, "uh oh")
    rep.elapsed = 0.5
    text = rep.render()
    assert "[PASS] alpha" in text
    assert "[FAIL] beta" in text
    assert "Result: FAILED" in text


def test_selftest_report_ok_when_all_pass() -> None:
    rep = selftest_cmd.SelftestReport()
    rep.add("alpha", True)
    rep.add("beta", True)
    assert rep.ok is True


def test_selftest_report_not_ok_when_any_fail() -> None:
    rep = selftest_cmd.SelftestReport()
    rep.add("alpha", True)
    rep.add("beta", False, "nope")
    assert rep.ok is False


def test_selftest_synthetic_vmf_has_known_issues(tmp_path: Path) -> None:
    # the synthetic VMF must contain at least one finding the analyzer
    # is guaranteed to detect (otherwise the selftest provides no
    # signal).
    from csgo2cs2.analyzers.vmf import analyze_vmf

    analysis = analyze_vmf(selftest_cmd.SYNTHETIC_VMF)
    ids = {f.issue_id for f in analysis.findings}
    assert "skybox_unknown" in ids
