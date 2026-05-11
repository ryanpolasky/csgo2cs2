# track install-side files for cleanup, and per-stage state for resume.

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List


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

    title: str | None = None
    description: str | None = None
    creator: str | None = None
    tags: List[str] = field(default_factory=list)
    preview_url: str | None = None
    time_created: int | None = None
    time_updated: int | None = None
    fetched_at: float | None = None


# Stage state values used by the port pipeline. Pipeline writes one of
# these into manifest.stages[<stage_name>] after each stage runs.
STAGE_PENDING = "pending"
STAGE_RUNNING = "running"
STAGE_DONE = "done"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"

# Canonical stage names in pipeline order. Centralized here so other
# modules (status_cmd, walkthrough, tests) can reference the same list.
PORT_STAGES: tuple[str, ...] = (
    "download",
    "inspect",
    "extract",
    "decompile",
    "analyze",
    "import",
)


@dataclass
class StageRecord:
    name: str
    status: str = STAGE_PENDING
    started_at: float | None = None
    ended_at: float | None = None
    detail: str = ""  # free-form note: error message, file count, etc.

    @property
    def elapsed(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.ended_at if self.ended_at is not None else time.time()
        return end - self.started_at


@dataclass
class PortManifest:
    workshop_id: str
    addon_name: str
    copied_files: List[CopiedFile] = field(default_factory=list)
    patched_files: List[str] = field(default_factory=list)
    renamed_files: List[RenamedFile] = field(default_factory=list)
    workshop_meta: WorkshopMeta | None = None
    stages: Dict[str, StageRecord] = field(default_factory=dict)
    last_args: Dict[str, Any] = field(default_factory=dict)

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

    def start_stage(self, name: str) -> StageRecord:
        rec = self.stages.get(name)
        if rec is None:
            rec = StageRecord(name=name)
            self.stages[name] = rec
        rec.status = STAGE_RUNNING
        rec.started_at = time.time()
        rec.ended_at = None
        rec.detail = ""
        return rec

    def finish_stage(self, name: str, status: str, detail: str = "") -> StageRecord:
        rec = self.stages.get(name) or StageRecord(name=name)
        self.stages[name] = rec
        rec.status = status
        rec.ended_at = time.time()
        if detail:
            rec.detail = detail
        return rec

    def stage_is_done(self, name: str) -> bool:
        rec = self.stages.get(name)
        return rec is not None and rec.status == STAGE_DONE

    def save(self, path: Path) -> None:
        from .atomic import write_json

        data: Dict[str, Any] = {
            "workshop_id": self.workshop_id,
            "addon_name": self.addon_name,
            "copied_files": [asdict(c) for c in self.copied_files],
            "patched_files": list(self.patched_files),
            "renamed_files": [asdict(r) for r in self.renamed_files],
            "workshop_meta": asdict(self.workshop_meta) if self.workshop_meta else None,
            "stages": {k: asdict(v) for k, v in self.stages.items()},
            "last_args": dict(self.last_args),
        }
        write_json(path, data)

    @classmethod
    def load(cls, path: Path) -> PortManifest:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        copied = [CopiedFile(**c) for c in data.pop("copied_files", [])]
        renamed = [RenamedFile(**r) for r in data.pop("renamed_files", [])]
        meta_raw: Dict[str, Any] | None = data.pop("workshop_meta", None)
        meta: WorkshopMeta | None = None
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
        stages_raw = data.pop("stages", {}) or {}
        stages: Dict[str, StageRecord] = {}
        if isinstance(stages_raw, dict):
            for k, v in stages_raw.items():
                if not isinstance(v, dict):
                    continue
                try:
                    stages[k] = StageRecord(
                        name=str(v.get("name", k)),
                        status=str(v.get("status", STAGE_PENDING)),
                        started_at=v.get("started_at"),
                        ended_at=v.get("ended_at"),
                        detail=str(v.get("detail", "")),
                    )
                except (TypeError, ValueError):
                    continue
        last_args = data.pop("last_args", {}) or {}
        if not isinstance(last_args, dict):
            last_args = {}
        # remaining keys: workshop_id, addon_name -- forward to ctor
        return cls(
            copied_files=copied,
            renamed_files=renamed,
            workshop_meta=meta,
            stages=stages,
            last_args=last_args,
            **data,
        )
