# Manage CS2 workshop addon directories without Workshop Tools.

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_config
from ..logging_utils import error, info, success, warn
from ..tools.addon_scaffold import addon_dir
from ..tools.addon_scaffold import create as scaffold_create
from ..tools.addon_scaffold import inspect as inspect_addon


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "addon",
        help="Manage CS2 workshop addon directories (create, list, delete).",
    )
    sub = p.add_subparsers(dest="addon_command", required=True)

    create = sub.add_parser(
        "create",
        help="Scaffold a CS2 addon directory (addoninfo.gi + empty maps/).",
    )
    create.add_argument("name", help="Addon name; must match what you'll pass to --addon.")
    create.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing addon dir's addoninfo.gi.",
    )
    create.set_defaults(func=_run_create)

    list_p = sub.add_parser("list", help="List existing CS2 addons.")
    list_p.set_defaults(func=_run_list)

    delete = sub.add_parser("delete", help="Remove a CS2 addon directory and all its contents.")
    delete.add_argument("name", help="Addon name to delete.")
    delete.add_argument(
        "--force",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    delete.set_defaults(func=_run_delete)


def _run_create(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    try:
        d = scaffold_create(cfg, args.name, force=args.force)
    except FileExistsError as exc:
        error(str(exc))
        info("Pass --force to overwrite an existing addoninfo.gi.")
        return 1
    except RuntimeError as exc:
        error(str(exc))
        return 1
    success(f"Created addon {args.name!r} at {d}.")
    info("Next: `csgo2cs2 port <workshop_id> --addon " + args.name + " --auto`")
    return 0


def _run_list(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if not cfg.cs2_addons_path:
        error("cs2_addons_path is not set. Run `csgo2cs2 init --interactive` first.")
        return 1
    root = Path(cfg.cs2_addons_path).expanduser()
    if not root.exists():
        warn(f"cs2_addons_path does not exist: {root}")
        return 1
    addons = sorted([p for p in root.iterdir() if p.is_dir()])
    if not addons:
        info(f"No addons found under {root}.")
        return 0
    info(f"Addons under {root}:")
    for d in addons:
        state = inspect_addon(cfg, d.name)
        if state is None:
            continue
        tag = "scaffolded" if state.scaffolded_by_csgo2cs2 else "manual/WT"
        if state.has_prior_port_output:
            details = f"{state.map_count} file(s) under maps/"
        elif state.is_scaffolded:
            details = "empty (ready to port into)"
        elif state.has_addoninfo:
            details = "has addoninfo.gi"
        else:
            details = "no addoninfo.gi (broken?)"
        print(f"  {d.name:<32} [{tag:<10}] {details}")
    return 0


def _run_delete(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    d = addon_dir(cfg, args.name)
    if d is None:
        error("cs2_addons_path is not set. Run `csgo2cs2 init --interactive` first.")
        return 1
    if not d.exists():
        warn(f"Addon {args.name!r} does not exist at {d}; nothing to do.")
        return 0
    state = inspect_addon(cfg, args.name)
    if state is not None and state.has_prior_port_output and not args.force:
        warn(
            f"{d} contains {state.map_count} file(s) under maps/ from a prior "
            "port. Re-run with --force to confirm deletion."
        )
        return 1
    if not args.force:
        try:
            answer = input(f"Delete {d}? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            info("")
            return 1
        if answer not in {"y", "yes"}:
            info("Cancelled.")
            return 1
    import shutil

    shutil.rmtree(d)
    success(f"Deleted {d}.")
    return 0

