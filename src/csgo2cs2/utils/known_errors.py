# Known error patterns + remediation hints.
#
# When a subprocess (SteamCMD, BSPSource, Java, the import script,
# bspzip, vpkedit) fails, we run its combined stdout + stderr through
# this registry. If a pattern matches, the user gets a concrete
# "do this next" hint instead of just a wall of subprocess output.
#
# Each pattern carries a unique id so users can ask `csgo2cs2 explain`
# why it fired (TODO if that becomes useful) and so tests can assert
# against a stable identifier instead of the message text.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Pattern


@dataclass(frozen=True)
class KnownError:
    id: str
    pattern: Pattern[str]
    hint: str
    tool: str = ""  # informational: which tool typically emits this


_REGISTRY: List[KnownError] = []


def _register(
    error_id: str,
    pattern: str,
    hint: str,
    *,
    tool: str = "",
    flags: int = re.IGNORECASE,
) -> None:
    _REGISTRY.append(
        KnownError(
            id=error_id,
            pattern=re.compile(pattern, flags),
            hint=hint,
            tool=tool,
        )
    )


# ----- SteamCMD ------------------------------------------------------------

_register(
    "steam_login_denied",
    r"login\s+failure[:\s]+account\s+logon\s+denied",
    "SteamCMD needs Steam Guard. Run `steamcmd +login <username>` once "
    "interactively to cache credentials, then re-run `csgo2cs2 port`.",
    tool="steamcmd",
)

_register(
    "steam_login_rate_limited",
    r"login\s+failure[:\s]+rate\s+limit\s+exceeded",
    "SteamCMD is rate-limited. Wait ~5 minutes and try again.",
    tool="steamcmd",
)

_register(
    "steam_invalid_password",
    r"login\s+failure[:\s]+invalid\s+password",
    "Steam login failed. Verify the username in your config and the password "
    "you entered. Note that 2FA codes are not the same as passwords.",
    tool="steamcmd",
)

_register(
    "steam_workshop_download_failed",
    r"error!\s+downloading\s+item\s+\d+",
    "Steam workshop download failed. This is usually transient throttling. "
    "Wait 60s and re-run `csgo2cs2 port <id> --addon <name>` to resume.",
    tool="steamcmd",
)

_register(
    "steam_disk_full",
    r"(no\s+space\s+left\s+on\s+device|errno\s+28)",
    "Disk full. Free space under the SteamCMD content directory and retry.",
    tool="steamcmd",
)

_register(
    "steam_app_not_purchased",
    r"app[\s_]?id\s+\d+\s+not\s+(?:purchased|installed|available)",
    "SteamCMD reports the CS:GO depot is unavailable. Workshop downloads "
    "work anonymously for most public items, but private/curated items "
    "need an authenticated Steam login. Set `steam_login` in config.",
    tool="steamcmd",
)


# ----- BSPSource / Java ----------------------------------------------------

_register(
    "java_not_found",
    r"(?:'java' is not recognized|java: command not found|no\s+java\s+runtime)",
    "Java was not found on PATH. Install a JRE 8+ (e.g. Temurin) and re-run, "
    "or set `java_path` in your config to the `java` executable.",
    tool="java",
)

_register(
    "java_unsupported_class",
    r"unsupportedclassversionerror",
    "Your Java version is too old for BSPSource. Install JRE 8 or newer.",
    tool="bspsource",
)

_register(
    "bspsource_jvm_crash",
    r"(?:#\s*A fatal error has been detected by the Java Runtime|hs_err_pid)",
    "BSPSource crashed the JVM. Re-fetch a clean copy with "
    "`csgo2cs2 tools install bspsource --force`, then re-run.",
    tool="bspsource",
)

_register(
    "bspsource_protected",
    r"(bspprotect|map appears to be protected|protect)",
    "The BSP looks bspprotect-protected. Decompilation will not produce a "
    "usable VMF. csgo2cs2 cannot work around map protection.",
    tool="bspsource",
)

_register(
    "bspsource_corrupt_bsp",
    r"(invalid\s+bsp|unknown\s+lump|bsp\s+header\s+mismatch)",
    "BSP file is corrupt or not a Source 1 map. Re-download the workshop "
    "item; if the issue persists, the upload is broken on the publisher side.",
    tool="bspsource",
)


