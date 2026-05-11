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

# Same marker, expressed as a `//` line comment inside gameinfo.gi so we
# can detect csgo2cs2-written files for idempotent heal-on-port.
GAMEINFO_MARKER = "// scaffolded by csgo2cs2"


# Minimum addoninfo.gi for the CS2 importer to accept the addon as a
# valid target. addonGameType=core is the type for community maps.
_ADDONINFO_TEMPLATE = """{marker}
"AddonInfo"
{{
\t"addonGameType"\t\t"core"
}}
"""

# gameinfo.gi tells Workshop Tools / resourcecompiler / cs2.exe what
# search paths the addon mod has access to. The CRITICAL bit is
# `LayeredOnMod csgo` -- without that, the addon is isolated and can't
# resolve ANY base CSGO/CS2 content (concrete textures, weapon models,
# scripts, etc.). With it, all of csgo's search paths (csgo,
# csgo_imported, csgo_core, core) are inherited and resourcecompiler
# can find the assets the map references.
#
# `Game` and `Mod` entries pointing at csgo_addons/<addon> put the
# addon's own content at the head of the chain so map-specific overrides
# win over base content. Workshop Tools writes essentially the same
# file when you create an addon via its GUI; we just emit it directly
# so users don't have to launch Workshop Tools first.
_GAMEINFO_TEMPLATE = """{marker}
"GameInfo"
{{
\tgame\t\t"{addon}"
\ttitle\t\t"{addon}"
\ttype\t\tmultiplayer_only
\tGameData\t"csgo.fgd"

\tLayeredOnMod\tcsgo

\tFileSystem
\t{{
\t\tSteamAppId\t\t730
\t\tSearchPaths
\t\t{{
\t\t\tGame\tcsgo_addons/{addon}
\t\t\tMod\tcsgo_addons/{addon}
\t\t}}
\t}}
}}
"""


@dataclass(frozen=True)
class AddonState:
    """Summary of an addon directory's state, used by preflight and
    the `addon` subcommand to give the user actionable diagnostics."""

    path: Path
    exists: bool
    has_addoninfo: bool
    has_gameinfo: bool
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
    """Canonical addon path (game-side). Returns None when
    cs2_addons_path is unset."""
    if not cfg.cs2_addons_path:
        return None
    return Path(cfg.cs2_addons_path).expanduser() / addon


def content_addon_dir(cfg: Config, addon: str) -> Path | None:
    """Editable-source-side addon path under `content/csgo_addons/`.
    Mirrors the game-side dir's layout; Hammer reads .vmap source from
    here, resourcecompiler writes .vmap_c to game-side. Returns None
    when the install layout can't be inferred from cs2_addons_path."""
    game = addon_dir(cfg, addon)
    if game is None:
        return None
    parts = list(game.parts)
    try:
        idx = len(parts) - 1 - parts[::-1].index("game")
    except ValueError:
        return None
    parts[idx] = "content"
    return Path(*parts)


def inspect(cfg: Config, addon: str) -> AddonState | None:
    """Snapshot the addon dir for preflight decisions. Returns None
    if cs2_addons_path is not configured (caller's problem)."""
    d = addon_dir(cfg, addon)
    if d is None:
        return None
    exists = d.exists()
    info_file = d / "addoninfo.gi"
    has_addoninfo = info_file.exists()
    gi_file = d / "gameinfo.gi"
    has_gameinfo = gi_file.exists()
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
        has_gameinfo=has_gameinfo,
        has_maps_dir=has_maps_dir,
        map_count=map_count,
        scaffolded_by_csgo2cs2=scaffolded,
    )


def create(cfg: Config, addon: str, *, force: bool = False) -> Path:
    """Scaffold the minimum addon directory layout. Returns the addon
    path. Raises RuntimeError if cs2_addons_path is unset, FileExistsError
    if the dir already exists and contains files (unless `force` is set).

    Writes:
      - game-side  addoninfo.gi   (workshop addon metadata)
      - game-side  gameinfo.gi    (mod search path config; CRITICAL for
                                   csgo/csgo_imported/csgo_core mounting)
      - game-side  maps/          (so importer's xcopy target exists)
      - content-side gameinfo.gi  (mirror; Hammer reads from here)
      - content-side maps/        (Hammer source .vmap dir)
    """
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
    gi_file = d / "gameinfo.gi"
    if not gi_file.exists() or force:
        gi_file.write_text(
            _GAMEINFO_TEMPLATE.format(marker=GAMEINFO_MARKER, addon=addon),
            encoding="utf-8",
        )
    # Mirror on the content side so Hammer can find the addon.
    content_d = content_addon_dir(cfg, addon)
    if content_d is not None:
        content_d.mkdir(parents=True, exist_ok=True)
        (content_d / "maps").mkdir(exist_ok=True)
        content_gi = content_d / "gameinfo.gi"
        if not content_gi.exists() or force:
            content_gi.write_text(
                _GAMEINFO_TEMPLATE.format(marker=GAMEINFO_MARKER, addon=addon),
                encoding="utf-8",
            )
    return d


def ensure_gameinfo(cfg: Config, addon: str) -> list[Path]:
    """Heal an existing addon dir by writing gameinfo.gi if missing.

    Idempotent: returns the list of paths that were written. Returns
    `[]` if both sides already have gameinfo.gi or the install layout
    can't be resolved. Used by the port pipeline so addons scaffolded
    by an older csgo2cs2 (or by Workshop Tools without a gameinfo.gi)
    self-heal on the next port without requiring re-create.
    """
    written: list[Path] = []
    game_d = addon_dir(cfg, addon)
    if game_d is None or not game_d.exists():
        return written
    body = _GAMEINFO_TEMPLATE.format(marker=GAMEINFO_MARKER, addon=addon)
    for d in (game_d, content_addon_dir(cfg, addon)):
        if d is None:
            continue
        gi = d / "gameinfo.gi"
        if gi.exists():
            continue
        try:
            d.mkdir(parents=True, exist_ok=True)
            gi.write_text(body, encoding="utf-8")
        except OSError:
            continue
        written.append(gi)
    return written
