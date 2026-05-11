# vmf analysis with no file writes.
#
# pitfall sources documented inline; central attribution lives in
# README.md "Prior art & attributions".

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Set, Tuple

# wiki-confirmed cs2 skies, as documented at
# https://developer.valvesoftware.com/wiki/Counter-Strike_2_Workshop_Tools/CS2_Sky_List
# the wiki page is marked WIP so this is the documented subset, not
# necessarily the entire shipped sky set. each entry is the skybox material
# (env_sky) name from a shipping cs2 map.
WIKI_CONFIRMED_CS2_SKIES: Set[str] = {
    "s2_de_inferno_sky01",  # de_inferno (mediterranean / coastal)
    "sky_de_mirage",  # de_mirage (desert / arabian)
    "sky_de_annubis",  # de_anubis (egyptian / desert) — note the wiki spelling
    "sky_de_vertigo",  # de_vertigo (urban high-altitude)
    "sky_de_nuke",  # de_nuke (industrial / cloudy)
    "sky_cs_office",  # cs_office (overcast urban)
    "cs_italy_s2_skybox_2",  # cs_italy (italian / mediterranean)
    "sky_hr_aztec_02_lighting",  # de_ancient (jungle / temple)
    "sky_de_dust2",  # de_dust2 (desert)
    "sky_de_overpass_01",  # de_overpass (european urban)
}

# legacy / unverified skies kept in `KNOWN_CS2_SKIES` for backward
# compatibility with users who configured `cs2_sky_list` against earlier
# versions of csgo2cs2 (pre-PR5). these names were ported from csgo and
# may or may not actually exist in cs2; we don't shrink the set so we
# don't surface false-positive `skybox_unknown` findings on configs that
# previously passed clean.
#
# `sky_day01_01` was the old default_skybox value and is intentionally
# omitted: it doesn't appear in the wiki sky list nor in any csgo sky
# manifest we can find. the new default is `sky_cs_office`.
LEGACY_UNVERIFIED_SKIES: Set[str] = {
    "sky_csgo_cloudy01",
    "sky_csgo_night02",
    "sky_csgo_night02b",
    "sky_dust",
    "sky_l4d_rural02_ldr",
    "sky_lunacy",
    "sky_urb_alley01",
    "sky_urb_embassy01",
    "sky_venice",
}

# the union is what `analyze` accepts as a "known" sky. if a vmf already
# names one of these, we don't flag `skybox_unknown`. override via
# Config.cs2_sky_list.
KNOWN_CS2_SKIES: Set[str] = WIKI_CONFIRMED_CS2_SKIES | LEGACY_UNVERIFIED_SKIES

# csgo skies that are HDR-only (no LDR fallback) historically caused the
# importer to fail. flagging them separately so users get a targeted message.
# source: andreaskeller96/cs2-import-scripts pitfall list ("hdr skybox -> import
# WILL FAIL").
HDR_ONLY_SKIES: Set[str] = {
    "sky_borealis01_hdr",
    "sky_csgo_cloudy01_hdr",
    "sky_csgo_night02_hdr",
    "sky_dust_hdr",
    "sky_office_hdr",
    "sky_baggage_hdr",
}

