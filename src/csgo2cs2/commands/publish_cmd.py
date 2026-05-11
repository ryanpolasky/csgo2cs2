# `csgo2cs2 publish <addon>` --- package the imported addon dir into a
# workshop-upload-ready zip + run structural sanity checks.
#
# scope: this command does NOT actually upload to Steam Workshop. that
# requires browser-side auth + sdk pieces we deliberately don't pull in.
# what we do is:
#   1. resolve the addon dir under <install>/game/csgo_addons/<addon>
#   2. run the same structural checks `verify` does (`.vmap` exists,
#      `addoninfo.{json,gi,txt}` parses, asset refs resolve)
#   3. produce a clean zip the user can drop into Workshop Tools
#
# the zip layout matches what cs2's upload tooling expects: the addon
# dir contents at the zip root (so unpacking the zip into csgo_addons/
# yields a usable addon directory).

from __future__ import annotations

import argparse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from ..config import Config, load_config
from ..logging_utils import error, header, info, success, warn
from .verify_cmd import VerifyReport, verify_addon

# files we never include in the upload zip. these are either editor /
# build artifacts that bloat the archive, or csgo2cs2-private files (e.g.
# our preview-download tempfile sentinels) that have no business being
# shipped to other users.
_DEFAULT_EXCLUDES = (
    "*.bak",
    "*.csgo2cs2.bak",
    "_csgo2cs2_*",  # tempfiles
    ".DS_Store",
    "Thumbs.db",
    "*.tmp",
)


@dataclass
class PublishReport:
    addon_dir: Path
    zip_path: Path
    file_count: int
    skipped: List[str]
    verify: VerifyReport


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "publish",
        help="Package an addon directory into an upload-ready .zip.",
    )
    p.add_argument("addon", help="cs2 addon directory name (under csgo_addons/).")
    p.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output zip path. Defaults to <addon>.zip in the workspace dir.",
    )
    p.add_argument(
        "--map",
        dest="mapname",
        default=None,
        help="Map name used by --verify (default: auto-detect from maps/*.vmap).",
    )
    p.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip the structural sanity checks; package only.",
    )
    p.add_argument(
        "--allow-errors",
        action="store_true",
        help=(
            "Build the zip even if verify reports errors. Default behavior is "
            "to abort on errors so you don't ship a broken addon."
        ),
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    from .launch_cmd import resolve_addon_dir

    addon_dir = resolve_addon_dir(cfg, args.addon)
    if addon_dir is None:
        error(f"Cannot resolve addon dir for {args.addon!r}; check cs2_addons_path in config.")
        return 2
    if not addon_dir.exists():
        error(f"Addon dir does not exist: {addon_dir}")
        return 2

    # structural checks — same code path as `verify`
    if not args.skip_verify:
        header("Verifying addon")
        report = verify_addon(cfg, args.addon, args.mapname)
        for issue in report.issues:
            level = (
                warn if issue.severity == "warn" else (error if issue.severity == "error" else info)
            )
            level(f"{issue.severity}: {issue.message}")
        if report.has_errors and not args.allow_errors:
            error(
                "Aborting publish: verify reported errors. Re-run with --allow-errors to override."
            )
            return 1
    else:
        # build a synthetic empty report so the dataclass invariants hold
        report = VerifyReport(addon_dir=addon_dir, issues=[])

    out_zip = _resolve_output_path(cfg, args.addon, args.output)
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    header(f"Packaging -> {out_zip}")
    file_count, skipped = _build_zip(addon_dir, out_zip)
    success(f"Wrote {out_zip} ({file_count} files, {_human_size(out_zip.stat().st_size)})")
    if skipped:
        info(f"skipped {len(skipped)} excluded files (build artifacts / tempfiles)")

    return 0


def _resolve_output_path(cfg: Config, addon: str, override: str | None) -> Path:
    if override:
        return Path(override).expanduser()
    workspace = Path(cfg.workspace_dir).expanduser()
    return workspace / f"{addon}.zip"


def _build_zip(addon_dir: Path, out_zip: Path) -> Tuple[int, List[str]]:
    file_count = 0
    skipped: List[str] = []
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(addon_dir.rglob("*")):
            if not path.is_file():
                continue
            if _is_excluded(path):
                skipped.append(str(path.relative_to(addon_dir)))
                continue
            arcname = str(path.relative_to(addon_dir)).replace("\\", "/")
            zf.write(path, arcname=arcname)
            file_count += 1
    return file_count, skipped


def _is_excluded(path: Path) -> bool:
    name = path.name
    for pattern in _DEFAULT_EXCLUDES:
        if path.match(pattern) or name == pattern:
            return True
    # also drop our previous publish output if it's nested in the addon
    if name.endswith(".zip") and name.startswith(path.parent.name):
        return True
    return False


def _human_size(n: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.1f} {u}"
        f /= 1024
    return f"{n} B"
