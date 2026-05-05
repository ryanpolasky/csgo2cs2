# curated explanations for every issue_id we emit.
#
# this is the "human-readable summary" surface for `csgo2cs2 analyze --explain`
# and `csgo2cs2 explain <issue_id>`. the entries are deterministic and offline
# on purpose: an llm-generated summary would be flakier and would ship vmf
# metadata to a third party.
#
# entries are keyed by issue_id and contain:
#   title:      one-line summary
#   what:       what was detected
#   why:        why it matters for the cs2 import
#   fix:        what the user should do; "auto" if csgo2cs2 will handle it
#   refs:       attribution / further reading

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Explanation:
    issue_id: str
    title: str
    what: str
    why: str
    fix: str
    refs: List[str]


# attribution shorthands referenced from individual entries
_REF_KELLER = (
    "andreaskeller96/cs2-import-scripts (Valve's official CS2 import script "
    "ported to Python 3): https://github.com/andreaskeller96/cs2-import-scripts"
)
_REF_BSPSRC = (
    "ata4/bspsrc (BSPSource decompiler) — limitations on entities consumed by "
    "vbsp: https://github.com/ata4/bspsrc#limitations-and-known-bugs"
)
_REF_VALVE_S2_VIS = (
    "Source 2 visibility / occlusion notes — Valve Developer Wiki: "
    "https://developer.valvesoftware.com/wiki/Source_2"
)
_REF_VALVE_NAV = "CS2 nav generation — `nav_generate` console command in CS2 Workshop Tools."
_REF_VALVE_CUBEMAPS = "CS2 cubemaps — run `buildcubemaps` after import to bake new envmaps."


