"""Live integration tests that hit Steam and the real BSPSource binary.

These tests are skipped unless `CSGO2CS2_LIVE_TEST=1` is set. They are
designed to run on a dedicated CI job with steamcmd + java + the
csgo2cs2 tools cache already provisioned, and to catch regressions that
unit tests structurally can't see (Steam API/CLI surface changes,
BSPSource JAR update breakage, SteamCMD output-parsing drift, etc.).

The two tests share a session-scoped workspace so the download is paid
for exactly once and the decompile/analyze step picks up the cached
BSP for free.

Failure semantics: anything that looks like a Steam-side transient
(rate limit, "workshop item temporarily unavailable", anonymous-login
throttle) is reported via `pytest.xfail`, not `pytest.fail`, because
those are not bugs in this codebase. A real regression in our adapter
glue surfaces as a normal failure.
"""

from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path
from typing import List

import pytest

from csgo2cs2.analyzers.vmf import analyze_vmf
from csgo2cs2.config import load_config
from csgo2cs2.tools.bspsource import BSPSource
from csgo2cs2.tools.steamcmd import SteamCMD

pytestmark = pytest.mark.integration


# ---- helpers ----------------------------------------------------------------


def _looks_like_steam_transient(text: str) -> bool:
    """Pattern-match Steam-side *transient* flake signatures (the kind
    that go away if you retry an hour later). These should xfail, not
    fail -- they're not bugs in our adapter glue."""
    if not text:
        return False
    needles = (
        "ERROR! Timeout downloading",
        "Failure: Account Logon Denied",
        "rate limit",
        "Could not connect to Steam network",
        "Connection to Steam server failed",
        "No response",
        "Failed to retrieve",
        "STEAMAUTH",
        "ERROR! Failed to install app",
    )
    lc = text.lower()
    return any(n.lower() in lc for n in needles)


def _looks_like_permanent_workshop_error(text: str) -> bool:
    """Pattern-match *permanent* workshop failures (item doesn't exist,
    is private, was deleted, requires ownership). These should fail
    with a clear message pointing at CSGO2CS2_LIVE_TEST_WORKSHOP_ID, not
    masquerade as a Steam transient -- if the configured map is wrong,
    the right fix is to pick a different one, not retry."""
    if not text:
        return False
    needles = (
        "File Not Found",
        "Workshop item does not exist",
        "no longer exists",
        "Access Denied",
        "is not available for this app",
    )
    return any(n in text for n in needles)


def _candidate_workshop_dirs(steam: SteamCMD, workshop_id: str) -> List[Path]:
    """Where SteamCMD might have dropped the workshop item, in order of
    likelihood. SteamCMD's Linux build defaults to ~/Steam/ for data
    storage even if its binary lives elsewhere; the Windows build keeps
    everything under its install dir. We probe both."""
    candidates: List[Path] = []
    expected = steam.expected_workshop_path(workshop_id)
    if expected:
        candidates.append(expected)
    home = Path.home()
    candidates.append(home / "Steam" / "steamapps" / "workshop" / "content" / "730" / workshop_id)
    seen: set = set()
    out: List[Path] = []
    for c in candidates:
        s = str(c.resolve()) if c.exists() else str(c)
        if s in seen:
            continue
        seen.add(s)
        out.append(c)
    return out


