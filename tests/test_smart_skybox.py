# tests for the PR5 smart-skybox replacement table.
#
# the goals:
# - every replacement must be in WIKI_CONFIRMED_CS2_SKIES (no inventing
#   sky names that don't ship with cs2);
# - moods we care about (desert, urban, italian, etc.) must route to a
#   sane wiki-confirmed sky;
# - moods we don't have a confirmed equivalent for (night, snow, rural)
#   must fall through to the configured default rather than being
#   forced into a daytime urban sky;
# - the smart pick must propagate through the full analyze -> fix
#   pipeline so a `de_dust2_redux` map ends up with `sky_de_dust2` after
#   --fix, not the configured default.

from __future__ import annotations

from csgo2cs2.analyzers.vmf import (
    SKY_MOOD_RULES,
    WIKI_CONFIRMED_CS2_SKIES,
    analyze_vmf,
    pick_smart_skybox,
)
from csgo2cs2.fixers import apply_all  # noqa: F401  (registers fixers)


def _wrap_world(sky: str) -> str:
    return "world\n{\n" '\t"id" "1"\n' '\t"classname" "worldspawn"\n' f'\t"skyname" "{sky}"\n' "}\n"


def test_every_mood_replacement_is_wiki_confirmed():
    # the contract that lets us call this "mood-aware safe" — we never
    # invent a sky name that doesn't exist in cs2.
    bad = [
        (needle, repl) for needle, repl in SKY_MOOD_RULES if repl not in WIKI_CONFIRMED_CS2_SKIES
    ]
    assert bad == [], (
        f"SKY_MOOD_RULES must only map to wiki-confirmed cs2 skies; " f"these entries don't: {bad}"
    )


def test_pick_smart_skybox_routes_dust():
    assert pick_smart_skybox("sky_dust2") == "sky_de_dust2"
    assert pick_smart_skybox("sky_dust_") == "sky_de_dust2"
    assert pick_smart_skybox("sky_de_dust2_redux") == "sky_de_dust2"


def test_pick_smart_skybox_routes_office_to_cs_office():
    # mood "office" should route to the cs2 cs_office sky, not the
    # vertigo / urban sky.
    assert pick_smart_skybox("sky_office_hdr") == "sky_cs_office"
    assert pick_smart_skybox("sky_office_morning") == "sky_cs_office"


def test_pick_smart_skybox_routes_anubis():
    assert pick_smart_skybox("sky_anubis_egypt") == "sky_de_annubis"
    # the wiki keeps the csgo "annubis" misspelling
    assert pick_smart_skybox("sky_de_annubis") == "sky_de_annubis"


def test_pick_smart_skybox_routes_italian():
    assert pick_smart_skybox("sky_italy_morning") == "cs_italy_s2_skybox_2"
    assert pick_smart_skybox("sky_italia_summer") == "cs_italy_s2_skybox_2"


def test_pick_smart_skybox_routes_overpass():
    assert pick_smart_skybox("sky_de_overpass_v2") == "sky_de_overpass_01"
    assert pick_smart_skybox("euro_train_yard") == "sky_de_overpass_01"


def test_pick_smart_skybox_routes_jungle_temple():
    assert pick_smart_skybox("sky_aztec_temple") == "sky_hr_aztec_02_lighting"
    assert pick_smart_skybox("sky_ancient_ruin") == "sky_hr_aztec_02_lighting"
    assert pick_smart_skybox("sky_jungle_morning") == "sky_hr_aztec_02_lighting"


def test_pick_smart_skybox_falls_back_for_unmatched_moods():
    # we deliberately do NOT have a "night" mapping (no confirmed cs2
    # night sky exists in the wiki list). same for snow / rural.
    assert pick_smart_skybox("aim_redline_night", default_skybox="sky_cs_office") == "sky_cs_office"
    assert pick_smart_skybox("dz_blacksite_snow", default_skybox="sky_cs_office") == "sky_cs_office"
    assert (
        pick_smart_skybox("rural_woods", default_skybox="sky_de_overpass_01")
        == "sky_de_overpass_01"
    )


