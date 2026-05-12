# `csgo2cs2 verify <addon>` --- post-port sanity check.
#
# the cs2 import script can succeed and still leave you with a broken
# addon — missing materials, broken `addoninfo.gi`, no `.vmap`, etc. you
# only find out by loading cs2, seeing purple/black checkers, and
# digging through the workshop tools logs.
#
# this command catches that offline. cross-platform (no `cs2.exe`
# required), runs in well under a second.

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

from ..config import Config, load_config
from ..logging_utils import error, info, success, warn

# substrings of asset path keys we expect to see in a .vmap. this isn't
# a strict KV parser — vmap is an arbitrary-keytype valve resource format
# and parsing it properly would require Source 2 sdk bindings.
# instead we do a regex-level scan and probe a sample.
_ASSET_REF_RE = re.compile(r'"[^"]*\.(?:vmat|vmdl|vsnd|vmdl_c|vmat_c|vsnd_c)"', re.IGNORECASE)

# how many sampled asset refs to actually probe on disk. avoids exploding
# on huge maps.
_ASSET_SAMPLE_LIMIT = 50


@dataclass
class VerifyIssue:
    severity: str  # "error" | "warn" | "info"
    message: str

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


@dataclass
class VerifyReport:
    addon_dir: Path
    issues: List[VerifyIssue]

    @property
    def has_errors(self) -> bool:
        return any(i.is_error for i in self.issues)


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "verify",
        help="Post-port sanity check for a cs2 addon directory.",
    )
    p.add_argument("addon", help="cs2 addon directory name (under csgo_addons/).")
    p.add_argument(
        "--map",
        dest="mapname",
        default=None,
        help="Map name to verify (default: auto-detect from maps/*.vmap).",
    )
    p.set_defaults(func=run)


def _resolve_addon_dir(cfg: Config, addon: str) -> Path | None:
    # share the path-resolution logic with launch_cmd by importing.
    # avoids drift between the two commands.
    from .launch_cmd import resolve_addon_dir

    return resolve_addon_dir(cfg, addon)


def _check_vmap(addon_dir: Path, mapname: str | None) -> tuple[Path | None, List[VerifyIssue]]:
    issues: List[VerifyIssue] = []
    maps_dir = addon_dir / "maps"
    if not maps_dir.is_dir():
        issues.append(VerifyIssue("error", f"No maps/ directory under {addon_dir}"))
        return None, issues
    vmaps = sorted(maps_dir.glob("*.vmap"))
    if not vmaps:
        issues.append(VerifyIssue("error", f"No .vmap files under {maps_dir}"))
        return None, issues
    if mapname:
        chosen = maps_dir / f"{mapname}.vmap"
        if not chosen.exists():
            issues.append(
                VerifyIssue(
                    "error",
                    f"--map {mapname!r} not found; available: {[v.stem for v in vmaps]}",
                )
            )
            return None, issues
        return chosen, issues
    if len(vmaps) > 1:
        issues.append(
            VerifyIssue(
                "warn",
                f"Multiple .vmap files found ({[v.stem for v in vmaps]}); "
                "verifying the first. Pass --map to be specific.",
            )
        )
    return vmaps[0], issues


def _check_addoninfo(addon_dir: Path) -> List[VerifyIssue]:
    # cs2 accepts a few names; try them in priority order.
    candidates = [
        addon_dir / "addoninfo.gi",
        addon_dir / "addoninfo.json",
        addon_dir / "addoninfo.txt",
    ]
    found = [c for c in candidates if c.exists()]
    if not found:
        return [VerifyIssue("warn", "No addoninfo.{gi,json,txt} found; cs2 will use defaults.")]
    info_path = found[0]
    text = info_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return [VerifyIssue("warn", f"{info_path.name} exists but is empty.")]
    # if it's json (one of the formats valve allows for community addons),
    # actually parse it.
    if info_path.suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            return [VerifyIssue("error", f"{info_path.name} is malformed JSON: {exc}")]
    return []


def _check_assets(addon_dir: Path, vmap: Path) -> List[VerifyIssue]:
    try:
        text = vmap.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [VerifyIssue("error", f"Cannot read {vmap}: {exc}")]
    refs = _ASSET_REF_RE.findall(text)
    if not refs:
        return [
            VerifyIssue("info", "No external material/model refs found in .vmap (likely fine).")
        ]
    issues: List[VerifyIssue] = []
    sampled = list(dict.fromkeys(refs))[:_ASSET_SAMPLE_LIMIT]  # de-dupe + cap
    missing: List[str] = []
    for ref in sampled:
        rel = ref.strip('"')
        # vmat/vmdl/vsnd in source content -> we look for the _compiled_ equivalent
        # under addon_dir (e.g. materials/foo.vmat -> materials/foo.vmat_c). we
        # accept either form.
        compiled = rel + "_c"
        if not (addon_dir / rel).exists() and not (addon_dir / compiled).exists():
            missing.append(rel)
    if missing:
        head = ", ".join(missing[:5])
        more = "" if len(missing) <= 5 else f" (+{len(missing) - 5} more)"
        issues.append(
            VerifyIssue(
                "error",
                f"{len(missing)} of {len(sampled)} sampled asset refs not found "
                f"under {addon_dir}: {head}{more}",
            )
        )
    else:
        issues.append(VerifyIssue("info", f"All {len(sampled)} sampled asset refs resolved."))
    return issues


def verify_addon(cfg: Config, addon: str, mapname: str | None = None) -> VerifyReport:
    issues: List[VerifyIssue] = []
    addon_dir = _resolve_addon_dir(cfg, addon)
    if addon_dir is None or not addon_dir.is_dir():
        issues.append(VerifyIssue("error", f"Addon directory not found: {addon_dir}"))
        return VerifyReport(addon_dir or Path(addon), issues)

    vmap, vmap_issues = _check_vmap(addon_dir, mapname)
    issues.extend(vmap_issues)
    issues.extend(_check_addoninfo(addon_dir))
    if vmap is not None:
        issues.extend(_check_assets(addon_dir, vmap))
    return VerifyReport(addon_dir, issues)


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    report = verify_addon(cfg, args.addon, args.mapname)

    info(f"Verifying addon: {report.addon_dir}")
    for issue in report.issues:
        if issue.severity == "error":
            error(issue.message)
        elif issue.severity == "warn":
            warn(issue.message)
        else:
            info(issue.message)

    if report.has_errors:
        warn(f"Verification FAILED for `{args.addon}`.")
        return 1
    success(f"Verification passed for `{args.addon}`.")
    return 0
