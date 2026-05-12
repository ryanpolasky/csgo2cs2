# Blacklisted-material fixer.
#
# source1import (closed-source) silently drops .vmf brush-side `material`
# refs whose pak01 .vmt is on a hardcoded blacklist (tools/locked,
# editor/gray, dev/reflectivity_90b, dev/dev_hazzardstripe01a). The
# resulting `.vmat_c` never gets written, so CS2's compile / Hammer Build
# flags `Failed loading resource "...vmat_c" (ERROR_FILEOPEN: File not
# found)` warnings and the affected brush sides render as missing-texture
# checkerboards in-game.
#
# We can't lift the source1import blacklist itself, so we instead rewrite
# every offending `"material" "<blacklisted path>"` value in the .vmf to
# a CS2-stock substitute defined in
# `analyzers.vmf.CSGO_BLACKLISTED_MATERIALS`. The substitute materials
# already ship with CS2 (no import step required), so the brush sides
# render with a sensible-looking texture and the Hammer Build warning
# disappears.

from __future__ import annotations

from typing import Tuple

from ..analyzers.vmf import CSGO_BLACKLISTED_MATERIALS, Finding, _norm_mat
from . import base


def fix_csgo_blacklisted_materials(text: str, finding: Finding) -> Tuple[str, bool, str]:
    refs = finding.context.get("refs") or []
    if not isinstance(refs, list) or not refs:
        return text, False, "no blacklisted refs in finding context"

    replaced_count = 0
    replaced_pairs: list[Tuple[str, str]] = []
    for ref in refs:
        if not isinstance(ref, str):
            continue
        substitute = CSGO_BLACKLISTED_MATERIALS.get(_norm_mat(ref))
        if not substitute:
            continue
        needle = f'"material" "{ref}"'
        replacement = f'"material" "{substitute}"'
        if needle in text:
            # exact-case match: literal replace, count occurrences first
            count = text.count(needle)
            text = text.replace(needle, replacement)
            replaced_count += count
            replaced_pairs.append((ref, substitute))
            continue
        # fall back to case-insensitive search for `"Material" "..."`
        # variants. .vmf KV keys are usually lower-case but tools have
        # been seen with `Material` (BSPSource being one).
        lo_needle = needle.lower()
        lo_text = text.lower()
        idx = lo_text.find(lo_needle)
        if idx == -1:
            continue
        while idx != -1:
            text = text[:idx] + replacement + text[idx + len(needle):]
            replaced_count += 1
            lo_text = text.lower()
            idx = lo_text.find(lo_needle)
        replaced_pairs.append((ref, substitute))

    if not replaced_count:
        return text, False, "no blacklisted material refs found in vmf body"
    summary = ", ".join(f"`{src}` -> `{dst}`" for src, dst in replaced_pairs)
    return text, True, f"substituted {replaced_count} ref(s): {summary}"


base.register("csgo_blacklisted_materials", fix_csgo_blacklisted_materials)
