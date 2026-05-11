# `csgo2cs2 bug-report` --- bundle diagnostic info for a github issue.
#
# Produces `<workspace>/bug-reports/bug-report-<timestamp>.zip` with:
#   - csgo2cs2 version + python version + platform info
#   - sanitized environment (no Steam Guard codes, no passwords)
#   - doctor --json output
#   - last N run logs
#   - the manifests for the last K workshop dirs
#   - the drift state file (if any)
#
# Designed to make "what did you run, what failed" reproducible without
# the user having to scroll back through their terminal.

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import re
import sys
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .. import __version__
from ..config import Config, load_config
from ..logging_utils import error, header, info, success, warn
from ..utils.drift import DRIFT_STATE_FILENAME

# Env var names we never write to the bundle, full stop. Includes the
# standard secret names plus any Steam Guard / auth shortcut we know
# about.
_FORBIDDEN_ENV = {
    "STEAM_GUARD",
    "STEAM_PASSWORD",
    "STEAMPW",
    "STEAM_API_KEY",
    "GITHUB_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
}

# Loose pattern fallback: any env var name containing one of these
# substrings gets redacted to "<redacted>".
_REDACT_SUBSTRINGS = ("TOKEN", "PASSWORD", "PASSWD", "SECRET", "API_KEY", "AUTH")


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "bug-report",
        help="Bundle diagnostic info into a zip for a github issue.",
    )
    p.add_argument(
        "--output",
        "-o",
        metavar="PATH",
        default=None,
        help="Output zip path (default: <workspace>/bug-reports/bug-report-<ts>.zip).",
    )
    p.add_argument(
        "--logs",
        type=int,
        default=5,
        help="Include this many of the most recent run logs (default: 5).",
    )
    p.add_argument(
        "--manifests",
        type=int,
        default=5,
        help="Include manifests from up to this many workshop dirs (default: 5).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    workspace = Path(cfg.workspace_dir).expanduser()
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    if args.output:
        out = Path(args.output).expanduser()
    else:
        out = workspace / "bug-reports" / f"bug-report-{ts}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)

    header(f"Building bug report: {out}")
    payload = _collect_payload(cfg, workspace, args)
    try:
        _write_zip(out, payload)
    except OSError as exc:
        error(f"Could not write bug report: {exc}")
        return 1
    success(f"Wrote: {out}")
    info("Attach this zip when filing an issue at:")
    info("  https://github.com/ryanpolasky/csgo2cs2/issues")
    info("Contents:")
    for name in sorted(payload.keys()):
        info(f"  {name}")
    return 0


def _collect_payload(
    cfg: Config,
    workspace: Path,
    args: argparse.Namespace,
) -> Dict[str, bytes]:
    out: Dict[str, bytes] = {}

    # summary.json: high-level info
    out["summary.json"] = _bytes_json(_build_summary(cfg))

    # env.txt: sanitized environment variables (relevant ones only)
    out["env.txt"] = _build_env_dump().encode("utf-8")

    # config.json: the loaded config (no secrets in it -- steam_login
    # is a username only, never a password).
    out["config.json"] = _bytes_json(_redact_config(asdict(cfg)))

    # doctor.json: structured doctor output, if doctor command is callable.
    doctor_json = _safe_doctor_json(cfg, args)
    if doctor_json:
        out["doctor.json"] = doctor_json

    # drift state
    drift_path = workspace / DRIFT_STATE_FILENAME
    if drift_path.exists():
        try:
            out["drift.json"] = drift_path.read_bytes()
        except OSError as exc:
            warn(f"Could not include drift state: {exc}")

    # last N run logs
    for name, data in _collect_recent_logs(workspace, limit=args.logs):
        out[f"logs/{name}"] = data

    # last K manifests
    for name, data in _collect_recent_manifests(workspace, limit=args.manifests):
        out[f"manifests/{name}"] = data

    return out


def _bytes_json(obj: Any) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _build_summary(cfg: Config) -> Dict[str, Any]:
    return {
        "csgo2cs2_version": __version__,
        "python_version": sys.version,
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "executable": sys.executable,
        "argv": sys.argv,
        "workspace_dir": cfg.workspace_dir,
        "config_keys_set": _config_keys_set(cfg),
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }


def _config_keys_set(cfg: Config) -> List[str]:
    keys: List[str] = []
    for k, v in asdict(cfg).items():
        if v in (None, "", [], {}):
            continue
        keys.append(k)
    return sorted(keys)


def _redact_config(data: Dict[str, Any]) -> Dict[str, Any]:
    # config.py doesn't store passwords -- steam_login is a username
    # only. We still defensively strip anything that looks like a
    # secret by name.
    out: Dict[str, Any] = {}
    for k, v in data.items():
        if _looks_secret_key(k):
            out[k] = "<redacted>"
        else:
            out[k] = v
    return out


def _looks_secret_key(name: str) -> bool:
    n = name.upper()
    if n in _FORBIDDEN_ENV:
        return True
    return any(s in n for s in _REDACT_SUBSTRINGS)


def _build_env_dump() -> str:
    relevant_prefixes = ("CSGO2CS2_", "STEAM_", "PATH", "JAVA_", "PYTHON", "TEMP", "TMP", "HOME")
    lines = ["# Sanitized environment dump (csgo2cs2, Steam, and language-related vars only)"]
    for k in sorted(os.environ.keys()):
        if not any(k.startswith(p) or k == p for p in relevant_prefixes):
            continue
        if _looks_secret_key(k):
            lines.append(f"{k}=<redacted>")
            continue
        v = os.environ[k]
        # Truncate huge PATH-like values so the file stays readable.
        if len(v) > 2000:
            v = v[:2000] + "...<truncated>"
        lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"


def _safe_doctor_json(cfg: Config, args: argparse.Namespace) -> Optional[bytes]:
    """Invoke `doctor --json` in-process and capture its stdout."""
    try:
        from . import doctor as cmd_doctor
    except ImportError:
        return None

    # build a minimal namespace; doctor's `run` reads args.config etc.
    ns = argparse.Namespace(
        config=getattr(args, "config", None),
        verbose=False,
        command="doctor",
        fix=False,
        unfix=False,
        emit_json=True,
    )
    import contextlib
    import io

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            cmd_doctor.run(ns)
    except Exception as exc:  # noqa: BLE001
        warn(f"doctor --json failed during bug-report collection: {exc}")
        return None
    text = buf.getvalue()
    # try to parse and pretty-print for the bundle; fall back to raw.
    try:
        parsed = json.loads(text)
        return _bytes_json(parsed)
    except json.JSONDecodeError:
        return text.encode("utf-8", errors="replace")


def _collect_recent_logs(
    workspace: Path,
    *,
    limit: int,
) -> Iterable[tuple]:
    logs_dir = workspace / "logs"
    if not logs_dir.is_dir() or limit <= 0:
        return []
    entries = [p for p in logs_dir.iterdir() if p.is_file() and p.suffix == ".log"]
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[tuple] = []
    for p in entries[:limit]:
        try:
            data = p.read_bytes()
        except OSError as exc:
            warn(f"Could not read log {p}: {exc}")
            continue
        out.append((p.name, _sanitize_log_bytes(data)))
    return out


def _collect_recent_manifests(workspace: Path, *, limit: int) -> Iterable[tuple]:
    if not workspace.is_dir() or limit <= 0:
        return []
    # Manifests live at <workspace>/<workshop_id>/manifest.json
    candidates: List[Path] = []
    for child in workspace.iterdir():
        if not child.is_dir():
            continue
        manifest = child / "manifest.json"
        if manifest.is_file():
            candidates.append(manifest)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[tuple] = []
    for m in candidates[:limit]:
        try:
            data = m.read_bytes()
        except OSError as exc:
            warn(f"Could not read manifest {m}: {exc}")
            continue
        out.append((f"{m.parent.name}.manifest.json", data))
    return out


_HOMEDIR_RE = re.compile(re.escape(str(Path.home()))) if str(Path.home()) else None


def _sanitize_log_bytes(data: bytes) -> bytes:
    """Replace user's home dir path with ~ to reduce surface for accidents."""
    if _HOMEDIR_RE is None:
        return data
    try:
        text = data.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return data
    text = _HOMEDIR_RE.sub("~", text)
    return text.encode("utf-8", errors="replace")


def _write_zip(out: Path, payload: Dict[str, bytes]) -> None:
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(payload.items()):
            zf.writestr(name, data)
