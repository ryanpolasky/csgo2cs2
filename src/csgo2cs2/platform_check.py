# platform detection and windows-only guards.

from __future__ import annotations

import platform


def is_windows() -> bool:
    return platform.system() == "Windows"


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_linux() -> bool:
    return platform.system() == "Linux"


def os_label() -> str:
    return f"{platform.system()} {platform.release()}".strip()


class WindowsRequiredError(RuntimeError):
    pass


# block cs2 import steps outside windows.
def require_windows(action: str) -> None:
    if not is_windows():
        raise WindowsRequiredError(
            f"{action} requires Windows. Detected: {os_label()}. "
            f"Run download/decompile/analyze on any OS, then run port on Windows."
        )