# mood-aware skybox replacement table. matched as substrings against the
# original csgo skyname (case-insensitive). first hit wins, top-down. used
# by the skybox fixer so a `de_dust2_redux` map gets a desert sky and a
# `cs_office_remix` map gets the cs office sky, instead of everything
# ending up under the same `default_skybox` value.
#
# IMPORTANT: every replacement here MUST be in WIKI_CONFIRMED_CS2_SKIES.
# unverified csgo-era sky names (sky_day01_01, sky_dust, etc.) are kept in
# the LEGACY_UNVERIFIED_SKIES set for backward compat but never used as
# auto-replacements, since we can't be sure they ship with cs2.
#
# moods with no clean wiki match (snow, night, rural) intentionally fall
# through to default_skybox rather than picking a random urban sky.
SKY_MOOD_RULES: List[Tuple[str, str]] = [
    # csgo desert maps (de_dust2 / similar) -> cs2 dust2 sky
    ("dust2", "sky_de_dust2"),
    ("dust_", "sky_de_dust2"),
    ("dust.", "sky_de_dust2"),
    # arabian / mirage-style
    ("mirage", "sky_de_mirage"),
    ("arabia", "sky_de_mirage"),
    ("desert", "sky_de_mirage"),
    ("sahara", "sky_de_mirage"),
    # egyptian / anubis temple
    ("anubis", "sky_de_annubis"),
    ("annubis", "sky_de_annubis"),  # csgo mis-spelling carries through
    ("egypt", "sky_de_annubis"),
    ("pharaoh", "sky_de_annubis"),
    # mediterranean / coastal -> inferno sky
    ("inferno", "s2_de_inferno_sky01"),
    ("coast", "s2_de_inferno_sky01"),
    ("mediterranean", "s2_de_inferno_sky01"),
    # italian -> cs_italy sky
    ("italy", "cs_italy_s2_skybox_2"),
    ("italia", "cs_italy_s2_skybox_2"),
    # european urban (overpass-style)
    ("overpass", "sky_de_overpass_01"),
    ("euro", "sky_de_overpass_01"),
    # office / embassy / interior overcast urban
    ("office", "sky_cs_office"),
    ("embassy", "sky_cs_office"),
    ("station", "sky_cs_office"),
    # urban / city -> cs2 high-altitude vertigo sky
    ("vertigo", "sky_de_vertigo"),
    ("downtown", "sky_de_vertigo"),
    ("urban", "sky_de_vertigo"),
    ("urb_", "sky_de_vertigo"),
    ("alley", "sky_de_vertigo"),
    ("city", "sky_de_vertigo"),
    # industrial / nuke
    ("nuke", "sky_de_nuke"),
    ("industrial", "sky_de_nuke"),
    ("factory", "sky_de_nuke"),
    # jungle / temple / aztec / ancient
    ("aztec", "sky_hr_aztec_02_lighting"),
    ("ancient", "sky_hr_aztec_02_lighting"),
    ("jungle", "sky_hr_aztec_02_lighting"),
    ("temple", "sky_hr_aztec_02_lighting"),
    ("ruins", "sky_hr_aztec_02_lighting"),
    # NOTE: night / snow / rural / forest moods have no documented cs2 sky
    # equivalent. we let them fall through to cfg.default_skybox rather
    # than mapping them to an obviously-wrong daytime sky.
]

# source 1 entities that don't survive the cs2 import cleanly.
# additive: cfg.extra_unsupported_entities is merged at analyze-time.
UNSUPPORTED_ENTITIES: Set[str] = {
    # csgo / source 1 specific lighting / postfx
    "env_cascade_light",
    "env_tonemap_controller_ghosting",
    "info_overlay_transition",
    "env_screenoverlay",
    "info_no_dynamic_shadow",
    # legacy spawn / dev entities
    "info_player_logo",
    "point_devshot_camera",
    # source 1 ladder system (cs2 has its own)
    "func_simpleladder",
    # debug / server-only entities that get stripped or break imports
    "point_servercommand",
    "point_clientcommand",
}

# legacy team spawns from older source titles that occasionally appear
# in csgo ports of older maps. flagged separately because the fix is
# usually replace-with-info_player_terrorist/counterterrorist, not delete.
LEGACY_SPAWN_ENTITIES: Set[str] = {
    "info_player_axis",
    "info_player_allies",
    "info_player_combine",
    "info_player_rebel",
    "info_player_start",
}

# entities source 2 / cs2 deprecates or replaces. these survive the import
# but are dead weight afterward; we surface them as info findings with a
# "what to do" pointer in the explain registry.
# sources:
#   - ata4/bspsrc README "Limitations and known bugs"
#     (func_instance, func_viscluster, info_no_dynamic_shadow consumed by vbsp)
#   - valve developer wiki cs2 visibility / fog notes
DEPRECATED_S2_ENTITIES: Set[str] = {
    "func_areaportal",
    "func_areaportalwindow",
    "func_occluder",
    "func_viscluster",
    "env_fog_controller",
    "color_correction",
    "color_correction_volume",
    "shadow_control",
    "env_sun",
    "env_lightglow",
    "func_lod",
    "func_dustmotes",
    "func_smokevolume",
    "logic_choreographed_scene",
    "scripted_sequence",
    "point_template",
}

