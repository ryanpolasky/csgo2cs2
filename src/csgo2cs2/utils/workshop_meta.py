# lightweight wrapper around the Steam ISteamRemoteStorage public api.
#
# this is a stdlib-only client — no `requests`, no `steam` package, no
# auth required. we POST to the unauthenticated GetPublishedFileDetails
# endpoint to look up a workshop item's preview image url, title, etc.,
# then optionally fetch the preview into a local directory the user can
# reuse when re-publishing.

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .downloader import DownloadError, fetch

# valve's public, anonymous endpoint. POST form-encoded body. no key needed.
STEAM_API_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"

# preview images are usually .jpg from akamai. some older items use .png.
# we trust whatever extension the URL says.
_DEFAULT_PREVIEW_NAME = "preview"


@dataclass
class WorkshopMetadata:
    workshop_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    preview_url: Optional[str] = None
    file_url: Optional[str] = None
    creator: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    time_created: Optional[int] = None
    time_updated: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "workshop_id": self.workshop_id,
            "title": self.title,
            "description": self.description,
            "preview_url": self.preview_url,
            "file_url": self.file_url,
            "creator": self.creator,
            "tags": list(self.tags),
            "time_created": self.time_created,
            "time_updated": self.time_updated,
        }


class WorkshopMetadataError(RuntimeError):
    pass


# parse the published-file response shape into a tidy dataclass. valve
# returns `{"response": {"publishedfiledetails": [{...}], "result": 1}}`.
def _parse_response(workshop_id: str, body: bytes) -> WorkshopMetadata:
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise WorkshopMetadataError(f"non-json response from Steam: {exc}") from exc
    items = data.get("response", {}).get("publishedfiledetails", []) or []
    if not items:
        raise WorkshopMetadataError(
            "Steam returned no publishedfiledetails for "
            f"workshop_id={workshop_id} (response={data!r:.200})"
        )
    item = items[0]
    # `result` of 9 == "file not found" / private. surface that explicitly.
    result = item.get("result")
    if result not in (None, 1):
        raise WorkshopMetadataError(
            f"Steam result code {result} for workshop_id={workshop_id} "
            "(may be private, deleted, or banned)."
        )
    tags_raw = item.get("tags", []) or []
    tags = [t.get("tag") for t in tags_raw if isinstance(t, dict) and t.get("tag")]
    return WorkshopMetadata(
        workshop_id=workshop_id,
        title=item.get("title") or None,
        description=item.get("description") or None,
        preview_url=item.get("preview_url") or None,
        file_url=item.get("file_url") or None,
        creator=item.get("creator") or None,
        tags=tags,
        time_created=item.get("time_created"),
        time_updated=item.get("time_updated"),
        raw=item,
    )


# fetch one workshop item's metadata. raises WorkshopMetadataError on
# any non-success path so callers can decide whether to soften
# (warn-and-continue) or hard-fail.
def fetch_metadata(
    workshop_id: str,
    timeout: float = 15.0,
    *,
    _opener: Optional[Any] = None,
) -> WorkshopMetadata:
    body = urllib.parse.urlencode(
        {
            "itemcount": "1",
            "publishedfileids[0]": str(workshop_id),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        STEAM_API_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "csgo2cs2/0.1 (+https://github.com/ryanpolasky/csgo2cs2)",
        },
    )
    opener = _opener or urllib.request.build_opener()
    try:
        with opener.open(req, timeout=timeout) as resp:
            payload = resp.read()
    except OSError as exc:
        raise WorkshopMetadataError(f"network error contacting Steam: {exc}") from exc
    return _parse_response(workshop_id, payload)


def _preview_filename(url: str) -> str:
    # strip the query string steam adds for caching, keep the extension.
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        suffix = ".jpg"  # safest default
    return f"{_DEFAULT_PREVIEW_NAME}{suffix}"


# write metadata + preview image (if any) under
# `<out_dir>/<workshop_id>/`. returns the created directory.
def export_to(
    meta: WorkshopMetadata,
    out_dir: Path,
    *,
    download_preview: bool = True,
) -> Path:
    target = out_dir / str(meta.workshop_id)
    target.mkdir(parents=True, exist_ok=True)
    (target / "metadata.json").write_text(
        json.dumps(meta.to_json_dict(), indent=2), encoding="utf-8"
    )
    if download_preview and meta.preview_url:
        preview_path = target / _preview_filename(meta.preview_url)
        try:
            fetch(meta.preview_url, preview_path, name=preview_path.name, progress=None)
        except DownloadError as exc:
            # preview is best-effort. callers see the error via the
            # logging_utils warn the command-level wrapper emits.
            raise WorkshopMetadataError(f"preview download failed: {exc}") from exc
    return target
