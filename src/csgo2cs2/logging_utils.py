# colorized console output.

from __future__ import annotations

import os
import sys
import textwrap
from typing import Iterable, List, Sequence, Tuple

try:
    from colorama import Fore, Style
    from colorama import init as _colorama_init

    _colorama_init()
    _HAS_COLOR = True
except ImportError:  # colorama is a hard dep, but fail soft
    _HAS_COLOR = False

    class _Stub:
        def __getattr__(self, _name):
            return ""

    Fore = _Stub()
    Style = _Stub()


# respect the cross-tool NO_COLOR convention as well as our own escape
# hatch. when set, every formatter below collapses to plain text.
def _color_disabled() -> bool:
    if os.environ.get("CSGO2CS2_NO_COLOR"):
        return True
    if os.environ.get("NO_COLOR") is not None:
        return True
    return False


def _c(code: str, msg: str) -> str:
    if _color_disabled() or not _HAS_COLOR:
        return msg
    return f"{code}{msg}{Style.RESET_ALL}"


_VERBOSE = False


def setup_logging(verbose: bool = False) -> None:
    global _VERBOSE
    _VERBOSE = verbose


def info(msg: str) -> None:
    print(f"{_c(Fore.CYAN, '[info]')} {msg}")


def success(msg: str) -> None:
    print(f"{_c(Fore.GREEN, '[ok]')} {msg}")


def warn(msg: str) -> None:
    print(f"{_c(Fore.YELLOW, '[warn]')} {msg}", file=sys.stderr)


def error(msg: str) -> None:
    print(f"{_c(Fore.RED, '[error]')} {msg}", file=sys.stderr)


def debug(msg: str) -> None:
    if _VERBOSE:
        print(_c(Style.DIM, f"[debug] {msg}"))


# Pick a rule character that the active stdout codec can actually
# encode. Windows cmd.exe under cp1252 (which is also Python's default
# when stdout is a pipe/file on Windows) can't encode U+2500, so we
# silently fall back to '-' there to avoid a UnicodeEncodeError that
# would crash the whole CLI on first `header()` call.
def _rule_char() -> str:
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "\u2500".encode(enc)
    except (UnicodeEncodeError, LookupError):
        return "-"
    return "\u2500"


_RULE_CHAR = _rule_char()


# section header. emits a blank line + rule + title + rule. wider than
# the old `== title ==` so longer step names like "Step 5/5: Analyze and
# fix VMF" don't look cramped.
def header(msg: str) -> None:
    rule = _RULE_CHAR * max(8, min(60, len(msg) + 8))
    print()
    print(_c(Style.BRIGHT, rule))
    print(_c(Style.BRIGHT, f"  {msg}"))
    print(_c(Style.BRIGHT, rule))


# program banner — printed once on long-running commands. keeps the
# "what is this tool" context visible at the top of long sessions.
def banner(version: str, subtitle: str = "") -> None:
    line1 = f"csgo2cs2  v{version}"
    print(_c(Style.BRIGHT + Fore.CYAN, line1))
    if subtitle:
        print(_c(Style.DIM, f"  {subtitle}"))


# pretty-print a 2D table with aligned columns. headers are bold,
# severity column is colored when present.
def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    if not rows:
        return
    cols = len(headers)
    widths: List[int] = []
    for i in range(cols):
        widest = len(headers[i])
        for r in rows:
            if i < len(r):
                widest = max(widest, len(r[i]))
        widths.append(widest)

    def _row_fmt(parts: Sequence[str], colorize_severity: bool) -> str:
        out = []
        for i, p in enumerate(parts):
            cell = p.ljust(widths[i])
            if colorize_severity and headers[i].lower() == "severity":
                cell = _severity_color(p, cell)
            out.append(cell)
        return "  ".join(out)

    print(_c(Style.BRIGHT, _row_fmt(headers, colorize_severity=False)))
    rule_parts = ["─" * w for w in widths]
    print(_c(Style.DIM, "  ".join(rule_parts)))
    for r in rows:
        print(_row_fmt([str(x) for x in r], colorize_severity=True))


def _severity_color(value: str, cell: str) -> str:
    v = value.strip().lower()
    if v == "error":
        return _c(Fore.RED, cell)
    if v == "warn":
        return _c(Fore.YELLOW, cell)
    if v == "info":
        return _c(Fore.CYAN, cell)
    if v in {"yes", "true", "ok"}:
        return _c(Fore.GREEN, cell)
    return cell


# summary footer for analyze / port runs. shows counts by severity and
# any extras the caller wants to surface (fixed, fixable, manual).
def summary_footer(
    *,
    by_severity: dict[str, int],
    extras: Iterable[Tuple[str, str]] = (),
    next_step: str = "",
) -> None:
    line_parts = []
    for sev in ("error", "warn", "info"):
        count = by_severity.get(sev, 0)
        cell = f"{count} {sev}"
        line_parts.append(_severity_color(sev, cell))
    extras_parts = [f"{label}: {value}" for label, value in extras]
    print()
    print(_c(Style.BRIGHT, "Summary"))
    print(_c(Style.DIM, "─" * 40))
    print("  " + "   ".join(line_parts))
    for line in extras_parts:
        print(f"  {line}")
    if next_step:
        print()
        wrapped = textwrap.fill(
            next_step, width=78, initial_indent="  → ", subsequent_indent="    "
        )
        print(_c(Fore.CYAN, wrapped))
