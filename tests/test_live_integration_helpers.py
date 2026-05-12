"""Unit tests for the live integration test's classifier helpers in
`tests/integration/test_live_port.py` plus the production workshop
filesystem helpers in `csgo2cs2.tools.steamcmd`.

These exercise the parts of the live-test pipeline that DON'T touch
Steam or external tools: the SteamCMD output classifier (transient vs.
permanent error), the candidate-workshop-dir probe, and the legacy.bin
ZIP unwrapper. The live tests themselves are skipped by default; this
file ensures the helper logic stays correct under refactors.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import zipfile
from pathlib import Path

import pytest

from csgo2cs2.tools.steamcmd import (
    candidate_workshop_dirs,
    resolve_downloaded_bsp,
    unwrap_legacy_bin,
)

_INTEGRATION_DIR = Path(__file__).parent / "integration"
_LIVE_PORT = _INTEGRATION_DIR / "test_live_port.py"


def _load_live_port():
    # the live-test module still owns the SteamCMD-output classifiers;
    # dynamic-load to access them without forcing pytest to collect the
    # gated tests in test_live_port itself.
    spec = importlib.util.spec_from_file_location("csgo2cs2_live_port_helpers", _LIVE_PORT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["csgo2cs2_live_port_helpers"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---- classifier -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "ERROR! Timeout downloading item 12345",
        "Failure: Account Logon Denied",
        "rate limit exceeded",
        "Could not connect to Steam network",
        "Connection to Steam server failed",
        "ERROR! Failed to install app '730' (No response)",
        "STEAMAUTH error",
    ],
)
def test_classifier_transient_matches(text: str) -> None:
    mod = _load_live_port()
    assert mod._looks_like_steam_transient(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "ERROR! Download item 1 failed (File Not Found).",
        "Workshop item does not exist",
        "Steam: ERROR! Workshop item 999 is no longer exists",
        "Access Denied",
        "is not available for this app",
    ],
)
def test_classifier_permanent_matches(text: str) -> None:
    mod = _load_live_port()
    assert mod._looks_like_permanent_workshop_error(text) is True


def test_classifier_empty_text_is_neither() -> None:
    mod = _load_live_port()
    assert mod._looks_like_steam_transient("") is False
    assert mod._looks_like_permanent_workshop_error("") is False


def test_classifier_clean_output_is_neither() -> None:
    mod = _load_live_port()
    text = "Downloading item 12345 ...\nSuccess. Downloaded item 12345"
    assert mod._looks_like_steam_transient(text) is False
    assert mod._looks_like_permanent_workshop_error(text) is False


def test_classifier_permanent_does_not_match_transient_pattern() -> None:
    """`File Not Found` is permanent (bad workshop id), not a transient
    that should be retried. Verifies the two classifiers don't overlap."""
    mod = _load_live_port()
    text = "ERROR! Download item 1 failed (File Not Found)."
    assert mod._looks_like_permanent_workshop_error(text) is True
    assert mod._looks_like_steam_transient(text) is False


# ---- legacy.bin unwrap ------------------------------------------------------


def _make_fake_bsp(tmp: Path, name: str = "fake.bsp", size: int = 64) -> Path:
    """A minimal `VBSP`-magic file BSPSource would accept as a BSP."""
    out = tmp / name
    out.write_bytes(b"VBSP" + struct.pack("<i", 21) + b"\x00" * (size - 8))
    return out


