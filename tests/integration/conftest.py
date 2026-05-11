"""Shared fixtures and gating for the live integration tests.

The live integration tests are different from every other test in this
repo: they actually contact Steam (anonymous CSGO workshop download) and
run real BSPSource against a real .bsp. That makes them slow, flaky on
Steam's bad days, and useless without `steamcmd` + `java` + a BSPSource
JAR on the host.

So they are gated behind `CSGO2CS2_LIVE_TEST=1`. Regular `pytest -q`
must continue to skip them with zero side effects.

The workshop ID under test defaults to a small public CS:GO surf/aim
map known to be stable on the Steam Workshop. Override with
`CSGO2CS2_LIVE_TEST_WORKSHOP_ID=<id>` if Steam ever loses or replaces
the default.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from csgo2cs2.config import Config, load_config, save_config

LIVE_TEST_ENV = "CSGO2CS2_LIVE_TEST"
WORKSHOP_ID_ENV = "CSGO2CS2_LIVE_TEST_WORKSHOP_ID"
TIMEOUT_ENV = "CSGO2CS2_LIVE_TEST_TIMEOUT"

# Default workshop ID -- a long-lived public CS:GO community map that
# anonymous SteamCMD can fetch (~4 MB). Override via
# CSGO2CS2_LIVE_TEST_WORKSHOP_ID if Steam ever drops it. The criteria
# for a replacement: small (<20 MB), publicly downloadable without a
# Steam login, and not gated behind paid content.
DEFAULT_WORKSHOP_ID = "419404847"

# Default download timeout, seconds. Anonymous workshop downloads are
# bandwidth-throttled by Steam; the smallest maps can still take a
# minute or two on a bad day.
DEFAULT_TIMEOUT = 600


def is_live_test_enabled() -> bool:
    v = os.environ.get(LIVE_TEST_ENV, "").lower()
    return v in ("1", "true", "yes", "on")


def get_workshop_id() -> str:
    return os.environ.get(WORKSHOP_ID_ENV, DEFAULT_WORKSHOP_ID)


def get_timeout() -> int:
    try:
        return int(os.environ.get(TIMEOUT_ENV, DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def _resolve_tool(env_var: str, name: str, default_from_config: str | None) -> str | None:
    """Resolve a tool path in priority order:
    1. explicit `env_var` override
    2. the path the user's saved config (~/.csgo2cs2/config.json) already
       points at -- this is what `csgo2cs2 tools install` produces
    3. first match on PATH (e.g. system-wide install)
    Returns None if nothing matched."""
    explicit = os.environ.get(env_var)
    if explicit and Path(explicit).exists():
        return explicit
    if default_from_config and Path(default_from_config).exists():
        return default_from_config
    return shutil.which(name)


def _require_tool(env_var: str, name: str, default_from_config: str | None) -> str:
    """Fail the calling test cleanly if a required external tool is
    missing on the host. We do not auto-install -- CI is expected to
    have run `csgo2cs2 tools install` already."""
    path = _resolve_tool(env_var, name, default_from_config)
    if not path:
        pytest.fail(
            f"Live integration test needs '{name}'. Looked at {env_var}, "
            f"~/.csgo2cs2/config.json, and PATH. "
            f"Either run `csgo2cs2 tools install` first, or unset "
            f"{LIVE_TEST_ENV} to skip these tests.",
            pytrace=False,
        )
    return path


@pytest.fixture(scope="session")
def live_skip_if_disabled():
    """Skip the entire integration-test module if the env gate is off.

    Returning normally means the test was allowed to proceed. We do not
    raise here; individual tests pull this fixture for the gate to
    fire."""
    if not is_live_test_enabled():
        pytest.skip(f"Live integration tests are gated on {LIVE_TEST_ENV}=1")


@pytest.fixture(scope="session")
def live_workspace(tmp_path_factory, live_skip_if_disabled) -> Path:
    """Session-scoped workspace. We share it across the two live tests
    so the download-only test feeds its BSP into the full-chain test
    without re-paying for the Steam download."""
    return tmp_path_factory.mktemp("live_workspace")


@pytest.fixture(scope="session")
def live_config_path(live_workspace) -> Path:
    """A real config file pointing at the host-installed tools. Pulls
    paths from `~/.csgo2cs2/config.json` (what `csgo2cs2 tools install`
    writes) by default; respect env-var overrides for hosts that have a
    custom setup."""
    # try the user's installed config first; fall back to a fresh Config
    # if it doesn't exist yet.
    try:
        installed_cfg = load_config(None)
    except Exception:  # noqa: BLE001
        installed_cfg = Config()

    steamcmd = _require_tool("CSGO2CS2_LIVE_STEAMCMD_PATH", "steamcmd", installed_cfg.steamcmd_path)
    bspsource = _resolve_tool(
        "CSGO2CS2_LIVE_BSPSOURCE_PATH", "bspsrc", installed_cfg.bspsource_path
    )

    cfg = Config(
        steamcmd_path=steamcmd,
        bspsource_path=bspsource,
        workspace_dir=str(live_workspace),
    )
    cfg_path = live_workspace / "config.json"
    save_config(cfg, str(cfg_path))
    return cfg_path


@pytest.fixture(scope="session")
def live_workshop_id() -> str:
    return get_workshop_id()


@pytest.fixture(scope="session")
def live_timeout() -> int:
    return get_timeout()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: live integration tests requiring Steam + Java + BSPSource. "
        f"Gated on {LIVE_TEST_ENV}=1.",
    )
