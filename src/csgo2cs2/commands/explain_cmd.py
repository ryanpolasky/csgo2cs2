# csgo2cs2 explain <issue_id>  (or --list)

from __future__ import annotations

import argparse

from ..analyzers import explain as explain_mod
from ..logging_utils import error, info


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "explain",
        help="Explain a finding's issue_id (what / why / how to fix).",
    )
    p.add_argument(
        "issue_id",
        nargs="?",
        default=None,
        help="An issue_id from `csgo2cs2 analyze` output.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List every issue_id with a curated explanation.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    if args.list or not args.issue_id:
        ids = explain_mod.known_ids()
        info(f"{len(ids)} known issue_id(s):")
        for i in ids:
            exp = explain_mod.get(i)
            assert exp is not None
            print(f"  {i:<32} {exp.title}")
        return 0

    exp = explain_mod.get(args.issue_id)
    if exp is None:
        error(f"Unknown issue_id: {args.issue_id}")
        info("Try `csgo2cs2 explain --list`.")
        return 2

    print(explain_mod.render(exp))
    return 0
