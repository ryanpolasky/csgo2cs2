# dedupe light_environment entities: keep the first, delete the rest.

from __future__ import annotations

from typing import List, Tuple

from ..analyzers.vmf import Finding
from . import base
from .entities import CLASSNAME_RE, ENTITY_HEADER_RE, _find_block_end


def dedupe_light_environment(text: str, finding: Finding) -> Tuple[str, bool, str]:
    target = "light_environment"
    spans: List[Tuple[int, int]] = []
    pos = 0
    while True:
        m = ENTITY_HEADER_RE.search(text, pos)
        if not m:
            break
        brace_idx = text.find("{", m.start())
        if brace_idx < 0:
            break
        end = _find_block_end(text, brace_idx)
        if end < 0:
            break
        block = text[m.start() : end]
        cls = CLASSNAME_RE.search(block)
        if cls and cls.group(1) == target:
            spans.append((m.start(), end))
        pos = end

    if len(spans) <= 1:
        return text, False, "nothing to dedupe"

    # keep spans[0]; drop the rest in reverse so earlier indices stay valid
    extras = spans[1:]
    for start, end in reversed(extras):
        # gobble trailing whitespace so we don't leave blank lines
        while end < len(text) and text[end] in (" ", "\t", "\r", "\n"):
            end += 1
        text = text[:start] + text[end:]

    n = len(extras)
    return text, True, f"removed {n} duplicate `light_environment` entit{'y' if n == 1 else 'ies'}"


base.register("light_environment_count", dedupe_light_environment)
