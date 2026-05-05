# legacy spawn rewriter for `--fix-spawns ct|t`.
#
# this is intentionally NOT a base.register-based fixer like the others:
# the side decision (ct vs t) is a map-design call that the analyzer
# can't make, so we keep it gated behind an explicit cli flag and run
# it as a separate pass after the standard fixers.
#
# scope: rewrites the value of `"classname"` lines that name a legacy
# DOD/HL2-era spawn entity to the cs2-canonical
# `info_player_terrorist` / `info_player_counterterrorist` based on the
# user's chosen side. nothing else about the entity changes; the entity
# block keeps its origin / angles / etc.

from __future__ import annotations

import re
from typing import Iterable, Tuple

from ..analyzers.vmf import LEGACY_SPAWN_ENTITIES

# canonical cs2 spawn classnames
SIDE_CT = "info_player_counterterrorist"
SIDE_T = "info_player_terrorist"

_SIDE_MAP = {
    "ct": SIDE_CT,
    "counter": SIDE_CT,
    "counterterrorist": SIDE_CT,
    "t": SIDE_T,
    "terrorist": SIDE_T,
}

# vmf classname kv. anchored on `"classname"` to avoid matching custom
# keys named e.g. `_classname` in user-authored prefabs.
_CLASSNAME_RE = re.compile(r'(?P<lead>"classname"\s+")(?P<name>[^"]+)(?P<trail>")')


def _resolve_side(side: str) -> str:
    key = side.strip().lower()
    if key not in _SIDE_MAP:
        raise ValueError(
            f"unknown spawn side {side!r}; expected one of: ct, t, " "counterterrorist, terrorist"
        )
    return _SIDE_MAP[key]


# rewrite legacy spawn classnames to the cs2 canonical for `side`. no-op
# when no legacy spawns are present. returns (new_text, n_rewritten,
# rewrite_summary). callers use the count to drive the summary footer.
def fix_legacy_spawns(
    text: str,
    side: str,
    *,
    legacy_classes: Iterable[str] = LEGACY_SPAWN_ENTITIES,
) -> Tuple[str, int, str]:
    target = _resolve_side(side)
    legacy = set(legacy_classes)
    rewrites: dict[str, int] = {}

    def _sub(m: re.Match) -> str:
        cls = m.group("name")
        if cls in legacy:
            rewrites[cls] = rewrites.get(cls, 0) + 1
            return f"{m.group('lead')}{target}{m.group('trail')}"
        return m.group(0)

    new_text = _CLASSNAME_RE.sub(_sub, text)
    n = sum(rewrites.values())
    if n == 0:
        return new_text, 0, "no legacy spawn entities present"
    parts = ", ".join(f"{cls} x{count}" for cls, count in sorted(rewrites.items()))
    return new_text, n, f"rewrote {parts} -> {target}"
