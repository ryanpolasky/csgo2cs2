# csgo2cs2

A Python CLI for porting CS:GO Workshop maps to CS2 in one command. Wraps
SteamCMD, BSPSource, VPKEdit/BSPZIP, and Valve's `import_map_community.py`,
plus the install-side patching, asset pre-copy, and addon packaging the
official import script doesn't cover.

The work CS:GO→CS2 porting actually requires is mostly small and mechanical,
but it's spread across half a dozen tools and several Valve dev-wiki pages.
csgo2cs2 collapses it into one pipeline and reports the rest as concrete
findings.

## Status

Alpha scaffolding. The read-only commands (`download`, `decompile`,
`analyze`, `explain`, and the JSON reports) run on any OS. The full `port`
pipeline requires Windows: `import_map_community.py` and the CS2 Workshop
Tools are Windows-only. The importer's `-usebsp` flag covers the equivalent
of `vbsp -prepfors2` internally, so there is no separate `vbsp` adapter.

## Quick start

```bash
pip install -e .
csgo2cs2 init                                 # finds your Steam install, writes config
csgo2cs2 tools install                        # fetches pinned BSPSource / SteamCMD / import script
csgo2cs2 doctor --fix                         # patches the install; reversible with --unfix
csgo2cs2 port "<workshop-url>" --addon my_addon --auto
csgo2cs2 verify my_addon                      # cross-platform sanity check on the imported addon
csgo2cs2 launch my_addon                      # Windows-only; opens CS2 with the addon active
```

That is the happy path. The rest of this README covers what to do when a
specific map fails to import cleanly.

## Architecture

```
workshop url
  -> SteamCMD               (download workshop item)
  -> BSP inspector          (header + bspProtect detection + pakfile inventory)
  -> VPKEdit / BSPZIP       (extract packed bsp content)
  -> BSPSource              (decompile .bsp -> .vmf)
  -> VMF analyzer + fixers  (skybox, hdr-only sky, unsupported / deprecated
                             entities, light_environment dedupe, asset-path
                             issues, custom clip textures, etc.)
  -> stage <s1_content>/maps/<mapname>.vmf  (no spaces in path)
  -> pre-copy pakfile assets into <s1_content>/  (materials, models, sound,
                                                  scripts, particles, resource)
  -> import_map_community.py    (Windows-only, 5 positional args + flags)
  -> manifest + report          (track install-side mutations)
  -> cleanup                    (reverse copies/patches/renames)
```

Each external tool gets an adapter under `src/csgo2cs2/tools/`, so tools can
be swapped without rewriting the pipeline. Fixers self-register against
analyzer `issue_id`s in `src/csgo2cs2/fixers/`, which keeps new auto-fixes
small.

## Prerequisites