# entities that need user action after import (cubemaps, soundscapes, etc.)
# we emit a single info per category if any are present, plus a category-level
# "manual_rebuild_*" finding so the explain registry can surface guidance.
NEEDS_REBUILD_ENTITIES: Dict[str, str] = {
    "env_cubemap": "manual_rebuild_cubemaps",
    "env_soundscape": "manual_review_soundscapes",
    "env_soundscape_proxy": "manual_review_soundscapes",
    "env_soundscape_triggerable": "manual_review_soundscapes",
    "ambient_generic": "manual_review_soundscapes",
    "info_overlay": "manual_review_overlays",
}

SKYNAME_RE = re.compile(r'"skyname"\s*"([^"]+)"', re.IGNORECASE)
CLASSNAME_RE = re.compile(r'"classname"\s*"([^"]+)"', re.IGNORECASE)
INSTANCE_FILE_RE = re.compile(r'"file"\s*"([^"]+\.vmf)"', re.IGNORECASE)

# value of any vmf key that looks like an asset path. matches material/model/
# sound/file references. catches values that contain forward slashes plus a
# common asset extension or known materials root.
_ASSET_KEYS = (
    "material",
    "texture",
    "model",
    "sound",
    "image",
    "filename",
    "instancefile",
    "noisetexture",
    "vmt",
    "vtf",
)
_ASSET_PAIR_RE = re.compile(
    r'"(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)"\s*"(?P<val>[^"\n]+)"',
)
_ASSET_EXT_RE = re.compile(
    r"\.(vmt|vtf|mdl|wav|mp3|vmf|vsndevts|vpcf)\b",
    re.IGNORECASE,
)
_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")  # windows drive-letter paths

# first path segment named "csgo". per upstream pitfall list, having a
# folder literally named "csgo" anywhere in your asset tree breaks the
# importer because the script special-cases the csgo install dir.
_CSGO_SUBFOLDER_RE = re.compile(r"(?:^|[\\/])csgo[\\/]", re.IGNORECASE)

# clip-style texture references. tools/* clips are recognized by the importer;
# anything else with "clip" in the name is a custom clip and gets dropped.
# source: andreaskeller96 pitfall list ("Custom clip textures will not be
# imported").
_CLIP_REF_RE = re.compile(
    r'"material"\s*"([^"\n]*?clip[^"\n]*)"',
    re.IGNORECASE,
)
_TOOLS_CLIP_PREFIXES = (
    "tools/toolsclip",
    "tools/toolsplayerclip",
    "tools/toolsnpcclip",
    "tools/toolsgrenadeclip",
    "tools/clip",
)


@dataclass
class Finding:
    issue_id: str
    severity: str
    message: str
    fixable: bool = False
    context: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class VmfAnalysis:
    findings: List[Finding] = field(default_factory=list)
    total_entities: int = 0
    class_counts: Dict[str, int] = field(default_factory=dict)
    skyname: str | None = None
    asset_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "skyname": self.skyname,
            "total_entities": self.total_entities,
            "class_counts": self.class_counts,
            "asset_refs": self.asset_refs,
            "findings": [f.to_dict() for f in self.findings],
        }


# detect asset-like values in a vmf body so the importer doesn't fail at
# runtime on broken paths. returns the raw values, deduped, sorted.
def _extract_asset_refs(text: str) -> List[str]:
    refs: Set[str] = set()
    for m in _ASSET_PAIR_RE.finditer(text):
        key = m.group("key").lower()
        val = m.group("val").strip()
        if not val:
            continue
        is_asset_key = key in _ASSET_KEYS or key.endswith("texture")
        looks_like_path = ("/" in val or "\\" in val) and bool(_ASSET_EXT_RE.search(val))
        if is_asset_key or looks_like_path:
            refs.add(val)
    return sorted(refs)


def _is_tools_clip(path: str) -> bool:
    norm = path.replace("\\", "/").lower()
    return any(norm.startswith(p) for p in _TOOLS_CLIP_PREFIXES)


# pick a mood-aware cs2 replacement for a csgo sky name. returns the user's
# default_skybox unchanged when no mood rule matches. exported because the
# fixer + tests + the explain registry all need to agree on the mapping.
def pick_smart_skybox(skyname: str, default_skybox: str = "sky_cs_office") -> str:
    s = (skyname or "").lower()
    for needle, replacement in SKY_MOOD_RULES:
        if needle in s:
            return replacement
    return default_skybox


