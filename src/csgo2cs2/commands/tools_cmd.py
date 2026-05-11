# `csgo2cs2 tools` --- install / list / show paths for external tools.
#
# pinned downloads land in `~/.csgo2cs2/tools/<tool>/<version>/`.
# successful installs auto-update the user's config to point at the binaries.

from __future__ import annotations

import argparse
import shutil
import stat
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Iterable, List, Tuple

from ..config import DEFAULT_CONFIG_DIR, load_config, save_config
from ..logging_utils import error, header, info, success, warn
from ..utils.downloader import DownloadError, fetch
from ..utils.tools_registry import (
    ToolDownload,
    bspsource_download,
    current_platform,
    import_map_community_repo_archive,
    steamcmd_download,
)

ALL_TOOLS = ("bspsource", "steamcmd", "import_map_community")


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "tools",
        help="Install and manage external tools (BSPSource, SteamCMD, etc.).",
    )
    sub = p.add_subparsers(dest="tools_command", required=True)

    p_install = sub.add_parser(
        "install",
        help="Download and configure an external tool into the local cache.",
    )
    p_install.add_argument(
        "tools",
        nargs="*",
        help=f"One or more of: {', '.join(ALL_TOOLS)}, all (default: all)",
    )
    p_install.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if the tool is already cached.",
    )
    p_install.set_defaults(func=run_install)

    p_list = sub.add_parser(
        "list",
        help="Show installed tools and where they live.",
    )
    p_list.set_defaults(func=run_list)

    p_path = sub.add_parser(
        "path",
        help="Print the configured path for a single tool, or empty if unset.",
    )
    p_path.add_argument("tool", choices=ALL_TOOLS)
    p_path.set_defaults(func=run_path)


def _tools_root() -> Path:
    return DEFAULT_CONFIG_DIR / "tools"


def _resolve_targets(requested: Iterable[str]) -> List[str]:
    items = [t.lower() for t in requested]
    if not items or "all" in items:
        return list(ALL_TOOLS)
    bad = [t for t in items if t not in ALL_TOOLS]
    if bad:
        raise SystemExit(f"Unknown tool(s): {', '.join(bad)}. Choose from: {', '.join(ALL_TOOLS)}")
    return items


def _extract_archive(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if name.endswith(".zip"):
        # zipfile.extractall discards POSIX perms; restore the +x bit
        # for any file the zip explicitly stored as executable.
        # this matters for tools like bspsource that ship a bundled
        # jre under bin/, where bin/java needs +x to actually run.
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                out_path = Path(zf.extract(info, dest))
                if sys.platform.startswith("win") or info.is_dir():
                    continue
                perm = (info.external_attr >> 16) & 0o777
                if perm:
                    try:
                        out_path.chmod(perm)
                    except OSError:
                        pass
        return
    if name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest)
        return
    raise RuntimeError(f"Unknown archive type: {archive.name}")


def _make_executable(path: Path) -> None:
    if sys.platform.startswith("win"):
        return
    try:
        st = path.stat()
        path.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


# install a single tool entry. returns (config_attr, resolved_path).
def _install_tool(tool: str, force: bool) -> Tuple[str, Path] | None:
    plat = current_platform()
    cache_root = _tools_root() / tool
    cache_root.mkdir(parents=True, exist_ok=True)

    if tool == "bspsource":
        spec = bspsource_download().get(plat)
        if not spec:
            warn(f"bspsource: no download available for platform {plat}")
            return None
        return _install_archive_tool(tool, spec, cache_root, "bspsource_path", force)

    if tool == "steamcmd":
        spec = steamcmd_download().get(plat)
        if not spec:
            warn(f"steamcmd: no download available for platform {plat}")
            return None
        return _install_archive_tool(tool, spec, cache_root, "steamcmd_path", force)

    if tool == "import_map_community":
        spec = import_map_community_repo_archive()
        return _install_archive_tool(tool, spec, cache_root, "import_script_path", force)

    warn(f"Don't know how to install {tool}")
    return None


def _install_archive_tool(
    tool: str,
    spec: ToolDownload,
    cache_root: Path,
    config_attr: str,
    force: bool,
) -> Tuple[str, Path] | None:
    archive = cache_root / spec.filename
    extract_dir = cache_root / "extracted"

    if extract_dir.exists() and not force:
        info(f"{tool}: already extracted at {extract_dir}; skipping (use --force to reinstall)")
    else:
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        try:
            info(f"{tool}: downloading {spec.url}")
            fetch(spec.url, archive, name=tool)
        except DownloadError as exc:
            error(f"{tool}: {exc}")
            return None
        info(f"{tool}: extracting to {extract_dir}")
        try:
            _extract_archive(archive, extract_dir)
        except Exception as exc:  # noqa: BLE001
            error(f"{tool}: extract failed: {exc}")
            return None

    binary = _find_binary(extract_dir, spec.binary_subpath)
    if not binary:
        error(f"{tool}: could not locate `{spec.binary_subpath}` under {extract_dir}")
        return None
    _make_executable(binary)
    success(f"{tool}: ready at {binary}")
    return config_attr, binary


def _find_binary(root: Path, subpath: str | None) -> Path | None:
    if not subpath:
        return None
    direct = root / subpath
    if direct.exists():
        return direct
    # repo archives extract to a single nested folder like
    # `cs2-import-scripts-main/`. peek one level deeper.
    for child in root.iterdir():
        if child.is_dir():
            candidate = child / subpath
            if candidate.exists():
                return candidate
    # fall back to a recursive search for the basename
    target = Path(subpath).name
    for found in root.rglob(target):
        if found.is_file():
            return found
    return None


def _persist_config_paths(config_path: str | None, updates: List[Tuple[str, Path]]) -> None:
    if not updates:
        return
    cfg = load_config(config_path)
    for attr, path in updates:
        setattr(cfg, attr, str(path))
    saved = save_config(cfg, config_path)
    info(f"Updated config: {saved}")


def run_install(args: argparse.Namespace) -> int:
    targets = _resolve_targets(args.tools)
    header(f"Installing: {', '.join(targets)}")

    updates: List[Tuple[str, Path]] = []
    failures: List[str] = []
    for tool in targets:
        result = _install_tool(tool, force=args.force)
        if result is None:
            failures.append(tool)
            continue
        updates.append(result)

    _persist_config_paths(args.config, updates)

    header("Summary")
    for attr, path in updates:
        success(f"{attr} -> {path}")
    if failures:
        error(f"Failed: {', '.join(failures)}")
        return 1
    return 0


def run_list(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    header("csgo2cs2 tools")
    info(f"cache: {_tools_root()}")
    rows = [
        ("steamcmd", cfg.steamcmd_path),
        ("bspsource", cfg.bspsource_path),
        ("vpkedit", cfg.vpkedit_path),
        ("bspzip", cfg.bspzip_path),
        ("import_map_community", cfg.import_script_path),
        ("java", cfg.java_path),
    ]
    for name, value in rows:
        marker = "ok " if value and Path(value).exists() else "-- "
        if value:
            info(f"{marker}{name:<22} {value}")
        else:
            info(f"{marker}{name:<22} <not configured>")
    return 0


def run_path(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    attr = {
        "bspsource": "bspsource_path",
        "steamcmd": "steamcmd_path",
        "import_map_community": "import_script_path",
    }[args.tool]
    value = getattr(cfg, attr)
    if value:
        print(value)
    # always exit 0; empty stdout means "unset", which is scriptable
    return 0