The CLI runs on any OS, but the full porting pipeline needs Windows plus
several external tools. **Most are auto-fetched** by
`csgo2cs2 tools install`, so the four steps in [Quick start](#quick-start)
cover a fresh setup.

If the auto-installer cannot reach GitHub or Valve CDNs, the manual list is:

- **Python 3.10+** on PATH
- **SteamCMD** (anonymous downloads for app `730` are unreliable; an
  authenticated Steam login is often required in practice)
- **Java JRE 24+** — only if you use the cross-platform `bspsrc-jar-only`
  build; the per-platform builds bundle their own JRE
- **BSPSource** (`bspsrc.jar`, `bspsrc.bat`, or `bspsrc.sh`)
- **VPKEdit** CLI, or Valve's `bspzip.exe` from the CS:GO `bin/` directory
- **CS:GO/CS2 install** (the `Counter-Strike Global Offensive` folder)
- `<csgo_install>/game/bin/win64/` on PATH (Windows)
- `colorama` Python package (required by Valve's import script)

The CS2 import path also needs two install patches the first time:

- Remove `.decode()` from line 328 of
  `game/csgo/scripts/import_map_community.py` (the line number drifts with
  CS2 versions).
- Rename `game/bin/win64/vpk.signatures` to `vpk.signatures.old`.

`csgo2cs2 doctor --fix` automates both and writes `.csgo2cs2.bak` files so
the changes are reversible. Steam tends to revert them during game
updates — see [Doctor](#doctor) for how the tool catches that automatically.

## Install

```bash
pip install -e .
```

This exposes `csgo2cs2` as a shell command.

## Usage

```bash
# setup
csgo2cs2 init                                   # create config (auto-detects Steam install)
csgo2cs2 init --interactive                     # prompt for any paths we cannot auto-detect
csgo2cs2 tools install                          # fetch BSPSource / SteamCMD / import script
csgo2cs2 tools install bspsource --force        # re-download a single tool
csgo2cs2 tools list                             # show installed tool paths

# health
csgo2cs2 doctor                                 # check tools and prereqs
csgo2cs2 doctor --fix                           # apply install patches with backups
csgo2cs2 doctor --unfix                         # reverse install patches (VAC-safe)
csgo2cs2 doctor --json                          # machine-readable health report (jq-friendly)

# pieces
csgo2cs2 download "<workshop-url-or-id>"        # download via SteamCMD
csgo2cs2 download <id> --export-images <dir>    # also save the workshop preview + metadata.json
csgo2cs2 decompile <bsp-path>                   # BSPSource decompile
csgo2cs2 analyze <vmf-path>                     # report VMF issues
csgo2cs2 analyze <vmf-path> --fix               # apply auto-fixes (skybox, entities, paths, etc.)
csgo2cs2 analyze <vmf-path> --fix --dry-run     # preview the unified diff of --fix without writing
csgo2cs2 analyze <vmf-path> --fix --fix-spawns ct  # opt-in: rewrite legacy spawns to CT (or `t`)
csgo2cs2 analyze <vmf-path> --bsp <bsp-path>    # also include BSP header + pakfile audit
csgo2cs2 analyze <vmf-path> --explain           # print curated what/why/fix per finding
csgo2cs2 analyze <vmf-path> --report-json       # machine-readable findings on stdout
csgo2cs2 analyze <vmf-path> --report-json out.json  # write findings to a file
csgo2cs2 explain <issue_id>                     # standalone explanation for one finding
csgo2cs2 explain --list                         # list every issue_id with a curated entry

# full port
csgo2cs2 port "<workshop-url-or-id>" --addon my_addon --auto              # full pipeline (Windows)
csgo2cs2 port --bsp ./local.bsp --addon my_addon --auto                   # skip SteamCMD, use a local file
csgo2cs2 port "<workshop-url-or-id>" --addon my_addon --skip-import       # cross-OS dry run
csgo2cs2 port "<workshop-url-or-id>" --addon my_addon --auto --dry-run    # show fixer plan + would-run importer cmd
csgo2cs2 port <id> --addon <name> --export-images <dir>                   # also save preview + metadata.json
csgo2cs2 port <id> --addon <name> --auto-addoninfo                        # populate addoninfo.json from workshop metadata

# manage prior ports
csgo2cs2 list                                   # list prior ports under workspace_dir
csgo2cs2 status "<workshop-url-or-id>"          # show one port's manifest
csgo2cs2 cleanup "<workshop-url-or-id>"         # undo install-side mutations
csgo2cs2 cleanup "<workshop-url-or-id>" --dry-run

# post-port
csgo2cs2 verify <addon>                         # post-port sanity check (.vmap, addoninfo, asset refs)
csgo2cs2 launch <addon>                         # open CS2 with the addon active (Windows; --print-only elsewhere)
csgo2cs2 launch <addon> --hammer                # open Hammer 2 instead of the game
csgo2cs2 launch <addon> --map de_dust2          # override the auto-detected map
csgo2cs2 publish <addon>                        # package addon dir into upload-ready zip + verify
csgo2cs2 publish <addon> -o my_addon.zip        # override output path
csgo2cs2 publish <addon> --skip-verify          # skip structural checks (faster; not recommended)

# misc
csgo2cs2 about                                  # version, attribution, links
csgo2cs2 completion bash                        # shell completion (also: zsh, powershell)
```

## Findings

`csgo2cs2 analyze` reports issues by `issue_id` so they are easy to grep or
pipe into `jq` via `--report-json`. Current set:

| issue_id                    | severity | fixable | when                                                                                 |
|-----------------------------|----------|---------|--------------------------------------------------------------------------------------|
| `skybox_hdr_only`           | error    | yes     | Skyname is in the curated HDR-only list (importer fails)                             |
| `skybox_unknown`            | warn     | yes     | Skyname is not in `KNOWN_CS2_SKIES` (or `cfg.cs2_sky_list`)                          |
| `skybox_missing`            | warn     | no      | No `skyname` key in worldspawn                                                       |
| `entity_unsupported`        | warn     | yes     | Classname is in `UNSUPPORTED_ENTITIES` plus extras from config                       |
| `entity_legacy_spawn`       | warn     | no      | DOD-era / Source 1 spawns instead of CS2 team spawns                                 |
| `entity_deprecated_s2`      | info     | yes     | Classname has no Source 2 equivalent (areaportal, fog_controller, etc.)              |
| `missing_spawn`             | warn     | no      | No `info_player_terrorist` or `info_player_counterterrorist`                         |
| `light_environment_count`   | warn     | yes     | More than one `light_environment` (CS2 expects exactly one)                          |
| `texture_clip_custom`       | warn     | yes     | Custom clip texture (auto-rewrites to `tools/toolsclip` so the importer keeps it)    |
| `asset_path_space`          | error    | no      | A material/model path contains a space                                               |
| `asset_path_absolute`       | error    | no      | A material/model path uses a Windows drive letter                                    |
| `asset_path_backslash`      | warn     | yes     | A material/model path uses backslashes                                               |
| `asset_path_csgo_subfolder` | warn     | yes     | Path lives under a folder literally named `csgo/` (auto-rewritten to `csgo_legacy/`) |
| `manual_rebuild_cubemaps`   | info     | no      | `env_cubemap` entities or pakfile cubemap assets present (run `buildcubemaps`)       |
| `manual_review_soundscapes` | info     | no      | Soundscape/ambient entities or `scripts/soundscapes_*.txt` in pakfile                |
| `manual_review_overlays`    | info     | no      | `info_overlay` entities (UVs re-bake during import)                                  |
| `manual_rebuild_nav`        | info     | no      | `.nav` file in BSP pakfile (CS2 nav format differs)                                  |
| `manual_rebuild_radar`      | info     | no      | `resource/overviews/<map>_radar.*` in BSP pakfile                                    |
| `pakfile_scripts`           | warn     | no      | `.lua`/`.nut` scripts embedded (CS2 vscript surface differs)                         |
| `pakfile_csgo_subfolder`    | warn     | no      | BSP pakfile contains assets under `materials/csgo/`                                  |
| `bsp_invalid_header`        | error    | no      | File is not a Source 1 .bsp (no `VBSP` magic)                                        |
| `bsp_protected`             | error    | no      | BSP shows a known anti-decompile marker                                              |
| `pakfile_error`             | warn     | no      | Embedded pakfile lump is unreadable                                                  |

The JSON report includes a `summary` block with counts per severity plus a
`fixable` count, so CI scripts can fail on `summary.error > 0`.

`csgo2cs2 explain <issue_id>` prints a curated *what / why / how-to-fix*
block for each id; `csgo2cs2 analyze --explain` does the same inline for
every finding. The text is offline and deterministic — see
[Prior art & attributions](#prior-art--attributions) for the source
material.

## What `--fix` does

`csgo2cs2 analyze <vmf> --fix` writes a `.csgo2cs2.bak` and runs every
registered fixer in sequence. Add `--dry-run` to print a unified diff
instead of writing. The same fixers run automatically inside
`csgo2cs2 port`.

Each fixer is small and idempotent. Current set:

- **Smart skybox replacement.** When a `skybox_unknown` or
  `skybox_hdr_only` finding fires, the fixer first looks at the original
  skyname for hints (desert / urban / industrial / …) and picks the closest
  **wiki-confirmed CS2 sky** from the
  [official CS2 sky list](https://developer.valvesoftware.com/wiki/Counter-Strike_2_Workshop_Tools/CS2_Sky_List).
  If no hint matches, it falls back to `cfg.default_skybox` (default
  `sky_cs_office` — overcast neutral, picked because brightness=0 keeps it
  from visibly fighting the map's existing `light_environment`).
- **Entity removal.** `entity_unsupported` and `entity_deprecated_s2`
  classnames are stripped (areaportal, occluder, fog_controller,
  point_template, the rest of the consumed-entity set).
- **`light_environment` dedupe.** Keeps the first, deletes the rest. CS2
  expects exactly one.
- **Asset path normalization.** Backslashes become forward slashes; folders
  literally named `csgo/` are rewritten to `csgo_legacy/`, with a matching
  rename in the staged tree.
- **Custom clip textures.** Non-`tools/toolsclip*` clip texture references
  are rewritten so the importer keeps the brush instead of silently
  dropping it.
- **Legacy spawns** *(opt-in only).* `analyze --fix --fix-spawns ct|t`
  rewrites DOD/HL2-era spawn classnames (`info_player_axis`,
  `info_player_allies`, `info_player_combine`, `info_player_rebel`,
  `info_player_start`) to `info_player_counterterrorist` or
  `info_player_terrorist`. Off by default because the side mapping is
  map-design-specific.

After the fixers run, the resulting VMF is structurally re-validated
(brace balance, quote balance) by `analyzers/roundtrip.py`. If a fixer
produces a corrupted file, `--fix` refuses to write and the original stays
on disk.

### Smart skybox table

| Original skyname contains                                    | Replaced with                          |
|--------------------------------------------------------------|----------------------------------------|
| `dust2` / `dust_` / `dust.`                                  | `sky_de_dust2`                         |
| `mirage` / `arabia` / `desert` / `sahara`                    | `sky_de_mirage`                        |
| `anubis` / `annubis` / `egypt` / `pharaoh`                   | `sky_de_annubis`                       |
| `inferno` / `coast` / `mediterranean`                        | `s2_de_inferno_sky01`                  |
| `italy` / `italia`                                           | `cs_italy_s2_skybox_2`                 |
| `overpass` / `euro`                                          | `sky_de_overpass_01`                   |
| `office` / `embassy` / `station`                             | `sky_cs_office`                        |
| `vertigo` / `downtown` / `urban` / `urb_` / `alley` / `city` | `sky_de_vertigo`                       |
| `nuke` / `industrial` / `factory`                            | `sky_de_nuke`                          |
| `aztec` / `ancient` / `jungle` / `temple` / `ruins`          | `sky_hr_aztec_02_lighting`             |
| _(none of the above)_                                        | `cfg.default_skybox` (`sky_cs_office`) |

Override `cfg.default_skybox` to any wiki-confirmed sky from the list
above. Custom skies you have added to your CS2 install can be added to
`cfg.cs2_sky_list` so they do not trip `skybox_unknown`.

## Pakfile asset pre-copy

Real workshop maps usually embed custom `materials/`, `models/`, and
`sound/` files inside the BSP's pakfile. Valve's import script resolves
asset paths relative to the S1 *content* tree, so without those custom
assets in place the import aborts on the first missing
`.vmt` / `.mdl` / `.wav`.

`csgo2cs2 port` extracts the pakfile (via VPKEdit or BSPZIP) and pre-copies
the recognized subdirectories (`materials`, `models`, `sound`, `scripts`,
`particles`, `resource`) into the staged content tree before invoking the
importer. It is a no-op when `extracted/` is empty and skips files that
already exist at the same size, so re-running `port` on a workspace is
cheap.

## Post-port helpers

After the import succeeds, the workflow tail is `verify`, `launch`, and
optionally `publish`. All three operate on the imported addon directory;
none of them needs network or the CS2 install to run (`launch` does, but
only on Windows when actually launching the game).

```bash
csgo2cs2 verify <addon>          # cross-platform sanity check
csgo2cs2 launch <addon>          # Windows-only; opens CS2 with the addon
csgo2cs2 launch <addon> --hammer # opens Hammer 2 instead of the game
csgo2cs2 publish <addon>         # package addon into an upload-ready zip
```

`verify` checks that the addon directory looks plausible **without**
actually loading CS2:

- A `.vmap` file exists under `<addon>/maps/`.
- `addoninfo.json` (or `.gi` / `.txt`) parses and is non-empty.
- A sample of material / model references in the `.vmap` resolves on disk
  (catches the "all my custom textures are missing" failure mode that
  otherwise only shows up as purple/black checkers in-game).

It exits non-zero on any failure, so it slots cleanly into CI.

`launch` reads the addon's `maps/*.vmap` to find the map name, then runs
the equivalent of `cs2.exe -game csgo -addon <name> +map <mapname>`. On
non-Windows hosts it falls back to printing the command — useful as a
sanity check on macOS/Linux or for pasting into a Wine launcher.
`--hammer` opens the Workshop Tools instead; `--map <mapname>` overrides
auto-detection when the addon ships multiple `.vmap` files.

`publish` runs the same structural checks as `verify`, then packages the
addon directory into an upload-ready zip. Build artifacts (`*.bak`,
`*.csgo2cs2.bak`, `_csgo2cs2_*`, `.DS_Store`, `Thumbs.db`, `*.tmp`) are
excluded automatically. Flags: `-o <path>` for output, `--skip-verify` to
skip the structural checks, `--allow-errors` to build the zip even if
verify reports errors.

## Workshop metadata

`csgo2cs2 download` and `csgo2cs2 port` can optionally fetch the workshop
item's preview image plus a `metadata.json` blob (title, description,
tags, creation/update timestamps) via Steam's anonymous
`ISteamRemoteStorage/GetPublishedFileDetails` endpoint:

```bash
csgo2cs2 download <id> --export-images ./images
csgo2cs2 port <id> --addon my_addon --auto --export-images ./images
csgo2cs2 port <id> --addon my_addon --auto --auto-addoninfo
```

`--export-images` writes `./images/<workshop_id>/preview.jpg` plus
`./images/<workshop_id>/metadata.json`. Off by default; the network call
only happens when you opt in, and is **soft-failed** so flaky web
behavior will not kill an in-progress port.

`--auto-addoninfo` writes a populated `addoninfo.json` (title /
description / tags) plus the preview image as the addon thumbnail
directly into the imported addon's directory. Existing user-authored
`addoninfo.{json,gi,txt}` files are **never** overwritten unless you
explicitly pass `--force-addoninfo`; auto-generated files carry a
`_csgo2cs2: "auto-populated from workshop metadata"` sentinel so
subsequent runs can tell the difference.

When metadata is fetched (via either flag) it is also snapshotted into
the port's `manifest.json`, so `csgo2cs2 status <id>` later shows title,
creator, tags, and a trimmed description without re-hitting the Steam
API.

## Doctor

`doctor` is the install-side of the tool: patching, un-patching, and
inspection. All three modes share the same backup and manifest machinery.

```bash
csgo2cs2 doctor              # check tools and prereqs
csgo2cs2 doctor --fix        # apply install patches with .csgo2cs2.bak backups
csgo2cs2 doctor --unfix      # reverse install patches (VAC-safe)
csgo2cs2 doctor --json       # machine-readable health report
```

### Drift detection

`doctor --fix` records a SHA-256 of every file it patched (currently
`import_map_community.py` and the renamed `vpk.signatures.old`) into
`<workspace_dir>/.csgo2cs2_drift.json`. Plain `doctor` re-hashes them on
its next run and warns if any have drifted, which is Steam's usual way
of breaking these patches: a game update silently rewrites
`import_map_community.py` back to its un-patched form, or restores
`vpk.signatures` from the depot. The warning includes a hint to re-run
`--fix`.

### VAC safety

Running on a VAC server with the install patches applied is **not
recommended**. Valve has not published a stance on the modified
`import_map_community.py` or the renamed `vpk.signatures`, but anything
under `game/bin/win64/` is the kind of file VAC may flag in the future.
The simplest guarantee is to reverse the patches once you are done
porting:

```bash
csgo2cs2 doctor --unfix    # restores import_map_community.py and renames
                           # vpk.signatures.old back to vpk.signatures
```

`--unfix` uses the `.csgo2cs2.bak` files written during `--fix`. If those
backups are gone (e.g. the workspace was deleted), `--unfix` reports what
it could not reverse and exits 0 anyway, so it is safe to chain
(`doctor --unfix && cs2.exe`).

### JSON output

`--json` emits a structured report capturing environment, tool,
install-patch, and drift state. Useful for CI or piping into `jq`:

```bash
csgo2cs2 doctor --json | jq '.summary.ok'           # boolean
csgo2cs2 doctor --json | jq '.tools.steamcmd.path'
csgo2cs2 doctor --json | jq '.install_patches.import_map_community_py.patched'
```

The `summary` block (`ok`, `issue_count`, `fixes_applied_count`,
`drift_count`) is the obvious gate for a CI step: `exit 1` on any
non-zero count signals a regression.

## Ergonomics

A few smaller knobs that do not fit anywhere else:

- **Shell completion.** `csgo2cs2 completion bash|zsh|powershell` emits a
  static completion script for the shell of your choice. Covers
  subcommand names, `--fix-spawns` sides (`ct` / `t`), and the
  `completion` shell values themselves:

  ```bash
  csgo2cs2 completion bash >> ~/.local/share/bash-completion/completions/csgo2cs2
  csgo2cs2 completion zsh  >> ~/.zfunc/_csgo2cs2 && fpath+=~/.zfunc && compinit
  csgo2cs2 completion powershell >> $PROFILE
  ```

- **Color output.** `NO_COLOR=1` and `CSGO2CS2_NO_COLOR=1` both disable
  ANSI color. The default respects whatever `colorama` decides about the
  current terminal.
- **Dry runs.** `analyze --fix --dry-run` prints a unified diff of what
  the fixers would do; `port --dry-run` prints the asset pre-copy plan
  and the would-run importer command line. Neither writes anything.

## Known limitations

- **Windows-only `port`.** Decompile fidelity is bounded by BSPSource:
  brushwork, displacements, and area portals are imperfectly recovered.
- **`bspProtect`-protected maps** cannot be decompiled cleanly. The
  analyzer flags these (`bsp_protected`).
- **Nav meshes, radar, soundscapes, cubemaps, and lighting** do not
  transfer cleanly and need to be regenerated in Hammer 2. The analyzer
  reports these as `manual_rebuild_*` / `manual_review_*` info findings
  when it can detect the relevant entities or pakfile contents.
- **Legacy spawns** (`info_player_axis`, `info_player_allies`, etc.) are
  not auto-converted by default — the side mapping (CT vs. T) is
  map-design-specific. The analyzer flags them as `entity_legacy_spawn`
  warnings; opt in with `analyze --fix --fix-spawns ct|t` to auto-rewrite
  every legacy spawn to a single side.
- **Anonymous SteamCMD downloads** for app `730` are unreliable; an
  authenticated Steam login may be required.

## Prior art & attributions

- **[andreaskeller96/cs2-import-scripts](https://github.com/andreaskeller96/cs2-import-scripts)**
  — the canonical Python 3 port of Valve's official
  `import_map_community.py`, with the de-facto pitfall list for CS:GO→CS2
  imports. csgo2cs2's HDR sky detection, asset-path checks (spaces /
  drive-letter / backslash / `csgo/` subfolder), custom-clip-texture
  detection, and the `--unfix` patch list are derived from that project's
  README and source. csgo2cs2 uses the upstream script directly when you
  opt into `csgo2cs2 tools install import_map_community`.
- **[ata4/bspsrc](https://github.com/ata4/bspsrc)** (BSPSource) — the
  .bsp → .vmf decompiler that csgo2cs2 wraps. The
  `entity_deprecated_s2` set (`func_areaportal`, `func_viscluster`,
  `info_no_dynamic_shadow`, etc.) is derived from BSPSource's
  "Limitations and known bugs" notes about which entities `vbsp` consumes
  and cannot perfectly restore.
- **Valve** — `import_map_community.py` itself is Valve's official import
  script. csgo2cs2's role is to scaffold setup, flag the same pitfalls
  earlier, and orchestrate the pipeline.

If you spot prior art that should be credited (or a mistake in how
something is credited here), please open a PR.

## Layout

```
src/csgo2cs2/
  cli.py                 # argparse entry point
  config.py              # config load/save
  platform_check.py      # OS gating
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
    launch_cmd.py        # csgo2cs2 launch <addon>
    verify_cmd.py        # csgo2cs2 verify <addon>
    publish_cmd.py       # csgo2cs2 publish <addon> -> upload-ready zip
    about_cmd.py         # csgo2cs2 about
    completion_cmd.py    # csgo2cs2 completion bash|zsh|powershell
  tools/                 # external tool adapters
    base.py
    steamcmd.py
    bspsource.py
    vpkedit.py
    bspzip.py
    import_map.py
  analyzers/             # pure-python analysis
    vmf.py               # VMF text analysis -> findings
    bsp.py               # BSP header + protection sniff + pakfile inventory + findings
    report.py            # structured JSON report builder
    explain.py           # curated what/why/fix registry per issue_id
    roundtrip.py         # post-fix structural safety check (brace + quote balance)
  fixers/                # registered auto-fixers
    base.py              # registry + apply_all
    skybox.py            # skybox_unknown / skybox_hdr_only
    entities.py          # entity_unsupported / entity_deprecated_s2
    asset_paths.py       # asset_path_backslash + asset_path_csgo_subfolder
    light_environment.py # light_environment_count dedupe
    clip_textures.py     # texture_clip_custom -> tools/toolsclip
    spawns.py            # opt-in --fix-spawns ct|t legacy spawn rewriter
  utils/                 # url, paths, backup, manifest, steam, downloader,
                         #   tools_registry, workshop_meta, addoninfo, drift helpers
tests/                   # pytest suite
  fixtures/              # check-in VMF samples for snapshot tests
```
