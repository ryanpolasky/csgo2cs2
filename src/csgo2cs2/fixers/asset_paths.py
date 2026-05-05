# text-level cleanup of asset path key-value pairs.

from __future__ import annotations

from typing import Tuple

from ..analyzers.vmf import Finding
from . import base


# replace backslashes with forward slashes inside the matched quoted value.
# we anchor the replace on the full quoted form (`"<path>"`) to avoid touching
# substring matches elsewhere in the file (e.g. unrelated comments).
def fix_asset_path_backslash(text: str, finding: Finding) -> Tuple[str, bool, str]:
    old = str(finding.context.get("path") or "")
    if not old or "\\" not in old:
        return text, False, "no backslashes"
    new = old.replace("\\", "/")
    needle = f'"{old}"'
    if needle not in text:
        # rare: the analyzer matched but the .vmf was edited between analyze
        # and fix. fall back to a single global replace.
        if old not in text:
            return text, False, "path not found in vmf"
        text = text.replace(old, new, 1)
    else:
        text = text.replace(needle, f'"{new}"', 1)
    return text, True, f"`{old}` -> `{new}`"


base.register("asset_path_backslash", fix_asset_path_backslash)
