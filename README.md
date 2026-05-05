# csgo2cs2

a python cli for porting cs:go workshop maps to cs2 through one scripted
workflow. it wraps steamcmd, bspsource, vpkedit/bspzip, and valve's
`import_map_community.py` behind one command.

## Status

alpha scaffolding. the boring parts (url parsing, download, decompile, analyze)
should run anywhere. the full `port` pipeline needs windows because the cs2
import bits (`import_map_community.py`, cs2 workshop tools) live there.
the importer's `-usebsp` flag handles the equivalent of `vbsp -prepfors2`
internally, so we don't ship a separate `vbsp` adapter.

## Architecture

```
workshop url
  -> SteamCMD               (download workshop item)
  -> BSP inspector          (header + bspprotect detection + pakfile inventory)
  -> VPKEdit / BSPZIP       (extract packed bsp content)
  -> BSPSource              (decompile .bsp -> .vmf)
  -> VMF analyzer + fixers  (skybox, hdr-only sky, unsupported / deprecated
                             entities, light_environment dedupe, asset-path
                             issues, custom clip textures, etc.)
  -> stage <s1_content>/maps/<mapname>.vmf  (no spaces in path)
  -> pre-copy pakfile assets into <s1_content>/  (materials, models, sound,
                                                   scripts, particles, resource)
  -> import_map_community.py    (windows-only, 5 positional args + flags)
  -> manifest + report      (track install-side mutations)
  -> cleanup                (reverse copies/patches/renames)
```

each external tool gets an adapter under `src/csgo2cs2/tools/`, so tools can be
swapped without rewriting the pipeline. fixers self-register against analyzer
`issue_id`s in `src/csgo2cs2/fixers/`, which keeps new auto-fixes small.

## Prerequisites

the cli runs on any os, but the full porting pipeline needs windows plus these
external tools. **most of them are auto-fetched** by `csgo2cs2 tools install`,
so the only manual steps for a fresh setup are usually:

1. install python 3.10+ and run `pip install -e .`
2. `csgo2cs2 init` (auto-detects a Counter-Strike Global Offensive install)
3. `csgo2cs2 tools install` (downloads pinned BSPSource / SteamCMD / import script)
4. `csgo2cs2 doctor --fix` (applies the .decode + vpk.signatures install patches)

fully manual list, in case the auto-installer can't reach github / valve cdns:

- **python 3.10+** on PATH
- **SteamCMD** (anonymous downloads for app `730` are flaky; account login is
  often needed)
- **java jre 24+** (only if you go with the cross-platform `bspsrc-jar-only`
  build; the per-platform builds bundle their own jre)