# ----- Importer (import_map_community.py) ----------------------------------

_register(
    "importer_decode_error",
    r"attributeerror:.*str.*has\s+no\s+attribute\s+['\"]decode['\"]",
    "import_map_community.py needs the .decode() patch. Run "
    "`csgo2cs2 doctor --fix` to apply it.",
    tool="importer",
)

_register(
    "importer_vpk_signature_missing",
    r"(vpk\.signatures\.old|signature[s]?\s+file\s+not\s+found)",
    "vpk.signatures is blocking pakfile extraction. Run "
    "`csgo2cs2 doctor --fix` to rename it to vpk.signatures.old.",
    tool="importer",
)

_register(
    "importer_path_with_space",
    r"(invalid\s+option|unexpected\s+argument).*\s",
    "The importer chokes on paths with spaces. Move workspace_dir to a "
    "path without spaces (e.g. C:\\csgo2cs2) and re-run.",
    tool="importer",
)

_register(
    "importer_missing_gameinfo",
    r"(gameinfo\.(?:txt|gi)\s+not\s+found|cannot\s+find\s+gameinfo)",
    "The importer cannot find gameinfo.txt or gameinfo.gi under your CS:GO "
    "install path. Verify `csgo_install_path` in config points to the "
    "'Counter-Strike Global Offensive' folder.",
    tool="importer",
)

_register(
    "importer_python_not_found",
    r"(?:'python' is not recognized|python: command not found|no module named ['\"]?vpk)",
    "Python is not on PATH or the importer's deps are missing. The bundled "
    "Python in `<install>/game/bin/win64/python3.exe` is the recommended "
    "interpreter; set `python_executable` in your config to its full path.",
    tool="importer",
)


# ----- File system / permission --------------------------------------------

_register(
    "fs_permission_denied",
    r"(?:permission\s+denied|errno\s+13|access\s+is\s+denied)",
    "Permission denied on a file or directory. On Windows, make sure CS2 "
    "and Hammer 2 are closed, run the terminal as an Administrator if your "
    "install lives under Program Files, then retry.",
    tool="filesystem",
)

_register(
    "fs_path_too_long",
    r"(?:filename\s+too\s+long|errno\s+36|path\s+too\s+long|the system cannot find the path)",
    "Path length is over the Windows MAX_PATH limit. Move `workspace_dir` "
    "to a short root like C:\\csgo2cs2 and retry.",
    tool="filesystem",
)

_register(
    "fs_no_such_file",
    r"(?:no\s+such\s+file\s+or\s+directory|errno\s+2|cannot\s+find\s+the\s+file\s+specified)",
    "A file the pipeline expected was missing. If this is mid-port, "
    "re-run with the same arguments to resume from the last completed "
    "stage.",
    tool="filesystem",
)


# ----- VPKEdit / bspzip ----------------------------------------------------

_register(
    "vpkedit_not_a_pak",
    r"(?:not\s+a\s+valid\s+pak|invalid\s+vpk\s+header)",
    "The BSP's pakfile is empty or unrecognized -- nothing to extract. "
    "Continue without VPKEdit; the importer will still run.",
    tool="vpkedit",
)

_register(
    "bspzip_not_found",
    r"bspzip(?:\.exe)?:?\s+(?:not\s+found|no\s+such\s+file)",
    "bspzip is not configured. It is bundled with CS:GO at "
    "<install>/bin/bspzip.exe. Set `bspzip_path` if auto-detect fails.",
    tool="bspzip",
)


# ----- Lookup --------------------------------------------------------------


def match_error(text: str) -> KnownError | None:
    """Return the first registered KnownError whose pattern matches."""
    if not text:
        return None
    for entry in _REGISTRY:
        if entry.pattern.search(text):
            return entry
    return None


def match_all(text: str) -> List[KnownError]:
    """Return every KnownError whose pattern matches (preserves order)."""
    if not text:
        return []
    return [e for e in _REGISTRY if e.pattern.search(text)]


def all_errors() -> Iterable[KnownError]:
    return tuple(_REGISTRY)