def test_unwrap_legacy_bin_extracts_bsp(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    bsp = _make_fake_bsp(src_dir, "de_test.bsp")
    blob = tmp_path / "12345_legacy.bin"
    with zipfile.ZipFile(blob, "w") as zf:
        zf.write(bsp, arcname="de_test.bsp")
    result = unwrap_legacy_bin(blob, tmp_path / "unwrap")
    assert result.exists()
    assert result.suffix == ".bsp"
    assert result.read_bytes()[:4] == b"VBSP"


def test_unwrap_legacy_bin_picks_largest_when_multiple(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    small = _make_fake_bsp(src_dir, "small.bsp", size=64)
    big = _make_fake_bsp(src_dir, "big.bsp", size=1024)
    blob = tmp_path / "v_legacy.bin"
    with zipfile.ZipFile(blob, "w") as zf:
        zf.write(small, arcname="small.bsp")
        zf.write(big, arcname="big.bsp")
    result = unwrap_legacy_bin(blob, tmp_path / "unwrap")
    assert result.name == "big.bsp"


def test_unwrap_legacy_bin_handles_raw_bsp(tmp_path: Path) -> None:
    """SteamCMD on some platforms hands the BSP back as a renamed .bin
    rather than a zip wrapper. The unwrapper should detect the VBSP
    magic and just copy the file."""
    raw = tmp_path / "raw_legacy.bin"
    raw.write_bytes(b"VBSP" + struct.pack("<i", 21) + b"\x00" * 32)
    result = unwrap_legacy_bin(raw, tmp_path / "unwrap")
    assert result.exists()
    assert result.suffix == ".bsp"
    assert result.read_bytes()[:4] == b"VBSP"


def test_unwrap_legacy_bin_rejects_junk(tmp_path: Path) -> None:
    """A .bin that's neither a zip nor a raw BSP should raise, not
    silently produce a corrupted output file."""
    junk = tmp_path / "junk_legacy.bin"
    junk.write_bytes(b"XXXX" + b"\x00" * 32)
    with pytest.raises(RuntimeError, match="neither a zip nor a raw BSP"):
        unwrap_legacy_bin(junk, tmp_path / "unwrap")


def test_unwrap_legacy_bin_rejects_zip_without_bsp(tmp_path: Path) -> None:
    """A zip that has no .bsp inside should raise with a sample of the
    contents in the error so the user can see what they got."""
    blob = tmp_path / "weird_legacy.bin"
    with zipfile.ZipFile(blob, "w") as zf:
        zf.writestr("readme.txt", "not a bsp")
        zf.writestr("preview.jpg", b"\xff\xd8\xff\xe0")
    with pytest.raises(RuntimeError, match="contained no .bsp"):
        unwrap_legacy_bin(blob, tmp_path / "unwrap")


# ---- candidate-dir probing --------------------------------------------------


def _stub_home(monkeypatch, fake_home: Path) -> None:
    """Force `Path.home()` to return `fake_home`. We can't just set
    HOME because Windows uses USERPROFILE and falls back to
    HOMEDRIVE+HOMEPATH; patching `Path.home` directly is the only
    platform-agnostic option."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))


def test_candidate_dirs_returns_expected_then_home_fallback(tmp_path: Path, monkeypatch) -> None:
    """The probe should return SteamCMD's nominal workshop path first
    and the ~/Steam/... fallback second."""
    fake_root = tmp_path / "tools" / "steamcmd"
    fake_root.mkdir(parents=True)
    expected = fake_root / "steamapps" / "workshop" / "content" / "730" / "X"
    expected.mkdir(parents=True)

    class _Stub:
        def expected_workshop_path(self, wid: str) -> Path:
            return expected

    fake_home = tmp_path / "home"
    _stub_home(monkeypatch, fake_home)
    out = candidate_workshop_dirs(_Stub(), "X")
    assert out[0] == expected
    # second slot is the home-relative fallback. compare paths as
    # `Path` objects so trailing-slash and path-separator differences
    # don't matter across linux/windows.
    expected_fallback = fake_home / "Steam" / "steamapps" / "workshop" / "content" / "730" / "X"
    assert any(p == expected_fallback for p in out[1:])


def test_candidate_dirs_dedupes_identical_paths(tmp_path: Path, monkeypatch) -> None:
    """If a tool config happens to point at the same path as the home
    fallback, the probe should only list it once."""
    _stub_home(monkeypatch, tmp_path)
    shared = tmp_path / "Steam" / "steamapps" / "workshop" / "content" / "730" / "X"

    class _Stub:
        def expected_workshop_path(self, wid: str) -> Path:
            return shared

    out = candidate_workshop_dirs(_Stub(), "X")
    assert len(out) == 1


# ---- resolve_downloaded_bsp -------------------------------------------------


def test_resolve_downloaded_bsp_returns_raw_bsp_when_present(tmp_path: Path, monkeypatch) -> None:
    """Sanity: when SteamCMD dropped a raw `.bsp` into the expected
    path, `resolve_downloaded_bsp` returns it unmodified."""
    fake_root = tmp_path / "tools" / "steamcmd"
    expected = fake_root / "steamapps" / "workshop" / "content" / "730" / "X"
    expected.mkdir(parents=True)
    bsp = _make_fake_bsp(expected, "de_test.bsp", size=128)

    class _Stub:
        def expected_workshop_path(self, wid: str) -> Path:
            return expected

    _stub_home(monkeypatch, tmp_path / "home")
    result = resolve_downloaded_bsp(_Stub(), "X", tmp_path / "scratch")
    assert result == bsp


def test_resolve_downloaded_bsp_unwraps_legacy_bin(tmp_path: Path, monkeypatch) -> None:
    """Regression for the port-pipeline bug Ryan hit: anonymous SteamCMD
    downloads produce `<id>_legacy.bin` (a ZIP-wrapped BSP), not a raw
    `.bsp`. The resolver must unwrap it into the scratch dir and return
    the inner `.bsp` so BSPSource gets something it can decompile."""
    fake_root = tmp_path / "tools" / "steamcmd"
    expected = fake_root / "steamapps" / "workshop" / "content" / "730" / "X"
    expected.mkdir(parents=True)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    bsp = _make_fake_bsp(src_dir, "de_test.bsp", size=256)
    legacy_bin = expected / "12345_legacy.bin"
    with zipfile.ZipFile(legacy_bin, "w") as zf:
        zf.write(bsp, arcname="de_test.bsp")

    class _Stub:
        def expected_workshop_path(self, wid: str) -> Path:
            return expected

    _stub_home(monkeypatch, tmp_path / "home")
    scratch = tmp_path / "scratch"
    result = resolve_downloaded_bsp(_Stub(), "X", scratch)
    assert result is not None
    assert result.suffix == ".bsp"
    assert result.read_bytes()[:4] == b"VBSP"
    # the unwrap target should live under scratch/unwrap/<id>/
    assert str(scratch / "unwrap" / "X") in str(result)


def test_resolve_downloaded_bsp_returns_none_when_dir_empty(tmp_path: Path, monkeypatch) -> None:
    """No raw .bsp and no _legacy.bin -> None so the caller can produce
    a helpful "what is actually here" error rather than guessing."""
    fake_root = tmp_path / "tools" / "steamcmd"
    expected = fake_root / "steamapps" / "workshop" / "content" / "730" / "X"
    expected.mkdir(parents=True)
    # leave the dir empty -- SteamCMD timed out before downloading anything

    class _Stub:
        def expected_workshop_path(self, wid: str) -> Path:
            return expected

    _stub_home(monkeypatch, tmp_path / "home")
    assert resolve_downloaded_bsp(_Stub(), "X", tmp_path / "scratch") is None
