# remove unsupported vmf entity blocks.

from __future__ import annotations

import re
from typing import List, Tuple

from ..analyzers.vmf import Finding
from . import base

ENTITY_HEADER_RE = re.compile(r"\bentity\s*\{", re.IGNORECASE)
CLASSNAME_RE = re.compile(r'"classname"\s*"([^"]+)"', re.IGNORECASE)


# find the matching closing brace for a vmf block.
def _find_block_end(text: str, open_brace_idx: int) -> int:
    depth = 0
    i = open_brace_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def remove_unsupported_entity(text: str, finding: Finding) -> Tuple[str, bool, str]:
    target = str(finding.context.get("classname") or "").strip()
    if not target:
        return text, False, "no target classname"

    removed_spans: List[Tuple[int, int]] = []
    pos = 0
    while True:
        m = ENTITY_HEADER_RE.search(text, pos)
        if not m:
            break
        # locate this entity block
        brace_idx = text.find("{", m.start())
        if brace_idx < 0:
            break
        end = _find_block_end(text, brace_idx)
        if end < 0:
            break
        block = text[m.start() : end]
        cls_match = CLASSNAME_RE.search(block)
        if cls_match and cls_match.group(1) == target:
            removed_spans.append((m.start(), end))
        pos = end

    if not removed_spans:
        return text, False, f"no entities matched `{target}`"

    # remove from the end so earlier indices stay valid
    for start, end in reversed(removed_spans):
        # include trailing whitespace after the entity block
        while end < len(text) and text[end] in (" ", "\t", "\r", "\n"):
            end += 1
        text = text[:start] + text[end:]

    return (
        text,
        True,
        f"removed {len(removed_spans)} `{target}` entit{'y' if len(removed_spans) == 1 else 'ies'}",
    )


base.register("entity_unsupported", remove_unsupported_entity)
