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

If you would rather have the tool walk you through the steps interactively
the first time, run:

```bash
csgo2cs2 walkthrough         # or: csgo2cs2 tour
```

See [Walkthrough](#walkthrough) below for what it does.

## Walkthrough

`csgo2cs2 walkthrough` (alias `tour`) is an interactive guided tour for a
first-time port. It runs through six stages, explaining each one and asking
before doing anything that writes to disk:

1. **Config.** Detects whether `~/.csgo2cs2/config.json` exists; offers to
   run `csgo2cs2 init` (with or without `--interactive`) if it does not.
2. **External tools.** Lists the configured tools and their disk status.
   Offers to run `csgo2cs2 tools install` for anything missing.
3. **Install patches.** On Windows only, checks the drift state and offers
   `csgo2cs2 doctor --fix`. Skipped on macOS and Linux.
4. **Port.** Prompts for a Workshop URL/ID and an addon name, then asks
   whether to apply auto-fixes, populate `addoninfo.json` from workshop
   metadata, and export workshop images. On non-Windows hosts it falls
   back to a `--skip-import` dry run.
5. **Verify.** Runs `csgo2cs2 verify <addon>` against the imported addon
   directory.
6. **Launch.** Optional, Windows only. Runs `csgo2cs2 launch <addon>` if
   you want the tour to drop you straight into the game.

Re-running the walkthrough is safe: each stage detects its own state and
skips when there is nothing to do. Useful flags:

- `--yes` / `-y` — assume yes for every confirmation prompt
  (non-interactive; useful for CI smoke tests).
- `--from <stage>` — resume from a specific stage. Stages are
  `config`, `tools`, `patches`, `port`, `verify`, `launch`.
- `--workshop <url-or-id>` and `--addon <name>` — pre-fill the port
  prompts so the walkthrough only asks for confirmations.
- `--no-launch` — skip the optional launch step at the end.

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
csgo2cs2 port <id> --addon <name> --restart                               # wipe prior stage state and start over
csgo2cs2 port <id> --addon <name> --no-resume                             # re-run every stage but keep manifest
csgo2cs2 port <id> --addon <name> --overwrite                             # allow writing into an existing addon dir
csgo2cs2 port <id> --addon <name> --skip-preflight                        # bypass preflight checks (not recommended)

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
csgo2cs2 walkthrough                            # interactive guided tour for first-time users
csgo2cs2 walkthrough --yes                      # non-interactive (assume yes for every confirm)
csgo2cs2 walkthrough --from port --workshop <id> --addon my_addon
csgo2cs2 tour                                   # alias of `walkthrough`
csgo2cs2 about                                  # version, attribution, links
csgo2cs2 completion bash                        # shell completion (also: zsh, powershell)
csgo2cs2 selftest                               # synthetic pipeline test (no Steam, no CS2; <1s)
csgo2cs2 selftest --with-tools                  # also invoke SteamCMD/BSPSource as a smoke check
csgo2cs2 bug-report                             # bundle diagnostic info into a zip for github issues
csgo2cs2 bug-report -o /tmp/report.zip          # custom output path
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

## Resilience

`port` is the kind of pipeline that will fail at least once before it
succeeds. The failure modes are predictable (Steam logs you out
mid-download, BSPSource crashes on a weird BSP, the importer dies
halfway through, Steam's daily quota kicks in), so the tool is built
to recover from them gracefully rather than start over.

### Preflight checks

Before `port` writes anything or contacts Steam, it runs a battery of
checks: tool paths exist and are executable, `cs2_addons_path` is
writable, free disk space is at least 2 GB, the addon name is valid,
`workspace_dir` is below the Windows MAX_PATH safe budget, and the
install patches have been applied. Failures are reported up front as a
single "fix these N things and retry" message:

```
[error] Preflight blocked the port. Fix these and re-run:
[ERROR] tool_not_on_disk_steamcmd_path: steamcmd_path = '/totally/fake' does not exist on disk.
        hint: Run `csgo2cs2 tools install` or update the path in config.
[ERROR] cs2_addons_path_not_writable: cs2_addons_path = C:\...\game\csgo_addons is not writable.
        hint: Close CS2 and Hammer 2 if open. On Windows, if the install lives under
              Program Files, run your terminal as Administrator.
```

`--skip-preflight` (or `CSGO2CS2_SKIP_PREFLIGHT=1`) bypasses it for
users who know what they are doing.

### Stage-resume

The port pipeline runs six stages: `download`, `inspect`, `extract`,
`decompile`, `analyze`, and `import`. Each stage's status is recorded
into `<workspace>/<workshop_id>/manifest.json` under a `stages` block:

```json
{
  "stages": {
    "download": {"status": "done", "started_at": ..., "ended_at": ..., "detail": "..."},
    "decompile": {"status": "failed", "detail": "BSPSource JVM crash"}
  }
}
```

If the importer dies on a 4 GB workshop map, you can re-run the exact
same `port` command and only the failed stages re-run. Two flags
override the default behavior:

- `--restart` — wipe prior stage state and start from scratch.
- `--no-resume` — re-run every stage but keep the existing manifest.

The pipeline also prints a stage summary at the end so it is obvious
where time went:

```
Stage summary:
  download    done         3.2s
  inspect     done         0.0s
  extract     done         0.4s
  decompile   done        93.1s
  analyze     done         0.1s
  import      done        14.7s
```

### Retry and backoff

The pipeline wraps the known-flakey operations (SteamCMD workshop
download, BSPSource decompile) in an exponential-backoff retry loop.
`steamcmd_retries` in your config controls the SteamCMD attempt
count (default 3); BSPSource gets 2 attempts. Transient failures
("workshop item temporarily unavailable", "Java did not start") retry
without user intervention.

### Run logs

Every invocation (except short-lived `about`, `completion`, `explain`)
tees its full stdout, stderr, and any subprocess output to
`<workspace>/logs/<run-id>.log`. The last 25 logs are kept and older
ones are pruned automatically. When something breaks at 2 a.m. you
have one file to share. ANSI color codes are stripped from the log
copy so the file pastes cleanly into a GitHub issue.

Set `CSGO2CS2_NO_LOG=1` if you want to disable run-log capture for a
single run.

### Error remediation hints

Subprocess output (SteamCMD, BSPSource, the import script, bspzip,
VPKEdit) is matched against a registry of known error patterns. When
a pattern matches, the tool prints the matching hint right after
the error:

```
[warn] SteamCMD exit code: 1
[warn] hint (steam_login_denied): SteamCMD needs Steam Guard. Run
       `steamcmd +login <username>` once interactively to cache
       credentials, then re-run `csgo2cs2 port`.
```

The registry covers the predictable failure modes: Steam Guard
prompts, rate limiting, disk full, Java missing, BSPSource JVM
crashes, bspProtect protection, the importer's `.decode()`
AttributeError on un-patched installs, vpk.signatures permission
errors, paths with spaces, and a few more.

### Bug reports

`csgo2cs2 bug-report` collects everything I would otherwise have to
ask you to send me into a single zip:

```bash
csgo2cs2 bug-report                          # default: <workspace>/bug-reports/bug-report-<ts>.zip
csgo2cs2 bug-report -o /tmp/report.zip       # custom output path
csgo2cs2 bug-report --logs 3 --manifests 2   # tune what gets included
```

Contents: `summary.json` (csgo2cs2 version, Python version, platform,
argv, generated_at), `env.txt` (sanitized — Steam Guard codes, API
keys, and anything matching the secret pattern is replaced with
`<redacted>`), `config.json` (without password fields, which the tool
never stores), `doctor.json` (the structured doctor output),
`drift.json` if the workspace has one, the most recent run logs under
`logs/`, and the most recent port manifests under `manifests/`.

Attach the resulting zip to the issue and the failure mode is
reproducible without back-and-forth.

### Selftest

`csgo2cs2 selftest` runs a synthetic end-to-end test of the
analyze/fix pipeline. It does **not** touch Steam, CS2, the
filesystem outside a tempdir, or any external tool. It runs in under
a second and checks:

- the analyzer detects the documented issues in a known-bad VMF
- the fixers apply and produce a structurally sound output
- atomic writes survive a thread race
- the manifest round-trips its stage state through save/load

`--with-tools` adds a smoke test that invokes `steamcmd +quit` and
`bspsource --help` to verify the configured external tools are
actually runnable. Useful before pointing real maps at the pipeline:

```bash
csgo2cs2 selftest                  # 7 internal checks, <1s
csgo2cs2 selftest --with-tools     # also confirms SteamCMD/BSPSource start
```

### Windows long-path handling

On Windows, paths over 260 characters (MAX_PATH) fail in most
subprocess tools we shell out to. The preflight check warns when
`workspace_dir` is close to the safe budget (200 chars), and the
recommendation is always the same: move `workspace_dir` to a short
root like `C:\csgo2cs2`. Internal I/O uses the `\\?\` extended-path
prefix on Windows to dodge the limit where possible, but external
tools generally lack the long-path manifest, so the only reliable fix
is a short workspace root.

### Atomic writes

All manifests, configs, and drift state are written via
`tempfile-then-rename` so a power loss or Ctrl-C mid-write cannot
corrupt them. The previous contents survive any rename failure.

## Live integration test

The regular `pytest -q` suite mocks every external tool, which means a
Steam-side regression (Workshop API contract change, anonymous download
throttle, BSPSource JAR update breakage, SteamCMD output drift)
wouldn't be caught until a user hits it. The `tests/integration/`
directory holds a small, opt-in live test that exercises the real
`SteamCMD → BSPSource → analyze_vmf` chain against a public CS:GO
workshop map.

The live test is gated behind `CSGO2CS2_LIVE_TEST=1`. Without that env
var set, `pytest -q` skips both live tests with no side effects, no
network calls, and no external tool requirements.

```bash
# normal: live tests skipped
pytest -q tests/integration/         # 2 skipped

# opt-in locally (requires steamcmd + java + bspsource on the host):
CSGO2CS2_LIVE_TEST=1 pytest -q tests/integration/

# override the default workshop map if Steam ever drops it:
CSGO2CS2_LIVE_TEST=1 \
CSGO2CS2_LIVE_TEST_WORKSHOP_ID=419404847 \
  pytest -q tests/integration/

# override the per-download timeout (default 600s):
CSGO2CS2_LIVE_TEST_TIMEOUT=900 pytest -q tests/integration/
```

The live job runs in GitHub Actions on push to `main`, on a weekly
schedule (Saturday 04:17 UTC), via manual `workflow_dispatch`, and on
PRs whose title contains `[live-test]`. It is intentionally **not**
gated on every PR — Steam is flaky enough that running the live test
on every commit produces enough false reds to be noise.

Steam-side transients (rate limits, "workshop item temporarily
unavailable", login throttles) are reported as `xfail`, not `fail`, so
a bad Steam day cannot break CI. Real regressions in our adapter glue
(wrong path, contract drift, BSPSource invocation broken) come through
as normal failures. *Permanent* workshop errors (item deleted, ID
invalid, "Access Denied") fail loudly rather than xfail-quietly, since
the right fix is to pick a different default map rather than retry.

The first run of the live test caught two real production bugs that
PR8 also fixes:

- `tools install` on Linux extracted the bundled JRE under
  `bspsource/bin/` without preserving the +x bit, so `bspsrc.sh` died
  with `bin/java: Permission denied` on every Linux install.
  `_extract_archive` now restores the POSIX permissions stored in
  the zip entry's `external_attr`.
- The BSPSource adapter passed the output *directory* to `bspsrc -o`,
  which the tool treats as a *file path* when only one BSP is
  provided. The decompile succeeded silently and produced no `.vmf`.
  The adapter now composes the explicit `<dir>/<bsp.stem>.vmf` path.

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
    walkthrough_cmd.py   # csgo2cs2 walkthrough (alias: tour)
    bug_report_cmd.py    # csgo2cs2 bug-report -> diagnostic zip
    selftest_cmd.py      # csgo2cs2 selftest (synthetic pipeline test)
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
                         #   tools_registry, workshop_meta, addoninfo, drift,
                         #   atomic, long_path, retry, run_log, known_errors,
                         #   preflight helpers
tests/                   # pytest suite (mocked; runs on every PR)
  integration/           # live Steam + BSPSource tests; gated on CSGO2CS2_LIVE_TEST=1
  fixtures/              # check-in VMF samples for snapshot tests
```
