# vmf analysis with no file writes.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# known cs2 skyboxes used as safe replacements.
KNOWN_CS2_SKIES = {
    "sky_day01_01",
    "sky_csgo_cloudy01",
    "sky_csgo_night02",
}

# source 1 entities that often break cs2 import.
UNSUPPORTED_ENTITIES = {
    "env_cascade_light",
    "env_tonemap_controller_ghosting",
    "info_overlay_transition",
}

SKYNAME_RE = re.compile(r'"skyname"\s*"([^"]+)"', re.IGNORECASE)
CLASSNAME_RE = re.compile(r'"classname"\s*"([^"]+)"', re.IGNORECASE)


@dataclass
class Finding:
    issue_id: str
    severity: str
    message: str
    fixable: bool = False
    context: Dict[str, object] = field(default_factory=dict)


@dataclass
class VmfAnalysis:
    findings: List[Finding] = field(default_factory=list)
    total_entities: int = 0
    class_counts: Dict[str, int] = field(default_factory=dict)
    skyname: Optional[str] = None


# run every vmf check we currently support.
def analyze_vmf(text: str, default_skybox: str = "sky_day01_01") -> VmfAnalysis:
    analysis = VmfAnalysis()

    # check skybox compatibility
    sky_match = SKYNAME_RE.search(text)
    if sky_match:
        skyname = sky_match.group(1)
        analysis.skyname = skyname
        if skyname not in KNOWN_CS2_SKIES:
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
        if cls in UNSUPPORTED_ENTITIES:
            analysis.findings.append(
                Finding(
                    issue_id="entity_unsupported",
                    severity="warn",
                    message=f"Unsupported entity `{cls}` x{class_counts[cls]}",
                    fixable=True,
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

    return analysis
