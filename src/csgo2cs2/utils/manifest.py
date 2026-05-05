# track install-side files for cleanup.

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CopiedFile:
    src: str
    dest: str
    overwrote_existing: bool = False


@dataclass
class RenamedFile:
    original: str
    renamed_to: str


@dataclass
class WorkshopMeta:
    """workshop metadata snapshot recorded at port time. populated when
    `--export-images` or `--auto-addoninfo` triggers a steam api fetch."""

    title: Optional[str] = None
    description: Optional[str] = None
    creator: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    preview_url: Optional[str] = None
    time_created: Optional[int] = None
    time_updated: Optional[int] = None
    fetched_at: Optional[float] = None


@dataclass
class PortManifest:
    workshop_id: str
    addon_name: str
    copied_files: List[CopiedFile] = field(default_factory=list)
    patched_files: List[str] = field(default_factory=list)
    renamed_files: List[RenamedFile] = field(default_factory=list)
    workshop_meta: Optional[WorkshopMeta] = None

    def record_copy(self, src: Path, dest: Path, overwrote: bool) -> None:
        self.copied_files.append(
            CopiedFile(src=str(src), dest=str(dest), overwrote_existing=overwrote)
        )

    def record_patch(self, path: Path) -> None:
        s = str(path)
        if s not in self.patched_files:
            self.patched_files.append(s)

    def record_rename(self, original: Path, renamed_to: Path) -> None:
        self.renamed_files.append(RenamedFile(original=str(original), renamed_to=str(renamed_to)))

    def record_workshop_meta(self, meta: WorkshopMeta) -> None:
        self.workshop_meta = meta

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> PortManifest:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        copied = [CopiedFile(**c) for c in data.pop("copied_files", [])]
        renamed = [RenamedFile(**r) for r in data.pop("renamed_files", [])]
        meta_raw: Optional[Dict[str, Any]] = data.pop("workshop_meta", None)
        meta: Optional[WorkshopMeta] = None
        if isinstance(meta_raw, dict):
            meta = WorkshopMeta(
                title=meta_raw.get("title"),
                description=meta_raw.get("description"),
                creator=meta_raw.get("creator"),
                tags=list(meta_raw.get("tags") or []),
                preview_url=meta_raw.get("preview_url"),
                time_created=meta_raw.get("time_created"),
                time_updated=meta_raw.get("time_updated"),
                fetched_at=meta_raw.get("fetched_at"),
            )
        return cls(
            copied_files=copied,
            renamed_files=renamed,
            workshop_meta=meta,
            **data,
        )
