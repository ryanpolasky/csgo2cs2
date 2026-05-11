# Scaffolding for CS2 workshop addon directories.
#
# Valve's import_map_community.py requires the target addon directory to
# already exist with at least an addoninfo.gi file and a maps/ subdir.
# Without those, the importer hangs silently or crashes (Windows is
# especially bad about silent hangs). Workshop Tools normally creates
# this scaffolding via its GUI; we ship a programmatic equivalent so
# users can port maps without launching the (5 GB) Workshop Tools app
# first.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Config

# Marker we drop into addoninfo.gi when WE created the addon, so later
# `addon list` runs can distinguish csgo2cs2-scaffolded addons from
# Workshop-Tools-created ones. Purely informational; the importer
# ignores it.
SCAFFOLD_MARKER = "// scaffolded by csgo2cs2"


# Minimum addoninfo.gi for the CS2 importer to accept the addon as a
# valid target. addonGameType=core is the type for community maps.
_ADDONINFO_TEMPLATE = """{marker}
"AddonInfo"
{{
\t"addonGameType"\t\t"core"
}}
"""


@dataclass(frozen=True)
class AddonState:
    """Summary of an addon directory's state, used by preflight and
    the `addon` subcommand to give the user actionable diagnostics."""

    path: Path
    exists: bool
    has_addoninfo: bool
    has_maps_dir: bool
    map_count: int  # files under maps/ (any depth)
    scaffolded_by_csgo2cs2: bool

    @property
    def is_scaffolded(self) -> bool:
        """True iff the dir exists with the minimum files but no
        prior port output. Safe to import into without --overwrite."""
        return self.exists and self.has_addoninfo and self.map_count == 0

    @property
    def has_prior_port_output(self) -> bool:
        """True iff the dir contains files a prior port would have
        written. Importing into here without --overwrite would clobber
        their work."""
        return self.exists and self.map_count > 0


def addon_dir(cfg: Config, addon: str) -> Path | None:
    """Canonical addon path. Returns None when cs2_addons_path is unset."""
    if not cfg.cs2_addons_path:
        return None
    return Path(cfg.cs2_addons_path).expanduser() / addon


def inspect(cfg: Config, addon: str) -> AddonState | None:
    """Snapshot the addon dir for preflight decisions. Returns None
    if cs2_addons_path is not configured (caller's problem)."""
    d = addon_dir(cfg, addon)
    if d is None:
        return None
    exists = d.exists()
    info_file = d / "addoninfo.gi"
    has_addoninfo = info_file.exists()
    maps_dir = d / "maps"
    has_maps_dir = maps_dir.exists()
    if has_maps_dir:
        map_count = sum(1 for p in maps_dir.rglob("*") if p.is_file())
    else:
        map_count = 0
    scaffolded = False
    if has_addoninfo:
        try:
            scaffolded = SCAFFOLD_MARKER in info_file.read_text(encoding="utf-8")
        except OSError:
            scaffolded = False
    return AddonState(
        path=d,
        exists=exists,
        has_addoninfo=has_addoninfo,
        has_maps_dir=has_maps_dir,
        map_count=map_count,
        scaffolded_by_csgo2cs2=scaffolded,
    )


def create(cfg: Config, addon: str, *, force: bool = False) -> Path:
    """Scaffold the minimum addon directory layout. Returns the addon
    path. Raises RuntimeError if cs2_addons_path is unset, FileExistsError
    if the dir already exists and contains files (unless `force` is set)."""
    d = addon_dir(cfg, addon)
    if d is None:
        raise RuntimeError(
            "cs2_addons_path is not set; cannot scaffold an addon. "
            "Run `csgo2cs2 init --interactive` first."
        )
    if d.exists() and any(d.iterdir()) and not force:
        raise FileExistsError(
            f"{d} already exists and is not empty. Pass force=True to overwrite."
        )
    d.mkdir(parents=True, exist_ok=True)
    (d / "maps").mkdir(exist_ok=True)
    info_file = d / "addoninfo.gi"
    if not info_file.exists() or force:
        info_file.write_text(
            _ADDONINFO_TEMPLATE.format(marker=SCAFFOLD_MARKER),
            encoding="utf-8",
        )
    return d

