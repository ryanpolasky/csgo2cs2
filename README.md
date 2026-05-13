# csgo2cs2 — `port-bulk` feature

Self-contained Python script that adds the `csgo2cs2 port-bulk`
subcommand (+ tests + docs) to a csgo2cs2 checkout. No `.patch` files,
no `git apply`, no extra deps. Cross-platform (Windows/Linux/macOS).

## Usage

```cmd
cd D:\PyCharmProjects\csgo2cs2
python C:\path\to\this\zip\apply_port_bulk.py
:: or with an explicit repo path:
python C:\path\to\this\zip\apply_port_bulk.py D:\PyCharmProjects\csgo2cs2
```

Then commit + push:

```cmd
pytest -q                              :: 580 passed, 2 skipped (+20 new)
ruff check src/ tests/                 :: All checks passed!
ruff format --check src tests          :: 128 files already formatted
git add -A
git commit -m "feat: add port-bulk command for batching workshop IDs"
git push
```

## What the script does

1. Writes `src/csgo2cs2/commands/port_bulk.py` (~430 lines, new file)
2. Writes `tests/test_port_bulk.py` (~460 lines, new file, 20 tests)
3. Inserts 2 lines into `src/csgo2cs2/cli.py`:
   - `from .commands import port_bulk as cmd_port_bulk`
   - `cmd_port_bulk.register(sub)` inside `build_parser()`
4. Adds 8 lines to the `## Usage` cheatsheet in `README.md` (port-bulk
   examples in the same style as the existing `port` lines)
5. Adds a new `## Bulk porting` section to `README.md` (~50 lines:
   behavior, addon-naming, skip-already-ported, manifest, exit codes)

## Safety

- **Idempotent.** Re-running the script on an already-patched checkout
  prints four `[skip]` lines and exits 0. Safe to run twice.
- **Anchor-based.** Uses unique substrings to find the right insertion
  point. If the anchors aren't found (e.g., you have local
  modifications), the script either errors out (for cli.py — required)
  or warns (for README.md — optional cosmetic block).
- **Verified on a fresh clone of `origin/main`.** The script reproduces
  byte-identical output to my Devin-side branch on this commit:
  `61eb712 (HEAD -> main, origin/main) Ruff fixes`.

## Test counts

| | Before | After |
|---|---|---|
| Tests | 560 | 580 (+20 new) |
| ruff check | ok | ok |
| ruff format --check | ok | ok |

## Resulting commands

```cmd
csgo2cs2 port-bulk 419404847 1129516277 --auto
csgo2cs2 port-bulk --from-file workshop_ids.txt --auto
csgo2cs2 port-bulk <ids...> --auto --continue-on-failure --overwrite
csgo2cs2 port-bulk <ids...> --dry-run --addon-template "{workshop_id}"
csgo2cs2 port-bulk <ids...> --manifest bulk.json
csgo2cs2 port-bulk --help
```

See the new "Bulk porting" section of the repo's README for full
behavior + flag docs.
