# patch drift detection state.
#
# `doctor --fix` records the post-patch sha256 of each file it touched
# into a small JSON state file. plain `doctor` then re-hashes those
# files and reports whether they've drifted since (which is steam's
# usual mode of breaking these patches: a game update silently rewrites
# import_map_community.py back to its un-patched form, or restores
# vpk.signatures from the depot).
#
# the state file lives next to the workspace dir as
# `<workspace_dir>/.csgo2cs2_drift.json` so it travels with the user's
# config without needing a global cache dir.

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

DRIFT_STATE_FILENAME = ".csgo2cs2_drift.json"


@dataclass
class DriftEntry:
    path: str
    sha256: str
    size: int
    fixed_at: float  # unix timestamp


@dataclass
class DriftState:
    entries: Dict[str, DriftEntry] = field(default_factory=dict)

    def to_json_dict(self) -> Dict[str, object]:
        return {
            "version": 1,
            "entries": {
                k: {
                    "path": v.path,
                    "sha256": v.sha256,
                    "size": v.size,
                    "fixed_at": v.fixed_at,
                }
                for k, v in self.entries.items()
            },
        }

    @classmethod
    def from_json_dict(cls, data: Dict[str, object]) -> DriftState:
        entries: Dict[str, DriftEntry] = {}
        raw_entries = data.get("entries", {})
        if isinstance(raw_entries, dict):
            for k, v in raw_entries.items():
                if not isinstance(v, dict):
                    continue
                try:
                    entries[k] = DriftEntry(
                        path=str(v.get("path", k)),
                        sha256=str(v.get("sha256", "")),
                        size=int(v.get("size", 0) or 0),
                        fixed_at=float(v.get("fixed_at", 0) or 0),
                    )
                except (TypeError, ValueError):
                    continue
        return cls(entries=entries)


def _state_path(workspace_dir: Path) -> Path:
    return Path(workspace_dir).expanduser() / DRIFT_STATE_FILENAME


def load_state(workspace_dir: Path) -> DriftState:
    p = _state_path(workspace_dir)
    if not p.exists():
        return DriftState()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DriftState()
    if not isinstance(data, dict):
        return DriftState()
    return DriftState.from_json_dict(data)


def save_state(state: DriftState, workspace_dir: Path) -> Path:
    p = _state_path(workspace_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state.to_json_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return p


def hash_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


# record the post-fix state of each file. the key is the absolute path
# string so we can match across runs; the value records what the file
# looked like *after* --fix finished.
def record_fix(state: DriftState, file_path: Path, marker: str = "post_fix") -> None:
    p = file_path.expanduser()
    digest = hash_file(p)
    if digest is None:
        # file got removed mid-fix? leave the prior entry (if any) alone.
        return
    state.entries[str(p.resolve())] = DriftEntry(
        path=str(p.resolve()),
        sha256=digest,
        size=p.stat().st_size,
        fixed_at=time.time(),
    )


@dataclass
class DriftCheck:
    path: str
    drifted: bool
    last_fixed_at: float
    reason: str  # human-readable summary of what changed


# compare current file state against the stashed post-fix state.
# returns a list of one entry per tracked path. callers decide what to
# warn on.
def check_drift(state: DriftState, paths: List[Path]) -> List[DriftCheck]:
    out: List[DriftCheck] = []
    for raw in paths:
        p = raw.expanduser().resolve()
        key = str(p)
        entry = state.entries.get(key)
        if entry is None:
            # never been --fix'd; not drift, just a first-time install
            continue
        current = hash_file(p)
        if current is None:
            out.append(
                DriftCheck(
                    path=key,
                    drifted=True,
                    last_fixed_at=entry.fixed_at,
                    reason="file is missing or unreadable",
                )
            )
            continue
        if current != entry.sha256:
            out.append(
                DriftCheck(
                    path=key,
                    drifted=True,
                    last_fixed_at=entry.fixed_at,
                    reason=f"sha256 changed since last --fix ({entry.sha256[:12]} -> {current[:12]})",
                )
            )
        else:
            out.append(
                DriftCheck(
                    path=key,
                    drifted=False,
                    last_fixed_at=entry.fixed_at,
                    reason="unchanged since last --fix",
                )
            )
    return out
