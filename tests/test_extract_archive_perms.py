"""Regression tests for `_extract_archive` POSIX permission handling
and the BSPSource adapter's `-o` argument shape.

Both behaviors are wired together: BSPSource ships a bundled JRE under
`bin/` inside its release zip. `zipfile.extractall()` strips the +x bit
from every file, leaving `bin/java` non-executable and the wrapper
script unable to run. Tools like SteamCMD have the same issue when
extracted from a tarball isn't a concern (tarfile preserves perms),
but the zip-extraction path is what bspsrc ships through.

The BSPSource adapter has a related issue: `bspsrc -o <dir>` is treated
as a *file* path when only one BSP is provided, so passing a directory
silently produces no output. The adapter now composes the explicit VMF
file path.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from csgo2cs2.commands.tools_cmd import _extract_archive
from csgo2cs2.tools.bspsource import BSPSource

# ---- _extract_archive: zip permission preservation --------------------------


def _make_zip_with_executable(zip_path: Path, members: List[tuple]) -> None:
    """`members`: list of `(arcname, content_bytes, mode)` triples."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        for arcname, content, mode in members:
            info = zipfile.ZipInfo(arcname)
            info.external_attr = (mode & 0xFFFF) << 16
            zf.writestr(info, content)


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX permission preservation is a no-op on Windows.",
)
def test_extract_archive_preserves_executable_bit(tmp_path: Path) -> None:
    """The bundled-JRE bug: zipfile.extractall() strips the +x bit. The
    fixed `_extract_archive` should restore the permissions stored in
    the zip entry's external_attr."""
    zip_path = tmp_path / "tool.zip"
    _make_zip_with_executable(
        zip_path,
        [
            ("bin/java", b"#!/bin/sh\nexit 0\n", 0o755),
            ("bin/keytool", b"#!/bin/sh\nexit 0\n", 0o755),
            ("legal/README", b"hello", 0o644),
        ],
    )
    dest = tmp_path / "out"
    _extract_archive(zip_path, dest)

    java = dest / "bin" / "java"
    keytool = dest / "bin" / "keytool"
    readme = dest / "legal" / "README"

    assert java.exists()
    assert keytool.exists()
    assert readme.exists()
    assert os.access(java, os.X_OK), "bundled JRE binary lost its +x bit"
    assert os.access(keytool, os.X_OK), "bundled JRE binary lost its +x bit"
    # readme is rw-only; the test asserts we did NOT spuriously grant +x.
    assert not os.access(readme, os.X_OK), "non-executable file gained +x"


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX permission preservation is a no-op on Windows.",
)
def test_extract_archive_handles_directory_entries(tmp_path: Path) -> None:
    """Zip directory entries (those ending in `/`) have to be skipped
    cleanly without trying to chmod them."""
    zip_path = tmp_path / "withdir.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo("bin/")
        info.external_attr = (0o755 & 0xFFFF) << 16
        zf.writestr(info, "")
        info2 = zipfile.ZipInfo("bin/java")
        info2.external_attr = (0o755 & 0xFFFF) << 16
        zf.writestr(info2, "#!/bin/sh\n")
    dest = tmp_path / "out"
    _extract_archive(zip_path, dest)
    assert (dest / "bin").is_dir()
    assert (dest / "bin" / "java").exists()
    assert os.access(dest / "bin" / "java", os.X_OK)


def test_extract_archive_handles_zero_permission_entries(tmp_path: Path) -> None:
    """Some zip producers don't set external_attr at all (perm == 0).
    The extractor should fall back to whatever the OS's default umask
    produces -- i.e. it must not crash, and it must not chmod 0o000."""
    zip_path = tmp_path / "noperm.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo("readme.txt")
        info.external_attr = 0  # nothing set
        zf.writestr(info, "hello")
    dest = tmp_path / "out"
    _extract_archive(zip_path, dest)
    assert (dest / "readme.txt").exists()
    # if perm==0 was naively applied the file would be unreadable.
    assert (dest / "readme.txt").read_text() == "hello"


# ---- BSPSource adapter: -o <file.vmf> shape ---------------------------------


def _record_run(cmds: List[List[str]]):
    """Build a subprocess.run stub that records cmd shapes."""

    def _stub(cmd, check=False, capture_output=True, text=True):
        cmds.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    return _stub


def test_bspsource_passes_explicit_vmf_path_for_wrapper(tmp_path: Path) -> None:
    """`bspsrc.sh -o <dir>` produces no output for single-BSP runs (per
    the tool's docs). The adapter should compose `<dir>/<bsp.stem>.vmf`
    so the result lands at a predictable path on every platform."""
    wrapper = tmp_path / "bspsrc.sh"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    bsp = tmp_path / "de_aim.bsp"
    bsp.write_bytes(b"VBSP")
    out_dir = tmp_path / "out"
    bs = BSPSource(str(wrapper))

    cmds: List[List[str]] = []
    with patch("csgo2cs2.tools.bspsource.subprocess.run", side_effect=_record_run(cmds)):
        bs.decompile(bsp, out_dir)

    assert len(cmds) == 1
    cmd = cmds[0]
    assert cmd[0] == str(wrapper)
    assert cmd[1] == "-o"
    # the second-to-last arg is the VMF file path; last is the BSP path.
    assert cmd[2] == str(out_dir / "de_aim.vmf")
    assert cmd[-1] == str(bsp)


def test_bspsource_passes_explicit_vmf_path_for_jar(tmp_path: Path) -> None:
    """Same fix has to apply to the .jar invocation path."""
    jar = tmp_path / "bspsrc.jar"
    jar.write_bytes(b"PK\x03\x04")
    fake_java = tmp_path / "java"
    fake_java.write_text("#!/bin/sh\n", encoding="utf-8")
    bsp = tmp_path / "de_aim.bsp"
    bsp.write_bytes(b"VBSP")
    out_dir = tmp_path / "out"
    bs = BSPSource(str(jar), java_path=str(fake_java))

    cmds: List[List[str]] = []
    with patch("csgo2cs2.tools.bspsource.subprocess.run", side_effect=_record_run(cmds)):
        bs.decompile(bsp, out_dir)

    cmd = cmds[0]
    assert cmd[0] == str(fake_java)
    assert "-jar" in cmd
    assert str(jar) in cmd
    # the -o argument follows the same shape: explicit .vmf file path.
    o_idx = cmd.index("-o")
    assert cmd[o_idx + 1] == str(out_dir / "de_aim.vmf")


def test_bspsource_creates_output_directory(tmp_path: Path) -> None:
    """The adapter should mkdir the output dir if it doesn't exist
    (BSPSource won't create parent dirs for the -o target)."""
    wrapper = tmp_path / "bspsrc.sh"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    bsp = tmp_path / "de_aim.bsp"
    bsp.write_bytes(b"VBSP")
    out_dir = tmp_path / "new" / "nested" / "out"
    assert not out_dir.exists()
    bs = BSPSource(str(wrapper))

    with patch(
        "csgo2cs2.tools.bspsource.subprocess.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    ):
        bs.decompile(bsp, out_dir)

    assert out_dir.is_dir()
