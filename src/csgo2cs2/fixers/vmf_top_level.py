# normalize top-level VMF blocks so Valve's source1import CVMFtoVMAP
# doesn't bail with `Missing a required top-level key.`
#
# bspsource's decompiled output is valid s1 vmf but routinely omits
# `viewsettings`, and occasionally `cameras` / `cordon` -- the s2 importer
# requires at minimum `versioninfo`, `visgroups`, `viewsettings`, and
# `world`. this fixer is a no-op when every required block is already
# present, otherwise it inserts a minimal default block in the canonical
# position so the importer can construct its map document.

from __future__ import annotations

import re
from typing import Tuple

from ..analyzers.vmf import Finding
from . import base

# blocks that CVMFtoVMAP requires to be present at the top level. order
# matters because we insert in this sequence; missing blocks are added
# *before* the first `world`/`entity` block so they show up where Hammer
# would have written them. `world` itself is also required but if it's
# missing, the vmf is fundamentally broken and we don't try to fabricate
# a worldspawn from nothing.
REQUIRED_TOP_LEVEL_BLOCKS = ("versioninfo", "visgroups", "viewsettings")

_DEFAULTS: dict[str, str] = {
    "versioninfo": (
        "versioninfo\n"
        "{\n"
        '\t"editorversion" "400"\n'
        '\t"editorbuild" "8456"\n'
        '\t"mapversion" "1"\n'
        '\t"formatversion" "100"\n'
        '\t"prefab" "0"\n'
        "}\n"
    ),
    "visgroups": (
        "visgroups\n"
        "{\n"
        "}\n"
    ),
    "viewsettings": (
        "viewsettings\n"
        "{\n"
        '\t"bSnapToGrid" "1"\n'
        '\t"bShowGrid" "1"\n'
        '\t"bShowLogicalGrid" "0"\n'
        '\t"nGridSpacing" "64"\n'
        '\t"bShow3DGrid" "0"\n'
        "}\n"
    ),
}


def _top_level_block_present(text: str, name: str) -> bool:
    """True iff a top-level (column-0) block named `name` exists in the
    file. Matches the same shape BSPSource emits: bare keyword followed
    by an opening brace on the next line."""
    # column-0 anchored to avoid matching nested keys with the same name
    # (e.g. an entity property called "viewsettings").
    pattern = rf"(?m)^{re.escape(name)}\s*\n\s*\{{"
    return re.search(pattern, text) is not None


def fix_vmf_missing_top_level_keys(
    text: str, finding: Finding
) -> Tuple[str, bool, str]:
    missing = list(finding.context.get("missing") or [])
    if not missing:
        return text, False, "nothing to add"

    blocks = "".join(_DEFAULTS[name] for name in missing if name in _DEFAULTS)
    if not blocks:
        return text, False, "no default templates known"

    # insert before the first `world` or `entity` block so the
    # importer sees the headers in the canonical position. fall back
    # to prepending if neither anchor is found (very unusual).
    anchor = re.search(r"(?m)^(world|entity)\s*\n\s*\{", text)
    if anchor:
        idx = anchor.start()
        new_text = text[:idx] + blocks + text[idx:]
    else:
        new_text = blocks + text

    added = ", ".join(missing)
    return new_text, True, f"added missing top-level block(s): {added}"


base.register("vmf_missing_top_level_keys", fix_vmf_missing_top_level_keys)

