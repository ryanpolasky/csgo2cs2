# vmf analysis with no file writes.

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
HDR_ONLY_SKIES: Set[str] = {
    "sky_borealis01_hdr",
    "sky_csgo_cloudy01_hdr",
    "sky_csgo_night02_hdr",
    "sky_dust",  # csgo dust2 sky historically ldr-only in some installs
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

SKYNAME_RE = re.compile(r'"skyname"\s*"([^"]+)"', re.IGNORECASE)
CLASSNAME_RE = re.compile(r'"classname"\s*"([^"]+)"', re.IGNORECASE)

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

    # asset reference scan: spaces / drive-letter / backslashes blow up the
    # importer or break case-sensitive filesystems.
    asset_refs = _extract_asset_refs(text)
    analysis.asset_refs = asset_refs
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

    return analysis