# run every vmf check we currently support.
def analyze_vmf(
    text: str,
    default_skybox: str = "sky_cs_office",
    cs2_sky_list: Iterable[str] | None = None,
    extra_unsupported_entities: Iterable[str] | None = None,
) -> VmfAnalysis:
    analysis = VmfAnalysis()
    skies = set(cs2_sky_list) if cs2_sky_list is not None else KNOWN_CS2_SKIES
    unsupported = set(UNSUPPORTED_ENTITIES) | set(extra_unsupported_entities or [])

    # check skybox compatibility
    sky_match = SKYNAME_RE.search(text)
    if sky_match:
        skyname = sky_match.group(1)
        analysis.skyname = skyname
        smart = pick_smart_skybox(skyname, default_skybox=default_skybox)
        if skyname in HDR_ONLY_SKIES:
            analysis.findings.append(
                Finding(
                    issue_id="skybox_hdr_only",
                    severity="error",
                    message=(
                        f"Skybox `{skyname}` is HDR-only; the cs2 importer fails "
                        "without an LDR fallback. Replace with a known cs2 sky."
                    ),
                    fixable=True,
                    context={
                        "current": skyname,
                        "replacement": smart,
                        "default": default_skybox,
                    },
                )
            )
        elif skyname not in skies:
            analysis.findings.append(
                Finding(
                    issue_id="skybox_unknown",
                    severity="warn",
                    message=f"Skybox `{skyname}` is not a known CS2 sky.",
                    fixable=True,
                    context={
                        "current": skyname,
                        "replacement": smart,
                        "default": default_skybox,
                    },
                )
            )
    else:
        analysis.findings.append(
            Finding(
                issue_id="skybox_missing",
                severity="warn",
                message="No skyname found in worldspawn.",
                fixable=False,  # inserting this safely is fragile, so manual for now
                context={"replacement": default_skybox},
            )
        )

    # count classnames so later checks don't each re-parse the file
    class_counts: Dict[str, int] = {}
    for cls in CLASSNAME_RE.findall(text):
        class_counts[cls] = class_counts.get(cls, 0) + 1
    analysis.class_counts = class_counts
    analysis.total_entities = sum(class_counts.values())

    # flag unsupported entities before import
    for cls in sorted(class_counts):
        if cls in unsupported:
            analysis.findings.append(
                Finding(
                    issue_id="entity_unsupported",
                    severity="warn",
                    message=f"Unsupported entity `{cls}` x{class_counts[cls]}",
                    fixable=True,
                    context={"classname": cls, "count": class_counts[cls]},
                )
            )

    # legacy spawn entities are recoverable but aren't valid cs spawns
    for cls in sorted(class_counts):
        if cls in LEGACY_SPAWN_ENTITIES:
            analysis.findings.append(
                Finding(
                    issue_id="entity_legacy_spawn",
                    severity="warn",
                    message=(
                        f"Legacy spawn entity `{cls}` x{class_counts[cls]}; "
                        "cs2 wants info_player_terrorist / info_player_counterterrorist."
                    ),
                    fixable=False,
                    context={"classname": cls, "count": class_counts[cls]},
                )
            )

    # source 2 deprecated / replaced entities. info-severity because the
    # import succeeds; the user just needs to know they're dead weight.
    for cls in sorted(class_counts):
        if cls in DEPRECATED_S2_ENTITIES:
            analysis.findings.append(
                Finding(
                    issue_id="entity_deprecated_s2",
                    severity="info",
                    message=(
                        f"`{cls}` x{class_counts[cls]} is deprecated/replaced in CS2; "
                        "review after import."
                    ),
                    # `--fix` strips them since they're dead weight in cs2.
                    # findings stay info-severity (they don't block import).
                    fixable=True,
                    context={"classname": cls, "count": class_counts[cls]},
                )
            )

    # rebuild reminders driven by entity presence (one finding per category)
    rebuild_emitted: Set[str] = set()
    for cls, rebuild_id in NEEDS_REBUILD_ENTITIES.items():
        if cls not in class_counts or rebuild_id in rebuild_emitted:
            continue
        rebuild_emitted.add(rebuild_id)
        analysis.findings.append(
            Finding(
                issue_id=rebuild_id,
                severity="info",
                message=_REBUILD_MESSAGES[rebuild_id],
                fixable=False,
                context={"trigger": cls},
            )
        )

    # need spawn points for a playable cs map
    required_modes = {
        "info_player_counterterrorist": "CT spawn",
        "info_player_terrorist": "T spawn",
    }
    for ent, label in required_modes.items():
        if ent not in class_counts:
            analysis.findings.append(
                Finding(
                    issue_id="missing_spawn",
                    severity="warn",
                    message=f"No {label} ({ent}) found.",
                    fixable=False,
                    context={"classname": ent, "label": label},
                )
            )

    # multiple light_environment entities are broken in cs2's vrad
    light_env_count = class_counts.get("light_environment", 0)
    if light_env_count > 1:
        analysis.findings.append(
            Finding(
                issue_id="light_environment_count",
                severity="warn",
                message=(
                    f"{light_env_count} `light_environment` entities found; "
                    "cs2 expects exactly one."
                ),
                fixable=True,  # fix = keep the first, delete the rest
                context={"count": light_env_count},
            )
        )

    # custom clip textures get silently dropped by the importer; --fix
    # rewrites them to `tools/toolsclip` (the importer-recognized default)
    # so the .vmf at least documents what those brushes were before.
    for ref in _CLIP_REF_RE.findall(text):
        if not _is_tools_clip(ref):
            analysis.findings.append(
                Finding(
                    issue_id="texture_clip_custom",
                    severity="warn",
                    message=(
                        f"Custom clip texture `{ref}` will not survive the import; "
                        "auto-fix rewrites it to `tools/toolsclip`."
                    ),
                    fixable=True,
                    context={"path": ref},
                )
            )

    # asset reference scan: spaces / drive-letter / backslashes blow up the
    # importer or break case-sensitive filesystems.
    asset_refs = _extract_asset_refs(text)
    analysis.asset_refs = asset_refs
    csgo_subfolder_emitted = False
    for ref in asset_refs:
        if " " in ref:
            analysis.findings.append(
                Finding(
                    issue_id="asset_path_space",
                    severity="error",
                    message=f"Asset path `{ref}` contains a space; the cs2 importer fails on these.",
                    fixable=False,
                    context={"path": ref},
                )
            )
        if _ABS_PATH_RE.match(ref):
            analysis.findings.append(
                Finding(
                    issue_id="asset_path_absolute",
                    severity="error",
                    message=f"Absolute path `{ref}`; the importer needs game-relative paths.",
                    fixable=False,
                    context={"path": ref},
                )
            )
        # backslashes break on case-sensitive filesystems and the cs2 vfs
        if "\\" in ref:
            analysis.findings.append(
                Finding(
                    issue_id="asset_path_backslash",
                    severity="warn",
                    message=(
                        f"Asset path `{ref}` uses backslashes; convert to forward "
                        "slashes for cross-platform safety."
                    ),
                    fixable=True,  # safe text replace inside the quoted value
                    context={"path": ref},
                )
            )
        # custom subfolder named "csgo" trips the importer's path heuristics
        if not csgo_subfolder_emitted and _CSGO_SUBFOLDER_RE.search(ref):
            csgo_subfolder_emitted = True
            analysis.findings.append(
                Finding(
                    issue_id="asset_path_csgo_subfolder",
                    severity="warn",
                    message=(
                        f"Asset path `{ref}` lives under a `csgo/` subfolder; the cs2 "
                        "importer special-cases that name and may resolve assets to "
                        "the install dir instead of yours."
                    ),
                    fixable=True,  # PR5: bulk-rename to `csgo_legacy/`
                    context={"path": ref},
                )
            )

    return analysis


# messages for the manual-rebuild category findings.
_REBUILD_MESSAGES: Dict[str, str] = {
    "manual_rebuild_cubemaps": (
        "env_cubemap entities present; run `buildcubemaps` in cs2 after import "
        "to bake new envmaps. CSGO cubemaps don't transfer."
    ),
    "manual_review_soundscapes": (
        "soundscape / ambient entities present; cs2 uses .vsndevts soundscape "
        "scripts instead of CSGO's scripts/soundscapes_*.txt. Re-author after import."
    ),
    "manual_review_overlays": (
        "info_overlay entities present; overlays often need re-positioning after "
        "the cs2 import re-bakes brush UVs."
    ),
}
