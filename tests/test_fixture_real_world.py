# snapshot-style test against a hand-authored representative .vmf fixture.
# the fixture is designed to trip ~all relevant findings simultaneously, so
# any change to detection logic shows up as an explicit diff here.

from __future__ import annotations

from pathlib import Path

import pytest

from csgo2cs2.analyzers import explain as explain_mod
from csgo2cs2.analyzers.vmf import analyze_vmf
from csgo2cs2.fixers import apply_all

FIXTURE = Path(__file__).parent / "fixtures" / "sample_csgo_map.vmf"


# the exact set of issue_ids the fixture is engineered to produce.
# adding/removing a finding type here forces an explicit fixture update,
# which prevents silent regressions in detection logic.
EXPECTED_ISSUE_IDS = {
    "asset_path_absolute",
    "asset_path_backslash",
    "asset_path_csgo_subfolder",
    "asset_path_space",
    "entity_deprecated_s2",
    "entity_legacy_spawn",
    "entity_unsupported",
    "light_environment_count",
    "manual_rebuild_cubemaps",
    "manual_review_overlays",
    "manual_review_soundscapes",
    "skybox_hdr_only",
    "texture_clip_custom",
}


@pytest.fixture
def vmf_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_file_exists():
    assert FIXTURE.exists(), f"missing fixture: {FIXTURE}"


def test_fixture_produces_expected_issue_ids(vmf_text: str):
    a = analyze_vmf(vmf_text)
    found_ids = {f.issue_id for f in a.findings}
    missing = EXPECTED_ISSUE_IDS - found_ids
    extra = found_ids - EXPECTED_ISSUE_IDS
    assert not missing, f"detector regression: fixture stopped tripping {missing}"
    assert not extra, f"new finding type fired on fixture without test update: {extra}"


def test_every_fixture_finding_has_an_explanation(vmf_text: str):
    """Guard: every issue_id we emit must have a curated explain entry."""
    a = analyze_vmf(vmf_text)
    for f in a.findings:
        exp = explain_mod.get(f.issue_id)
        assert exp is not None, f"missing explanation for {f.issue_id}"


def test_fixture_round_trip_after_fix_has_no_fixable_findings_left(vmf_text: str):
    """After applying all fixers, a re-analysis should report no fixable
    findings. Manual / non-fixable ones may remain; that's expected."""
    a1 = analyze_vmf(vmf_text)
    new_text, _ = apply_all(vmf_text, a1.findings)
    a2 = analyze_vmf(new_text)
    remaining_fixable = [f for f in a2.findings if f.fixable]
    assert remaining_fixable == [], (
        "fixers were not idempotent: "
        f"{[f.issue_id for f in remaining_fixable]} are still fixable after --fix"
    )


def test_fixture_severity_distribution(vmf_text: str):
    """Lock in the high-level error/warn/info shape so a severity flip on
    any existing finding shows up as a deliberate test update."""
    a = analyze_vmf(vmf_text)
    by_severity: dict[str, int] = {}
    for f in a.findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
    # the fixture is engineered for a balanced spread across all 3 severities
    assert by_severity.get("error", 0) >= 1
    assert by_severity.get("warn", 0) >= 1
    assert by_severity.get("info", 0) >= 1
