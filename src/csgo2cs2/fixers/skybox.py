# replace unsupported skybox values.

from __future__ import annotations

import re
from typing import Tuple

from ..analyzers.vmf import Finding
from . import base

SKYNAME_REPLACE_RE = re.compile(r'("skyname"\s*")([^"]+)(")', re.IGNORECASE)


# replace the first skyname value with the configured replacement.
# the analyzer chooses a mood-aware replacement (see pick_smart_skybox) and
# stuffs both the smart pick and the user's default into context, so the
# detail message can hint when we deviated from the default.
def fix_skybox(text: str, finding: Finding) -> Tuple[str, bool, str]:
    replacement = str(finding.context.get("replacement") or "").strip()
    if not replacement:
        return text, False, "no replacement provided"

    new_text, count = SKYNAME_REPLACE_RE.subn(
        lambda m: f"{m.group(1)}{replacement}{m.group(3)}",
        text,
        count=1,
    )
    if count == 0:
        return text, False, "no skyname key found"
    current = str(finding.context.get("current") or "<unknown>")
    default = str(finding.context.get("default") or "")
    detail = f"skyname `{current}` -> `{replacement}`"
    if default and default != replacement:
        detail += f" (mood-matched; default would have been `{default}`)"
    return new_text, True, detail


base.register("skybox_unknown", fix_skybox)
# the same fix logic applies to hdr-only skies; the analyzer still emits a
# distinct issue_id so the message can be specific.
base.register("skybox_hdr_only", fix_skybox)