- **BSPSource** (`bspsrc.jar`, `bspsrc.bat`, or `bspsrc.sh`)
- **VPKEdit** CLI, or Valve's `bspzip.exe` from CS:GO `bin/`
- **CS:GO/CS2 install** ("Counter-Strike Global Offensive" folder)
- `<csgo_install>/game/bin/win64/` on PATH (windows)
- `colorama` Python package (required by Valve's import script)

the first time you set up cs2 imports manually, you also need:

- Remove `.decode()` from line 328 of `game/csgo/scripts/import_map_community.py`
  (path may vary by CS2 version). `csgo2cs2 doctor --fix` automates this with
  a backup.
- Rename `game/bin/win64/vpk.signatures` to `vpk.signatures.old`. Also automated
  by `doctor --fix`.

steam may revert these on game update. run `doctor` before every port.

## Install

```bash
pip install -e .
```

this exposes `csgo2cs2` as a shell command.

## Usage

```bash
csgo2cs2 init                                   # create config (auto-detects steam install)
csgo2cs2 init --interactive                     # prompt for any paths we cannot auto-detect
csgo2cs2 tools install                          # fetch BSPSource / SteamCMD / import script
csgo2cs2 tools install bspsource --force        # re-download a single tool
csgo2cs2 tools list                             # show installed tool paths
csgo2cs2 doctor                                 # check tools and prereqs
csgo2cs2 doctor --fix                           # apply install patches with backups
csgo2cs2 doctor --unfix                         # reverse install patches (VAC-safe)
csgo2cs2 download "<workshop-url-or-id>"        # download via steamcmd
csgo2cs2 decompile <bsp-path>                   # bspsource decompile
csgo2cs2 analyze <vmf-path>                     # report vmf issues
csgo2cs2 analyze <vmf-path> --fix               # apply auto-fixes (skybox, entities, paths, etc.)
csgo2cs2 analyze <vmf-path> --fix --dry-run     # preview the unified diff of --fix without writing
csgo2cs2 analyze <vmf-path> --bsp <bsp-path>    # also include bsp header + pakfile audit
csgo2cs2 analyze <vmf-path> --explain           # print curated what/why/fix per finding
csgo2cs2 analyze <vmf-path> --report-json       # machine-readable findings on stdout
csgo2cs2 analyze <vmf-path> --report-json out.json  # write findings to a file
csgo2cs2 explain <issue_id>                     # standalone explanation for one finding
csgo2cs2 explain --list                         # list every issue_id with a curated entry
csgo2cs2 port "<workshop-url-or-id>" --addon my_addon --auto              # full pipeline (windows)
csgo2cs2 port --bsp ./local.bsp --addon my_addon --auto                   # skip steamcmd, use a local file
csgo2cs2 port "<workshop-url-or-id>" --addon my_addon --skip-import       # cross-os dry run
csgo2cs2 port "<workshop-url-or-id>" --addon my_addon --auto --dry-run    # show fixer plan + would-run importer cmd
csgo2cs2 list                                   # list prior ports under workspace_dir
csgo2cs2 status "<workshop-url-or-id>"          # show one port's manifest
csgo2cs2 cleanup "<workshop-url-or-id>"         # undo install-side mutations
csgo2cs2 cleanup "<workshop-url-or-id>" --dry-run
```

## Findings

`csgo2cs2 analyze` reports issues by `issue_id` so they're easy to grep / pipe
into `jq` via `--report-json`. Current set:

| issue_id                    | severity | fixable | when                                                                       |
|-----------------------------|----------|---------|----------------------------------------------------------------------------|
| `skybox_hdr_only`           | error    | yes     | skyname is in the curated HDR-only list (importer fails)                   |
| `skybox_unknown`            | warn     | yes     | skyname isn't in `KNOWN_CS2_SKIES` (or `cfg.cs2_sky_list`)                 |
| `skybox_missing`            | warn     | no      | no `skyname` key in worldspawn                                             |
| `entity_unsupported`        | warn     | yes     | classname is in `UNSUPPORTED_ENTITIES` + extras from config                |
| `entity_legacy_spawn`       | warn     | no      | DOD-era / Source 1 spawns instead of CS2 team spawns                       |
| `entity_deprecated_s2`      | info     | yes     | classname has no Source 2 equivalent (areaportal, fog_controller, etc.)    |
| `missing_spawn`             | warn     | no      | no `info_player_terrorist` or `info_player_counterterrorist`               |
| `light_environment_count`   | warn     | yes     | more than one `light_environment` (cs2 expects exactly one)                |
| `texture_clip_custom`       | warn     | no      | custom clip texture (importer drops anything outside `tools/toolsclip*`)   |
| `asset_path_space`          | error    | no      | a material/model path contains a space                                     |
| `asset_path_absolute`       | error    | no      | a material/model path uses a Windows drive letter                          |
| `asset_path_backslash`      | warn     | yes     | a material/model path uses backslashes                                     |
| `asset_path_csgo_subfolder` | warn     | no      | a material/model path lives under a folder literally named `csgo/`         |
| `manual_rebuild_cubemaps`   | info     | no      | env_cubemap entities or pakfile cubemap assets present (run buildcubemaps) |
| `manual_review_soundscapes` | info     | no      | soundscape/ambient entities or `scripts/soundscapes_*.txt` in pakfile      |
| `manual_review_overlays`    | info     | no      | `info_overlay` entities (UVs re-bake during import)                        |
| `manual_rebuild_nav`        | info     | no      | `.nav` file in bsp pakfile (cs2 nav format differs)                        |
| `manual_rebuild_radar`      | info     | no      | `resource/overviews/<map>_radar.*` in bsp pakfile                          |
| `pakfile_scripts`           | warn     | no      | `.lua`/`.nut` scripts embedded (cs2 vscript surface differs)               |
| `pakfile_csgo_subfolder`    | warn     | no      | bsp pakfile contains assets under `materials/csgo/`                        |
| `bsp_invalid_header`        | error    | no      | file isn't a Source 1 .bsp (no `VBSP` magic)                               |
| `bsp_protected`             | error    | no      | bsp shows a known anti-decompile marker                                    |
| `pakfile_error`             | warn     | no      | embedded pakfile lump is unreadable                                        |

The JSON report includes a `summary` block with counts per severity plus a
`fixable` count, so CI scripts can fail on `summary.error > 0`.

`csgo2cs2 explain <issue_id>` prints a curated *what / why / how-to-fix* block
for each id; `csgo2cs2 analyze --explain` does the same inline for every
finding the analyzer surfaced. The text is offline and deterministic — see
[Prior art & attributions](#prior-art--attributions) for the source material.

## Pakfile asset pre-copy

Real workshop maps usually embed custom `materials/`, `models/`, and `sound/`
files inside the bsp's pakfile. Valve's import script resolves asset paths
relative to the s1 *content* tree, so without those custom assets in place
the import aborts on the first missing `.vmt` / `.mdl` / `.wav`.

`csgo2cs2 port` now extracts the pakfile (via VPKEdit or BSPZIP) and
pre-copies the recognized subdirectories (`materials`, `models`, `sound`,
`scripts`, `particles`, `resource`) into the staged content tree before
invoking the importer. This collapses the most common manual cleanup step
to zero work.

The pre-copy is a no-op when `extracted/` is empty (e.g. base-asset-only
maps) and skips files that already exist at the same size in the staged
tree, so re-running `port` on a workspace is cheap.

## Dry runs

Two `--dry-run` flags let you preview changes before they hit disk:

- `csgo2cs2 analyze <vmf> --fix --dry-run` runs the fixers in memory and
  prints a unified diff of the resulting `.vmf`. Nothing is written, no
  `.csgo2cs2.bak` is created. Use this to audit the fixer output before
  committing to it.
- `csgo2cs2 port <id> --addon <name> --dry-run` runs the full
  download / decompile / analyze flow but stops short of the cs2 import.
  It prints the asset pre-copy plan and the exact importer command it
  would run, so you can copy-paste it manually if you want to.

## Known Limitations

- **windows-only `port`.** decompile fidelity is bounded by BSPSource: brushwork,
  displacements, and area portals are imperfectly recovered.
- **`bspProtect`-protected maps** cannot be decompiled cleanly; the analyzer
  flags these (`bsp_protected`).
- **nav meshes, radar, soundscapes, cubemaps, and lighting** do not transfer
  cleanly and need to be regenerated in Hammer 2 — the analyzer surfaces this
  as `manual_rebuild_*` / `manual_review_*` info findings when it can detect
  the relevant entities or pakfile contents.
- **legacy spawns** (`info_player_axis`, `info_player_allies`, etc.) are not
  auto-converted because the side mapping (CT vs. T) is map-design-specific.
  The analyzer flags them as `entity_legacy_spawn` warnings; remap them in
  Hammer before re-running the import.
- **anonymous steamcmd downloads** for app `730` are unreliable; an authenticated
  Steam login may be required.

## VAC safety

Running on a VAC server with the install patches applied is **not recommended**
— Valve hasn't published a stance on the modified `import_map_community.py`
or the renamed `vpk.signatures`, but anything that touches files under
`game/bin/win64/` is the kind of thing VAC may flag in the future. The simplest
guarantee is to reverse them when you're done porting:

```bash
csgo2cs2 doctor --unfix    # restores import_map_community.py and renames
                           # vpk.signatures.old back to vpk.signatures
```

The reverse uses the `.csgo2cs2.bak` files written during `--fix`. If those
backups are gone (e.g. you've nuked the directory), `--unfix` reports what it
couldn't reverse and exits 0 anyway so you can chain it (`doctor --unfix && cs2.exe`).

## Prior art & attributions

This project stands on the shoulders of community work. In particular:

- **[andreaskeller96/cs2-import-scripts](https://github.com/andreaskeller96/cs2-import-scripts)**
  — the canonical Python 3 port of Valve's official `import_map_community.py`,
  with the de-facto pitfall list for csgo→cs2 imports. csgo2cs2's HDR sky
  detection, asset-path checks (spaces / drive-letter / backslash / `csgo/`
  subfolder), custom-clip-texture detection, and the `--unfix` patch list are
  all derived from that project's README and source. We use the upstream script
  directly when the user opts into `csgo2cs2 tools install import_map_community`.
- **[ata4/bspsrc](https://github.com/ata4/bspsrc)** (BSPSource) — the .bsp →
  .vmf decompiler that csgo2cs2 wraps. The `entity_deprecated_s2` set
  (`func_areaportal`, `func_viscluster`, `info_no_dynamic_shadow`, etc.) traces
  back to BSPSource's "Limitations and known bugs" notes about which entities
  vbsp consumes and can't be perfectly restored.
- **Valve** — `import_map_community.py` itself is Valve's official import
  script. csgo2cs2's role is only to scaffold setup, surface the same pitfalls
  earlier, and orchestrate the pipeline.

If you spot prior art we should credit (or a mistake in how we're crediting
something here), please open a PR.

## Layout

```
src/csgo2cs2/
  cli.py                 # argparse entry point
  config.py              # config load/save
  platform_check.py      # os gating
  logging_utils.py       # colorized output
  pipeline.py            # full port orchestration
  extract.py             # bsp asset extraction (vpkedit | bspzip)
  commands/              # subcommand implementations
    init_cmd.py
    doctor.py
    tools_cmd.py
    download.py
    decompile.py
    analyze.py
    explain_cmd.py
    port.py
    list_cmd.py
    status_cmd.py
    cleanup.py
  tools/                 # external tool adapters
    base.py
    steamcmd.py
    bspsource.py
    vpkedit.py
    bspzip.py
    import_map.py
  analyzers/             # pure-python analysis
    vmf.py               # vmf text analysis -> findings
    bsp.py               # bsp header + protection sniff + pakfile inventory + findings
    report.py            # structured json report builder
    explain.py           # curated what/why/fix registry per issue_id
  fixers/                # registered auto-fixers
    base.py              # registry + apply_all
    skybox.py            # skybox_unknown / skybox_hdr_only
    entities.py          # entity_unsupported / entity_deprecated_s2
    asset_paths.py       # asset_path_backslash
    light_environment.py # light_environment_count dedupe
  utils/                 # url, paths, backup, manifest, steam, downloader,
                         #   tools_registry helpers
tests/                   # pytest suite
  fixtures/              # check-in vmf samples for snapshot tests
```
