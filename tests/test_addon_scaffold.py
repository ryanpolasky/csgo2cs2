"""Unit tests for csgo2cs2.tools.addon_scaffold."""

from __future__ import annotations

from pathlib import Path

import pytest

from csgo2cs2.config import Config
from csgo2cs2.tools.addon_scaffold import (
    SCAFFOLD_MARKER,
    addon_dir,
    create,
    inspect,
)


def _cfg(tmp_path: Path) -> Config:
    addons = tmp_path / "cs2_addons"
    addons.mkdir()
    return Config(cs2_addons_path=str(addons))


def test_addon_dir_returns_none_when_unset(tmp_path: Path) -> None:
    cfg = Config()  # cs2_addons_path defaults to None
    assert addon_dir(cfg, "foo") is None


def test_addon_dir_resolves(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert addon_dir(cfg, "foo") == Path(cfg.cs2_addons_path) / "foo"


def test_inspect_returns_none_when_unset(tmp_path: Path) -> None:
    assert inspect(Config(), "foo") is None


def test_inspect_missing_dir(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    state = inspect(cfg, "ghost")
    assert state is not None
    assert state.exists is False
    assert state.has_addoninfo is False
    assert state.is_scaffolded is False
    assert state.has_prior_port_output is False


def test_inspect_fresh_workshop_tools_dir(tmp_path: Path) -> None:
    """Empty maps/ + addoninfo.gi without our marker (WT-created)."""
    cfg = _cfg(tmp_path)
    d = Path(cfg.cs2_addons_path) / "wt_addon"
    (d / "maps").mkdir(parents=True)
    (d / "addoninfo.gi").write_text('"AddonInfo" {}\n', encoding="utf-8")
    state = inspect(cfg, "wt_addon")
    assert state is not None
    assert state.exists is True
    assert state.has_addoninfo is True
    assert state.scaffolded_by_csgo2cs2 is False
    assert state.is_scaffolded is True  # empty maps/
    assert state.has_prior_port_output is False


def test_inspect_dir_with_prior_port_output(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    d = Path(cfg.cs2_addons_path) / "ported"
    (d / "maps").mkdir(parents=True)
    (d / "addoninfo.gi").write_text('"AddonInfo" {}\n', encoding="utf-8")
    (d / "maps" / "my_map.vmap").write_text("// prior\n", encoding="utf-8")
    state = inspect(cfg, "ported")
    assert state is not None
    assert state.has_prior_port_output is True
    assert state.is_scaffolded is False
    assert state.map_count == 1


def test_inspect_recognizes_our_scaffold(tmp_path: Path) -> None:
    """Our scaffolded dir is identifiable via the marker."""
    cfg = _cfg(tmp_path)
    create(cfg, "ours")
    state = inspect(cfg, "ours")
    assert state is not None
    assert state.scaffolded_by_csgo2cs2 is True
    assert state.is_scaffolded is True


def test_create_makes_minimum_layout(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    d = create(cfg, "fresh")
    assert d == Path(cfg.cs2_addons_path) / "fresh"
    assert (d / "addoninfo.gi").exists()
    assert (d / "maps").is_dir()
    assert SCAFFOLD_MARKER in (d / "addoninfo.gi").read_text(encoding="utf-8")


def test_create_is_idempotent_on_empty_dir(tmp_path: Path) -> None:
    """Calling create() on an existing-but-empty dir succeeds without
    --force; it just fills in the missing scaffolding."""
    cfg = _cfg(tmp_path)
    target = Path(cfg.cs2_addons_path) / "preexisting"
    target.mkdir()
    create(cfg, "preexisting")
    assert (target / "addoninfo.gi").exists()


def test_create_refuses_to_clobber_existing_addon(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    target = Path(cfg.cs2_addons_path) / "ported"
    (target / "maps").mkdir(parents=True)
    (target / "maps" / "my_map.vmap").write_text("hi\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create(cfg, "ported")


def test_create_force_overwrites(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    target = Path(cfg.cs2_addons_path) / "ported"
    (target / "maps").mkdir(parents=True)
    (target / "maps" / "my_map.vmap").write_text("hi\n", encoding="utf-8")
    create(cfg, "ported", force=True)
    assert (target / "addoninfo.gi").exists()
    # force=True rewrites addoninfo but does NOT wipe maps/
    assert (target / "maps" / "my_map.vmap").exists()


def test_create_rejects_when_cs2_addons_path_unset() -> None:
    with pytest.raises(RuntimeError, match="cs2_addons_path is not set"):
        create(Config(), "foo")
