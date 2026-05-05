# csgo2cs2

a python cli for porting cs:go workshop maps to cs2 through one scripted
workflow. it wraps steamcmd, bspsource, vpkedit/bspzip, and valve's
`import_map_community.py` behind one command.

## Status

alpha scaffolding. the boring parts (url parsing, download, decompile, analyze)
should run anywhere. the full `port` pipeline needs windows because the cs2
import bits (`vbsp.exe -prepfors2`, `import_map_community.py`, cs2 workshop
tools) live there.

## Architecture

```
workshop url
  -> SteamCMD               (download workshop item)
  -> BSP inspector          (sanity + bspprotect detection)
  -> VPKEdit / BSPZIP       (extract packed bsp content)
  -> BSPSource              (decompile .bsp -> .vmf)
  -> VMF analyzer + fixers  (skybox, unsupported entities, paths)
  -> import_map_community.py    (windows-only)
  -> manifest + report      (track install-side mutations)
  -> cleanup                (reverse copies/patches/renames)
```

each external tool gets an adapter under `src/csgo2cs2/tools/`, so tools can be
swapped without rewriting the pipeline. fixers self-register against analyzer
`issue_id`s in `src/csgo2cs2/fixers/`, which keeps new auto-fixes small.

## Prerequisites

the cli runs on any os, but the full porting pipeline needs windows plus these
external tools:

- **python 3.10+** on PATH
- **SteamCMD** (anonymous downloads for app `730` are flaky; account login is
  often needed)
- **java jre** (bspsource is java-based)
- **BSPSource** (`bspsrc.jar` or wrapper script)
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
csgo2cs2 init                                   # create config file
csgo2cs2 doctor                                 # check tools and prereqs
csgo2cs2 doctor --fix                           # apply install patches with backups
csgo2cs2 download "<workshop-url-or-id>"        # download via steamcmd
csgo2cs2 decompile <bsp-path>                   # bspsource decompile
csgo2cs2 analyze <vmf-path>                     # report vmf issues
csgo2cs2 analyze <vmf-path> --fix               # apply auto-fixes (skybox, entities)
csgo2cs2 port "<workshop-url-or-id>" --addon my_addon --auto   # full pipeline (windows)
csgo2cs2 port "<workshop-url-or-id>" --addon my_addon --skip-import   # cross-os dry run
csgo2cs2 cleanup "<workshop-url-or-id>"         # undo install-side mutations
csgo2cs2 cleanup "<workshop-url-or-id>" --dry-run
```

## Known Limitations

- **windows-only `port`.** decompile fidelity is bounded by BSPSource: brushwork,
  displacements, and area portals are imperfectly recovered.
- **`bspProtect`-protected maps** cannot be decompiled cleanly; the analyzer
  flags these.
- **nav meshes, radar, soundscapes, cubemaps, and lighting** do not transfer
  cleanly and need to be regenerated in Hammer 2.
- **anonymous steamcmd downloads** for app `730` are unreliable; an authenticated
  Steam login may be required.

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
    download.py
    decompile.py
    analyze.py
    port.py
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
    bsp.py               # bsp header + protection sniff
  fixers/                # registered auto-fixers
    base.py              # registry + apply_all
    skybox.py
    entities.py
  utils/                 # url, paths, backup, manifest helpers
tests/                   # pytest suite
```
