# text-level cleanup of asset path key-value pairs.

from __future__ import annotations

import re
from typing import Tuple

from ..analyzers.vmf import Finding
from . import base

# directory name we rename `csgo/` subdirs to. matches the rename the
# pipeline does on the staged asset tree, so the rewritten .vmf paths
# resolve to actual files on disk.
CSGO_LEGACY_DIRNAME = "csgo_legacy"

# match `csgo/` or `csgo\` as a path segment (preceded by a path separator
# or string boundary). we anchor on the separators rather than a bare
# `csgo` to avoid mangling unrelated identifiers like `csgo_warmup_xyz`.
# the trailing separator is kept in the replacement so we just rewrite
# the `csgo` token.
_CSGO_SEGMENT_RE = re.compile(r"(?P<lead>(?:^|[\"\\/]))csgo(?P<trail>[\\/])")


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


# rewrite every `csgo/` (or `csgo\`) path segment under quoted asset values
# to `csgo_legacy/` (or `csgo_legacy\`).
#
# the analyzer emits one category-level finding per .vmf so a single fixer
# call is enough to cover every offending path. we scan the whole text but
# only inside quoted strings (matched by the leading `"` or path separator)
# to avoid touching prose elsewhere in the file. the matching pipeline
# rename of `staged/<bucket>/csgo/` -> `csgo_legacy/` keeps the rewritten
# paths resolvable against the staged content tree.
def fix_asset_path_csgo_subfolder(text: str, finding: Finding) -> Tuple[str, bool, str]:
    if "csgo" not in text.lower():
        return text, False, "no csgo segment in vmf"

    count = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{m.group('lead')}{CSGO_LEGACY_DIRNAME}{m.group('trail')}"

    new_text = _CSGO_SEGMENT_RE.sub(_sub, text)
    if count == 0:
        return text, False, "no `csgo/` path segment found"
    detail = f"renamed {count} `csgo/` path segment{'s' if count != 1 else ''} -> `{CSGO_LEGACY_DIRNAME}/`"
    return new_text, True, detail


base.register("asset_path_backslash", fix_asset_path_backslash)
base.register("asset_path_csgo_subfolder", fix_asset_path_csgo_subfolder)
