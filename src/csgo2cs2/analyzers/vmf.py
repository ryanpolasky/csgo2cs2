# vmf analysis with no file writes.
#
# pitfall sources documented inline; central attribution lives in
# README.md "Prior art & attributions".

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Set

# known cs2 skyboxes used as safe replacements. covers the official cs2 ship-in
# set; not exhaustive of community skies. override via Config.cs2_sky_list.
KNOWN_CS2_SKIES: Set[str] = {
    "sky_day01_01",
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
    skyname: Optional[str] = None
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


# run every vmf check we currently support.
def analyze_vmf(
    text: str,
    default_skybox: str = "sky_day01_01",
    cs2_sky_list: Optional[Iterable[str]] = None,
    extra_unsupported_entities: Optional[Iterable[str]] = None,
) -> VmfAnalysis:
    analysis = VmfAnalysis()
    skies = set(cs2_sky_list) if cs2_sky_list is not None else KNOWN_CS2_SKIES
    unsupported = set(UNSUPPORTED_ENTITIES) | set(extra_unsupported_entities or [])

    # check skybox compatibility
    sky_match = SKYNAME_RE.search(text)
    if sky_match:
        skyname = sky_match.group(1)
        analysis.skyname = skyname
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
                    context={"current": skyname, "replacement": default_skybox},
                )
            )
        elif skyname not in skies:
            analysis.findings.append(
                Finding(
                    issue_id="skybox_unknown",
                    severity="warn",
                    message=f"Skybox `{skyname}` is not a known CS2 sky.",
                    fixable=True,
                    context={"current": skyname, "replacement": default_skybox},
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
                    fixable=False,
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
                fixable=False,
                context={"count": light_env_count},
            )
        )

    # custom clip textures get silently dropped by the importer
    for ref in _CLIP_REF_RE.findall(text):
        if not _is_tools_clip(ref):
            analysis.findings.append(
                Finding(
                    issue_id="texture_clip_custom",
                    severity="warn",
                    message=(
                        f"Custom clip texture `{ref}` will not survive the import; "
                        "replace with `tools/toolsclip` or `tools/toolsplayerclip` in s1 hammer."
                    ),
                    fixable=False,
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
                    fixable=False,
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
                    fixable=False,
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
