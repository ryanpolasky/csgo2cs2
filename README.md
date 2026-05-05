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
  -> BSP inspector          (sanity + bspprotect detection)
  -> VPKEdit / BSPZIP       (extract packed bsp content)
  -> BSPSource              (decompile .bsp -> .vmf)
  -> VMF analyzer + fixers  (skybox, unsupported entities, paths)
  -> stage <s1_content>/maps/<mapname>.vmf  (no spaces in path)
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
csgo2cs2 download "<workshop-url-or-id>"        # download via steamcmd
csgo2cs2 decompile <bsp-path>                   # bspsource decompile
csgo2cs2 analyze <vmf-path>                     # report vmf issues
csgo2cs2 analyze <vmf-path> --fix               # apply auto-fixes (skybox, entities)
csgo2cs2 port "<workshop-url-or-id>" --addon my_addon --auto   # full pipeline (windows)
csgo2cs2 port --bsp ./local.bsp --addon my_addon --auto        # skip steamcmd, use a local file
csgo2cs2 port "<workshop-url-or-id>" --addon my_addon --skip-import   # cross-os dry run
csgo2cs2 list                                   # list prior ports under workspace_dir
csgo2cs2 status "<workshop-url-or-id>"          # show one port's manifest
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
    tools_cmd.py
    download.py
    decompile.py
    analyze.py
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
    bsp.py               # bsp header + protection sniff
  fixers/                # registered auto-fixers
    base.py              # registry + apply_all
    skybox.py
    entities.py
  utils/                 # url, paths, backup, manifest, steam, downloader,
                         #   tools_registry helpers
tests/                   # pytest suite
```