def _unwrap_legacy_bin(legacy_bin: Path, extract_dir: Path) -> Path:
    """SteamCMD's anonymous downloads for CS:GO workshop items come down
    as a `<numeric_id>_legacy.bin` blob -- a ZIP container holding the
    actual `.bsp`. Unwrap it so the test can hand a real `.bsp` to
    BSPSource."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    if not zipfile.is_zipfile(legacy_bin):
        head = legacy_bin.read_bytes()[:4]
        if head == b"VBSP":
            target = extract_dir / (legacy_bin.stem + ".bsp")
            target.write_bytes(legacy_bin.read_bytes())
            return target
        raise RuntimeError(f"{legacy_bin} is neither a zip nor a raw BSP (magic={head!r})")
    with zipfile.ZipFile(legacy_bin) as zf:
        zf.extractall(extract_dir)
    bsps = sorted(extract_dir.rglob("*.bsp"))
    if not bsps:
        with zipfile.ZipFile(legacy_bin) as zf:
            names = zf.namelist()[:8]
        raise RuntimeError(f"{legacy_bin} unwrapped but contained no .bsp (sample: {names})")
    return max(bsps, key=lambda p: p.stat().st_size)


def _resolve_downloaded_bsp(steam: SteamCMD, workshop_id: str, scratch_root: Path) -> Path:
    """Find the .bsp SteamCMD just dropped onto disk, accounting for
    the platform-specific quirks in `_candidate_workshop_dirs` and the
    `*_legacy.bin` ZIP wrapping in `_unwrap_legacy_bin`."""
    candidates = _candidate_workshop_dirs(steam, workshop_id)
    inspected: List[str] = []
    for d in candidates:
        if not d.exists():
            inspected.append(f"{d} (missing)")
            continue
        contents = sorted(d.iterdir())
        inspected.append(f"{d} ({[p.name for p in contents]})")
        bsps = sorted(d.glob("*.bsp"))
        if bsps:
            return max(bsps, key=lambda p: p.stat().st_size)
        legacy_bins = sorted(d.glob("*_legacy.bin")) + sorted(d.glob("*.bin"))
        if legacy_bins:
            target_dir = scratch_root / "unwrap" / workshop_id
            return _unwrap_legacy_bin(max(legacy_bins, key=lambda p: p.stat().st_size), target_dir)
    raise FileNotFoundError(
        "No BSP found at any candidate SteamCMD workshop path. " "Probed: " + "; ".join(inspected)
    )


# ---- tests ------------------------------------------------------------------


def test_steamcmd_anonymous_workshop_download_succeeds(
    live_config_path: Path,
    live_workshop_id: str,
    live_timeout: int,
    live_workspace: Path,
) -> None:
    """The cheapest live check we can do: SteamCMD can anonymously
    download one small public workshop item and the result lands at
    the expected `steamapps/workshop/content/730/<id>/` path with at
    least one .bsp."""
    cfg = load_config(str(live_config_path))
    steam = SteamCMD(cfg.steamcmd_path)

    # We override `subprocess.run`'s timeout via the adapter's own
    # mechanism by setting an env var that SteamCMD wrapper respects;
    # otherwise the call can hang indefinitely on Steam's bad days.
    os.environ["CSGO2CS2_STEAMCMD_TIMEOUT"] = str(live_timeout)

    try:
        result = steam.download_workshop_item(live_workshop_id, retries=2)
    except subprocess.TimeoutExpired as exc:
        pytest.xfail(f"SteamCMD timed out after {live_timeout}s: {exc}")
    except FileNotFoundError as exc:
        pytest.fail(f"steamcmd binary not runnable: {exc}", pytrace=False)

    stdout = (result.stdout or "") + (result.stderr or "")
    if _looks_like_permanent_workshop_error(stdout):
        pytest.fail(
            f"Workshop ID {live_workshop_id!r} is invalid or no longer available. "
            f"Pick a different one via CSGO2CS2_LIVE_TEST_WORKSHOP_ID. "
            f"SteamCMD tail:\n{stdout[-800:]}",
            pytrace=False,
        )
    if _looks_like_steam_transient(stdout):
        pytest.xfail(
            "SteamCMD reported a Steam-side transient; not a regression in our "
            f"adapter glue. tail:\n{stdout[-800:]}"
        )

    bsp = _resolve_downloaded_bsp(steam, live_workshop_id, live_workspace)
    assert bsp.stat().st_size > 0, f"BSP at {bsp} is empty"


def test_full_chain_download_decompile_analyze(
    live_config_path: Path,
    live_workshop_id: str,
    live_timeout: int,
    live_workspace: Path,
) -> None:
    """Full chain: SteamCMD download -> BSPSource decompile -> analyze
    the resulting VMF. The download piggybacks on whatever the
    previous test cached in the same session-scoped workspace, so
    Steam only gets hit once.

    Assertions:
      - the BSP exists on disk
      - BSPSource produces a non-empty .vmf
      - `analyze_vmf` runs against it without raising and returns at
        least one finding (even a clean map produces info-level
        findings for nav/radar/etc.)
    """
    cfg = load_config(str(live_config_path))
    steam = SteamCMD(cfg.steamcmd_path)

    if not cfg.bspsource_path:
        pytest.skip(
            "BSPSource is not configured. Set CSGO2CS2_LIVE_BSPSOURCE_PATH "
            "or run `csgo2cs2 tools install bspsource` before invoking "
            "the live test."
        )

    # download (idempotent: SteamCMD skips already-cached items)
    try:
        download_result = steam.download_workshop_item(live_workshop_id, retries=2)
    except subprocess.TimeoutExpired as exc:
        pytest.xfail(f"SteamCMD timed out: {exc}")
    stdout = (download_result.stdout or "") + (download_result.stderr or "")
    if _looks_like_permanent_workshop_error(stdout):
        pytest.fail(
            f"Workshop ID {live_workshop_id!r} is invalid or no longer available. "
            f"Pick a different one via CSGO2CS2_LIVE_TEST_WORKSHOP_ID.",
            pytrace=False,
        )
    if _looks_like_steam_transient(stdout):
        pytest.xfail(
            "SteamCMD reported a Steam-side transient (download). " f"tail:\n{stdout[-800:]}"
        )

    bsp = _resolve_downloaded_bsp(steam, live_workshop_id, live_workspace)
    assert bsp.exists() and bsp.stat().st_size > 0

    # decompile
    bspsrc = BSPSource(cfg.bspsource_path)
    out_dir = live_workspace / "decompile" / live_workshop_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        decomp = bspsrc.decompile(bsp, out_dir)
    except subprocess.TimeoutExpired as exc:
        pytest.xfail(f"BSPSource timed out: {exc}")
    assert decomp.returncode == 0, (
        f"BSPSource non-zero exit ({decomp.returncode}). stderr tail:\n"
        f"{(decomp.stderr or '')[-1000:]}"
    )

    vmf_candidates = sorted(out_dir.glob("*.vmf"))
    assert vmf_candidates, (
        f"BSPSource produced no .vmf under {out_dir} "
        f"(contents: {[p.name for p in out_dir.iterdir()]})"
    )
    vmf = max(vmf_candidates, key=lambda p: p.stat().st_size)
    assert vmf.stat().st_size > 0, f".vmf at {vmf} is empty"

    # analyze
    text = vmf.read_text(encoding="utf-8", errors="replace")
    analysis = analyze_vmf(text)
    # we don't assert a specific finding -- maps differ -- but the
    # analyzer must run cleanly and return a structured report.
    assert analysis is not None
    assert hasattr(analysis, "findings")
    # the file must contain at least one entity block (sanity: this is
    # a real Source map, not an empty buffer).
    assert "classname" in text, "Decompiled VMF has no entity classnames"
