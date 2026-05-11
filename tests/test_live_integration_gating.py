"""Unit tests for the live integration test's gating helpers.

These exercise the conftest helpers in `tests/integration/conftest.py`
without depending on Steam or any external tool. The live tests
themselves are skipped by default (gated on CSGO2CS2_LIVE_TEST=1); this
module ensures the gate plumbing itself stays correct.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# load the integration conftest by file path (it lives in a subdir we
# do not normally package).
_INTEGRATION_DIR = Path(__file__).parent / "integration"
_CONFTEST = _INTEGRATION_DIR / "conftest.py"


def _load_conftest():
    spec = importlib.util.spec_from_file_location("csgo2cs2_integration_conftest", _CONFTEST)
    module = importlib.util.module_from_spec(spec)
    sys.modules["csgo2cs2_integration_conftest"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_is_live_test_enabled_default_off(monkeypatch) -> None:
    conf = _load_conftest()
    monkeypatch.delenv(conf.LIVE_TEST_ENV, raising=False)
    assert conf.is_live_test_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_is_live_test_enabled_truthy_values(monkeypatch, value: str) -> None:
    conf = _load_conftest()
    monkeypatch.setenv(conf.LIVE_TEST_ENV, value)
    assert conf.is_live_test_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
def test_is_live_test_enabled_falsy_values(monkeypatch, value: str) -> None:
    conf = _load_conftest()
    monkeypatch.setenv(conf.LIVE_TEST_ENV, value)
    assert conf.is_live_test_enabled() is False


def test_get_workshop_id_default(monkeypatch) -> None:
    conf = _load_conftest()
    monkeypatch.delenv(conf.WORKSHOP_ID_ENV, raising=False)
    assert conf.get_workshop_id() == conf.DEFAULT_WORKSHOP_ID


def test_get_workshop_id_override(monkeypatch) -> None:
    conf = _load_conftest()
    monkeypatch.setenv(conf.WORKSHOP_ID_ENV, "999888777")
    assert conf.get_workshop_id() == "999888777"


def test_get_timeout_default(monkeypatch) -> None:
    conf = _load_conftest()
    monkeypatch.delenv(conf.TIMEOUT_ENV, raising=False)
    assert conf.get_timeout() == conf.DEFAULT_TIMEOUT


def test_get_timeout_override(monkeypatch) -> None:
    conf = _load_conftest()
    monkeypatch.setenv(conf.TIMEOUT_ENV, "900")
    assert conf.get_timeout() == 900


def test_get_timeout_invalid_falls_back(monkeypatch) -> None:
    conf = _load_conftest()
    monkeypatch.setenv(conf.TIMEOUT_ENV, "not-a-number")
    assert conf.get_timeout() == conf.DEFAULT_TIMEOUT


def test_resolve_tool_env_var_wins(monkeypatch, tmp_path: Path) -> None:
    conf = _load_conftest()
    fake = tmp_path / "fake-steamcmd"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_TOOL_ENV", str(fake))
    out = conf._resolve_tool("FAKE_TOOL_ENV", "this-binary-does-not-exist", None)
    assert out == str(fake)


def test_resolve_tool_env_var_pointing_at_missing_file_falls_through(
    monkeypatch, tmp_path: Path
) -> None:
    conf = _load_conftest()
    monkeypatch.setenv("FAKE_TOOL_ENV", str(tmp_path / "missing"))
    out = conf._resolve_tool("FAKE_TOOL_ENV", "this-binary-does-not-exist-either", None)
    assert out is None


def test_resolve_tool_falls_back_to_config_path(monkeypatch, tmp_path: Path) -> None:
    conf = _load_conftest()
    monkeypatch.delenv("FAKE_TOOL_ENV", raising=False)
    fake = tmp_path / "from-config"
    fake.write_text("ok", encoding="utf-8")
    out = conf._resolve_tool("FAKE_TOOL_ENV", "this-binary-does-not-exist-yet", str(fake))
    assert out == str(fake)


def test_resolve_tool_falls_back_to_path(monkeypatch) -> None:
    conf = _load_conftest()
    monkeypatch.delenv("FAKE_TOOL_ENV", raising=False)
    # `python` is a binary every test host has somewhere on PATH.
    out = conf._resolve_tool("FAKE_TOOL_ENV", "python", None)
    assert out is not None


def test_resolve_tool_none_when_nothing_matches(monkeypatch) -> None:
    conf = _load_conftest()
    monkeypatch.delenv("FAKE_TOOL_ENV", raising=False)
    out = conf._resolve_tool("FAKE_TOOL_ENV", "absolutely-not-a-real-binary-name-xyz123", None)
    assert out is None
