# replace unsupported skybox values.

from __future__ import annotations

import re
from typing import Tuple

from ..analyzers.vmf import Finding
from . import base

SKYNAME_REPLACE_RE = re.compile(r'("skyname"\s*")([^"]+)(")', re.IGNORECASE)


# replace the first skyname value with the configured replacement.
def fix_skybox(text: str, finding: Finding) -> Tuple[str, bool, str]:
    replacement = str(finding.context.get("replacement") or "").strip()
    if not replacement:
        return text, False, "no replacement provided"

    new_text, count = SKYNAME_REPLACE_RE.subn(
        lambda m: f'{m.group(1)}{replacement}{m.group(3)}',
        text,
        count=1,
    )
    if count == 0:
        return text, False, "no skyname key found"
    current = str(finding.context.get("current") or "<unknown>")
    return new_text, True, f"skyname `{current}` -> `{replacement}`"


base.register("skybox_unknown", fix_skybox)