_EXPLANATIONS: Dict[str, Explanation] = {
    "skybox_hdr_only": Explanation(
        issue_id="skybox_hdr_only",
        title="Skybox is HDR-only and will fail the cs2 importer.",
        what="The map's `skyname` is a CSGO HDR-only sky with no LDR fallback.",
        why=(
            "The cs2 import script tries to find an LDR variant of the sky to "
            "convert; without one, the import aborts."
        ),
        fix=(
            "auto — `csgo2cs2 analyze --fix` swaps in `cfg.default_skybox` "
            "(default `sky_day01_01`). cs2 uses a different sky pipeline anyway, "
            "so the visual is mostly a placeholder."
        ),
        refs=[_REF_KELLER],
    ),
    "skybox_unknown": Explanation(
        issue_id="skybox_unknown",
        title="Skybox isn't a known cs2 sky.",
        what="The map's `skyname` value isn't in `KNOWN_CS2_SKIES` or `cfg.cs2_sky_list`.",
        why=(
            "Unknown skies usually still import, but the result is undefined — "
            "you may end up with the dev sky or no sky at all."
        ),
        fix=(
            "auto — `--fix` substitutes `cfg.default_skybox`. To accept a "
            "community sky as valid, add it to `cs2_sky_list` in your config."
        ),
        refs=[_REF_KELLER],
    ),
    "skybox_missing": Explanation(
        issue_id="skybox_missing",
        title="No skybox set on worldspawn.",
        what="No `skyname` key found on worldspawn.",
        why=(
            "The cs2 importer expects a sky reference. Without one, lighting "
            "may compile incorrectly."
        ),
        fix=(
            "manual — open the .vmf in Hammer and set worldspawn's Sky Name "
            "to one of the known cs2 skies (e.g. `sky_day01_01`)."
        ),
        refs=[_REF_KELLER],
    ),
    "entity_unsupported": Explanation(
        issue_id="entity_unsupported",
        title="Entity classname not supported in cs2.",
        what="An entity classname is in csgo2cs2's `UNSUPPORTED_ENTITIES` set.",
        why=(
            "These entities either crash the importer, get silently dropped, "
            "or have no cs2 equivalent. Removing them up front makes the "
            "import predictable."
        ),
        fix="auto — `--fix` deletes the entity blocks from the .vmf.",
        refs=[_REF_BSPSRC],
    ),
    "entity_legacy_spawn": Explanation(
        issue_id="entity_legacy_spawn",
        title="Legacy team-spawn entity from a non-CS Source title.",
        what=(
            "An `info_player_axis` / `info_player_allies` / `info_player_combine` "
            "/ `info_player_rebel` / `info_player_start` entity is present."
        ),
        why=(
            "CS2 only recognizes `info_player_terrorist` and "
            "`info_player_counterterrorist`. Other team spawns just won't spawn "
            "anyone."
        ),
        fix=(
            "manual — replace each legacy spawn with the appropriate cs2 spawn "
            "in Hammer. Picking which side maps to which is map-design-specific, "
            "so we don't auto-convert."
        ),
        refs=[],
    ),
    "entity_deprecated_s2": Explanation(
        issue_id="entity_deprecated_s2",
        title="Entity is deprecated/replaced in Source 2.",
        what=(
            "Entities like `func_areaportal`, `func_occluder`, `env_fog_controller`, "
            "or `color_correction_volume` are present."
        ),
        why=(
            "Source 2 replaced visibility (areaportals/occluders), fog, and "
            "color correction with new systems. The old entities import as "
            "no-ops."
        ),
        fix=(
            "manual — after import, delete these in Hammer 2 and use the cs2 "
            "equivalents: occlusion is automatic, fog uses `env_volumetric_fog`/"
            "`env_combined_light_probe_volume`, color correction uses tonemap LUTs."
        ),
        refs=[_REF_VALVE_S2_VIS, _REF_BSPSRC],
    ),
    "missing_spawn": Explanation(
        issue_id="missing_spawn",
        title="Map is missing CT or T spawns.",
        what="No `info_player_terrorist` or `info_player_counterterrorist` entities found.",
        why="A cs2 map needs both spawn classes to be playable in standard modes.",
        fix=(
            "manual — add the appropriate spawns in Hammer. If the source map "
            "had `info_player_start` (legacy spawn), see `entity_legacy_spawn`."
        ),
        refs=[],
    ),
    "light_environment_count": Explanation(
        issue_id="light_environment_count",
        title="Multiple `light_environment` entities found.",
        what="More than one `light_environment` exists in the .vmf.",
        why=(
            "CS2's vrad expects exactly one. Extras are ignored, but they "
            "indicate a copy-paste / legacy issue worth cleaning up."
        ),
        fix=(
            "auto — `csgo2cs2 analyze --fix` keeps the first `light_environment` "
            "and removes the rest. If the wrong one wins, edit the .vmf so the "
            "keeper is the first to appear in the file before re-running."
        ),
        refs=[],
    ),
    "texture_clip_custom": Explanation(
        issue_id="texture_clip_custom",
        title="Custom clip-style texture won't survive the import.",
        what="A material reference contains `clip` but isn't `tools/toolsclip*`.",
        why=(
            "The cs2 import script silently drops custom clip textures. cs2 "
            "doesn't rely on custom clips for footstep sounds either."
        ),
        fix=(
            "manual — replace the custom clip with `tools/toolsclip` or "
            "`tools/toolsplayerclip` in s1 Hammer before re-running the import."
        ),
        refs=[_REF_KELLER],
    ),
    "asset_path_space": Explanation(
        issue_id="asset_path_space",
        title="Asset path contains a space.",
        what="A material/model/sound reference contains a space character.",
        why=(
            "The cs2 import pipeline uses raw shell invocations that don't "
            "handle quoted paths consistently. Spaces cause hard failures."
        ),
        fix=(
            "manual — rename the path so there are no spaces, then update the "
            ".vmf references. The same rule applies to the .vmf's parent "
            "directory."
        ),
        refs=[_REF_KELLER],
    ),
    "asset_path_absolute": Explanation(
        issue_id="asset_path_absolute",
        title="Asset path is absolute (Windows drive letter).",
        what="An asset reference like `C:\\foo\\bar.vmt` was found.",
        why=(
            "The importer resolves assets relative to the csgo content tree. "
            "Absolute paths break that resolution and the import fails."
        ),
        fix=(
            "manual — convert to a path relative to "
            "`<csgo install>/csgo/materials/` (or `models/`, `sound/` etc)."
        ),
        refs=[_REF_KELLER],
    ),
    "asset_path_backslash": Explanation(
        issue_id="asset_path_backslash",
        title="Asset path uses backslashes.",
        what="An asset reference uses Windows-style `\\` separators.",
        why=(
            "Mostly cosmetic on Windows, but breaks on case-sensitive "
            "filesystems and is a sign the path was authored on a different OS."
        ),
        fix=(
            "auto — `csgo2cs2 analyze --fix` rewrites each flagged path's "
            "backslashes as forward slashes inside the quoted .vmf value."
        ),
        refs=[],
    ),
    "asset_path_csgo_subfolder": Explanation(
        issue_id="asset_path_csgo_subfolder",
        title="Asset path lives under a folder literally named `csgo/`.",
        what="A material/model path contains a `csgo/` directory segment.",
        why=(
            "The cs2 import script special-cases the csgo install directory; "
            "having `csgo/` in your map's path tree confuses path resolution."
        ),
        fix=(
            "manual — rename the offending folder (any name except `csgo` works) "
            "and update the .vmf references."
        ),
        refs=[_REF_KELLER],
    ),
    "manual_rebuild_cubemaps": Explanation(
        issue_id="manual_rebuild_cubemaps",
        title="Cubemaps need to be rebuilt in cs2.",
        what="The map references env_cubemap entities or embeds cubemap assets.",
        why=(
            "cs2 envmaps are baked through a different shader pipeline; the "
            "csgo cubemaps just become missing-texture references."
        ),
        fix=(
            "manual — after import, load the map in cs2 and run "
            "`buildcubemaps` in the in-editor console. Then save and recompile."
        ),
        refs=[_REF_VALVE_CUBEMAPS],
    ),
    "manual_review_soundscapes": Explanation(
        issue_id="manual_review_soundscapes",
        title="Soundscapes use the csgo format and need re-authoring.",
        what="The map embeds `scripts/soundscapes_*.txt` or has soundscape entities.",
        why=(
            "cs2 uses `.vsndevts` soundscape scripts in `scripts/soundevents/`. "
            "The csgo `scripts/soundscapes_*.txt` files don't run."
        ),
        fix=(
            "manual — recreate soundscape definitions in `.vsndevts` form and "
            "re-point any `env_soundscape` entities to the new event names."
        ),
        refs=[],
    ),
    "manual_review_overlays": Explanation(
        issue_id="manual_review_overlays",
        title="Decals/overlays may need re-positioning.",
        what="The map has `info_overlay` entities.",
        why=(
            "cs2 re-bakes brush UVs during import. Overlays often end up on "
            "the wrong faces or shifted off the intended surface."
        ),
        fix="manual — review every `info_overlay` after import and re-attach.",
        refs=[],
    ),
    "manual_rebuild_nav": Explanation(
        issue_id="manual_rebuild_nav",
        title="Nav mesh must be regenerated for cs2.",
        what="A `.nav` file is embedded in the bsp pakfile.",
        why=(
            "cs2 uses a different nav format. The csgo nav doesn't load and "
            "bots have nothing to navigate on."
        ),
        fix=(
            "manual — in cs2 with the map loaded, run `nav_generate` (or "
            "`nav_edit 1` and `nav_save`)."
        ),
        refs=[_REF_VALVE_NAV],
    ),
    "manual_rebuild_radar": Explanation(
        issue_id="manual_rebuild_radar",
        title="Radar overview must be regenerated for cs2.",
        what="`resource/overviews/<map>_radar.*` assets are embedded.",
        why=(
            "cs2's radar pipeline uses a different format and texture layout. "
            "The csgo radar texture won't render."
        ),
        fix=("manual — use cs2 Workshop Tools' `Generate Radar` step on the " "imported map."),
        refs=[],
    ),
    "pakfile_scripts": Explanation(
        issue_id="pakfile_scripts",
        title="Embedded vscript / lua scripts won't run in cs2.",
        what="The bsp pakfile contains `.lua` or `.nut` files.",
        why=("cs2 vscript surface area differs from csgo's; entity scripts " "won't execute."),
        fix=(
            "manual — port any required scripted behavior to cs2 vscript or "
            "to in-engine entity I/O."
        ),
        refs=[],
    ),
    "pakfile_csgo_subfolder": Explanation(
        issue_id="pakfile_csgo_subfolder",
        title="Pakfile assets live under `materials/csgo/`.",
        what="The bsp embeds materials under a literal `csgo/` subfolder.",
        why="Same reason as `asset_path_csgo_subfolder`: importer path conflict.",
        fix=(
            "manual — extract the pakfile, rename the `csgo/` folder to "
            "anything else, and re-pack OR move the assets into the cs2 "
            "addon's materials tree manually."
        ),
        refs=[_REF_KELLER],
    ),
    "bsp_invalid_header": Explanation(
        issue_id="bsp_invalid_header",
        title="File doesn't have a VBSP header.",
        what="The first 4 bytes of the .bsp aren't `VBSP`.",
        why="csgo2cs2 only supports Source 1 .bsp files.",
        fix="manual — verify you have the right file and that it's not corrupt.",
        refs=[],
    ),
    "bsp_protected": Explanation(
        issue_id="bsp_protected",
        title="Decompile-protected map.",
        what="The bsp contains a known anti-decompile marker (e.g. `BSPProtect`).",
        why=(
            "Protected maps either fail BSPSource outright or produce broken "
            "geometry. Most workshop maps that use this don't permit ports."
        ),
        fix=(
            "manual — get the original .vmf from the author. Don't proceed "
            "without permission; it's a license issue, not just a tooling issue."
        ),
        refs=[_REF_BSPSRC],
    ),
    "pakfile_error": Explanation(
        issue_id="pakfile_error",
        title="Couldn't read the embedded pakfile.",
        what="The pakfile lump exists but isn't a valid zip / read failed.",
        why=(
            "The pakfile is where csgo embeds custom materials/models. If we "
            "can't read it, custom assets may need to be sourced separately."
        ),
        fix=(
            "manual — try `bspsrc` or `vpkedit` directly on the .bsp; some "
            "tooling tolerates pakfile quirks better than zip's strict parser."
        ),
        refs=[_REF_BSPSRC],
    ),
}


def get(issue_id: str) -> Optional[Explanation]:
    return _EXPLANATIONS.get(issue_id)


def known_ids() -> List[str]:
    return sorted(_EXPLANATIONS.keys())


# render an explanation as a human-readable block. we intentionally keep this
# plain text (no ansi) so it pipes well to files / CI logs.
def render(exp: Explanation) -> str:
    lines: List[str] = [
        f"# {exp.issue_id}",
        "",
        exp.title,
        "",
        f"What:  {exp.what}",
        f"Why:   {exp.why}",
        f"Fix:   {exp.fix}",
    ]
    if exp.refs:
        lines.append("")
        lines.append("References:")
        for r in exp.refs:
            lines.append(f"  - {r}")
    return "\n".join(lines)
