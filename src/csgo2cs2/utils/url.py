# steam workshop url parsing.

from __future__ import annotations

import re

_QUERY_ID_RE = re.compile(r"[?&]id=(\d+)")
_STEAM_PROTOCOL_RE = re.compile(r"CommunityFilePage/(\d+)")
_BARE_ID_RE = re.compile(r"^\d+$")


# extract a workshop file id from a url or bare id.
def parse_workshop_id(url_or_id: str) -> str | None:
    if not url_or_id:
        return None
    s = url_or_id.strip()
    if _BARE_ID_RE.match(s):
        return s
    m = _QUERY_ID_RE.search(s)
    if m:
        return m.group(1)
    m = _STEAM_PROTOCOL_RE.search(s)
    if m:
        return m.group(1)
    return None


# build a canonical steam workshop url.
def workshop_url(workshop_id: str) -> str:
    return f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
