# tests for the vmf analyzer.

from csgo2cs2.analyzers.vmf import KNOWN_CS2_SKIES, analyze_vmf

VMF_MINIMAL = """\
versioninfo
{
\t"editorversion" "400"
}
world
{
\t"id" "1"
\t"classname" "worldspawn"
\t"skyname" "__SKY__"
}
entity
{
\t"id" "10"
\t"classname" "info_player_terrorist"
}
entity
{
\t"id" "11"
\t"classname" "info_player_counterterrorist"
}
"""


def _vmf(sky="sky_csgo_night02", extras: str = "") -> str:
    return VMF_MINIMAL.replace("__SKY__", sky) + extras


def test_known_cs2_sky_produces_no_skybox_finding():
    text = _vmf(sky=next(iter(KNOWN_CS2_SKIES)))
    a = analyze_vmf(text)
    assert all(f.issue_id != "skybox_unknown" for f in a.findings)


def test_unknown_sky_is_flagged_and_fixable():
    text = _vmf(sky="sky_csgo_someoldsky")
    a = analyze_vmf(text, default_skybox="sky_day01_01")
    sky_findings = [f for f in a.findings if f.issue_id == "skybox_unknown"]
    assert len(sky_findings) == 1
    f = sky_findings[0]
    assert f.fixable
    assert f.context["current"] == "sky_csgo_someoldsky"
    assert f.context["replacement"] == "sky_day01_01"


def test_missing_skyname_is_flagged_not_fixable():
    text = """\
world
{
\t"id" "1"
\t"classname" "worldspawn"
}
"""
    a = analyze_vmf(text)
    findings = [f for f in a.findings if f.issue_id == "skybox_missing"]
    assert len(findings) == 1
    assert findings[0].fixable is False


def test_unsupported_entity_flagged():
    extra = """\
entity
{
\t"id" "20"
\t"classname" "env_cascade_light"
}
"""
    text = _vmf() + extra
    a = analyze_vmf(text)
    cls_findings = [
        f
        for f in a.findings
        if f.issue_id == "entity_unsupported" and f.context.get("classname") == "env_cascade_light"
    ]
    assert len(cls_findings) == 1
    assert cls_findings[0].fixable
    assert cls_findings[0].context["count"] == 1


def test_required_spawns_detected():
    a = analyze_vmf(_vmf())
    missing = [f for f in a.findings if f.issue_id == "missing_spawn"]
    assert missing == []  # both spawns present


def test_missing_required_spawns_flagged():
    text = """\
world
{
\t"classname" "worldspawn"
\t"skyname" "sky_day01_01"
}
"""
    a = analyze_vmf(text)
    missing = sorted(f.context["classname"] for f in a.findings if f.issue_id == "missing_spawn")
    assert missing == ["info_player_counterterrorist", "info_player_terrorist"]


def test_total_entities_and_class_counts():
    a = analyze_vmf(_vmf())
    # worldspawn plus 2 entities equals 3 classnames
    assert a.total_entities == 3
    assert a.class_counts["info_player_terrorist"] == 1
    assert a.class_counts["info_player_counterterrorist"] == 1