def test_pick_smart_skybox_handles_empty_and_garbage_input():
    assert pick_smart_skybox("", default_skybox="sky_cs_office") == "sky_cs_office"
    assert pick_smart_skybox("???", default_skybox="sky_cs_office") == "sky_cs_office"


def test_smart_skybox_propagates_through_fix_pipeline():
    # `de_dust2_redux`-style sky -> --fix should land on `sky_de_dust2`
    # not on whatever the default is.
    text = _wrap_world("sky_dust2_redux")
    a = analyze_vmf(text, default_skybox="sky_cs_office")
    new_text, results = apply_all(text, a.findings)
    applied_ids = {r.issue_id for r in results if r.applied}
    assert "skybox_unknown" in applied_ids
    assert "sky_de_dust2" in new_text
    assert "sky_dust2_redux" not in new_text


def test_smart_skybox_records_default_in_finding_context():
    # the analyzer should stash both the smart pick AND the default in the
    # finding context, so the fixer's detail message can say "mood-matched;
    # default would have been ...".
    text = _wrap_world("sky_office_hdr")
    a = analyze_vmf(text, default_skybox="sky_cs_office")
    hdr = next(f for f in a.findings if f.issue_id == "skybox_hdr_only")
    assert hdr.context["replacement"] == "sky_cs_office"
    assert hdr.context["default"] == "sky_cs_office"

    text2 = _wrap_world("sky_dust_old")
    a2 = analyze_vmf(text2, default_skybox="sky_de_overpass_01")
    sky2 = next(f for f in a2.findings if f.issue_id == "skybox_unknown")
    # mood-matched to dust2; default was overridden to overpass on the call.
    assert sky2.context["replacement"] == "sky_de_dust2"
    assert sky2.context["default"] == "sky_de_overpass_01"


def test_csgo_sky_dust_is_substituted_not_left_alone():
    # `sky_dust` is a CSGO-era skyname for the OG de_dust map. It used
    # to live in LEGACY_UNVERIFIED_SKIES (treated as known-good); now we
    # treat the wiki list as authoritative and substitute everything not
    # on it. `sky_dust` -> mood-matched `sky_de_dust2`.
    text = _wrap_world("sky_dust")
    a = analyze_vmf(text, default_skybox="sky_cs_office")
    new_text, results = apply_all(text, a.findings)
    applied_ids = {r.issue_id for r in results if r.applied}
    assert "skybox_unknown" in applied_ids
    assert "sky_de_dust2" in new_text
    assert '"skyname" "sky_dust"' not in new_text


def test_custom_skybox_skips_substitution():
    # If the BSP pakfile shipped a `materials/skybox/sky_dust*.vmt`,
    # the map author authored a custom skybox and we must NOT substitute.
    text = _wrap_world("sky_dust")
    a = analyze_vmf(
        text,
        default_skybox="sky_cs_office",
        custom_skies=["sky_dust"],
    )
    # no skybox_unknown finding because the analyzer treats sky_dust as
    # author-shipped custom.
    sky_findings = [
        f for f in a.findings if f.issue_id in ("skybox_unknown", "skybox_hdr_only")
    ]
    assert sky_findings == []


def test_custom_skybox_matches_with_face_suffix():
    # Pipeline scans staged/materials/skybox/ for face files like
    # `sky_mymap_up.vmt`. The analyzer is given the suffix-stripped form
    # `sky_mymap` to compare against worldspawn skyname.
    text = _wrap_world("sky_mymap")
    a = analyze_vmf(
        text,
        default_skybox="sky_cs_office",
        custom_skies=["sky_mymap_up", "sky_mymap"],
    )
    sky_findings = [
        f for f in a.findings if f.issue_id in ("skybox_unknown", "skybox_hdr_only")
    ]
    assert sky_findings == []
