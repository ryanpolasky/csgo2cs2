# colorized console output.

from __future__ import annotations

import sys

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

_VERBOSE = False


def setup_logging(verbose: bool = False) -> None:
    global _VERBOSE
    _VERBOSE = verbose


def info(msg: str) -> None:
    print(f"{Fore.CYAN}[info]{Style.RESET_ALL} {msg}")


def success(msg: str) -> None:
    print(f"{Fore.GREEN}[ok]{Style.RESET_ALL} {msg}")


def warn(msg: str) -> None:
    print(f"{Fore.YELLOW}[warn]{Style.RESET_ALL} {msg}", file=sys.stderr)


def error(msg: str) -> None:
    print(f"{Fore.RED}[error]{Style.RESET_ALL} {msg}", file=sys.stderr)


def debug(msg: str) -> None:
    if _VERBOSE:
        print(f"{Style.DIM}[debug] {msg}{Style.RESET_ALL}")


def header(msg: str) -> None:
    print(f"\n{Style.BRIGHT}== {msg} =={Style.RESET_ALL}")
