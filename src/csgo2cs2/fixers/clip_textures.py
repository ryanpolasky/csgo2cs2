# clip-texture fixer.
#
# the cs2 importer drops `"material" "<path>"` pairs whose value isn't a
# `tools/toolsclip*`-prefixed reference. losing the brush is fine
# (toolsclip is a no-render collision-only material in both engines), but
# leaving the original path in the .vmf means the brush silently
# disappears with no breadcrumb. the fixer rewrites the value to
# `tools/toolsclip` so the .vmf at least documents that this was a clip
# brush in s1.

from __future__ import annotations

from typing import Tuple

from ..analyzers.vmf import Finding
from . import base

# what we rewrite custom clip refs to. tools/toolsclip is the importer's
# recognized default and the broadest-applicable clip in cs2.
DEFAULT_CLIP = "tools/toolsclip"


# the analyzer fires one finding per offending material ref, so we
# rewrite the single quoted value the finding identified. anchored on
# the full `"material" "..."` form to avoid touching unrelated
# identifiers that happen to contain "clip".
def fix_texture_clip_custom(text: str, finding: Finding) -> Tuple[str, bool, str]:
    old = str(finding.context.get("path") or "")
    if not old:
        return text, False, "no path in finding context"
    if old == DEFAULT_CLIP:
        return text, False, "already the default clip"

    needle = f'"material" "{old}"'
    replacement = f'"material" "{DEFAULT_CLIP}"'
    if needle in text:
        text = text.replace(needle, replacement, 1)
        return text, True, f"`{old}` -> `{DEFAULT_CLIP}`"

    # case-insensitive fallback: vmf keys are sometimes "Material"; the
    # analyzer's regex uses re.IGNORECASE so we mirror that here.
    lo_needle = needle.lower()
    lo_text = text.lower()
    idx = lo_text.find(lo_needle)
    if idx == -1:
        return text, False, "clip reference not found in vmf"
    text = text[:idx] + replacement + text[idx + len(needle) :]
    return text, True, f"`{old}` -> `{DEFAULT_CLIP}`"


base.register("texture_clip_custom", fix_texture_clip_custom)
