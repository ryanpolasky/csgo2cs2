from __future__ import annotations

from pathlib import Path

from csgo2cs2.config import Config
from csgo2cs2.utils import preflight


def _baseline_cfg(tmp_path: Path) -> Config:
    """A baseline config that has just enough to pass most preflight
    checks. Tests override specific fields to trigger one issue at a
    time."""
    steamcmd = tmp_path / "tools" / "steamcmd" / "steamcmd"
    steamcmd.parent.mkdir(parents=True, exist_ok=True)
    steamcmd.write_text("#!/bin/sh\n", encoding="utf-8")

    bspsource = tmp_path / "tools" / "bspsource" / "bspsrc.jar"
    bspsource.parent.mkdir(parents=True, exist_ok=True)
    bspsource.write_text("fake jar", encoding="utf-8")

    csgo_install = tmp_path / "csgo"
    (csgo_install / "csgo").mkdir(parents=True)
    (csgo_install / "csgo" / "gameinfo.txt").write_text("fake", encoding="utf-8")
    (csgo_install / "game" / "csgo").mkdir(parents=True)
    (csgo_install / "game" / "csgo" / "gameinfo.gi").write_text("fake", encoding="utf-8")

    addons = tmp_path / "addons"
    addons.mkdir()

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    return Config(
        steamcmd_path=str(steamcmd),
        bspsource_path=str(bspsource),
        csgo_install_path=str(csgo_install),
        cs2_addons_path=str(addons),
        workspace_dir=str(workspace),
    )


def test_clean_config_passes(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    report = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)
    assert report.ok, preflight.format_report(report)


def test_missing_addon_is_error(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    report = preflight.run_preflight(cfg, addon="", skip_import=True)
    assert not report.ok
    ids = {i.id for i in report.errors}
    assert "addon_name_empty" in ids


def test_addon_name_uppercase_is_warn(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    report = preflight.run_preflight(cfg, addon="MyAddon", skip_import=True)
    # not a hard error, but should warn
    ids = {i.id for i in report.warnings}
    assert "addon_name_case" in ids


def test_addon_name_invalid_chars(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    report = preflight.run_preflight(cfg, addon="my addon!", skip_import=True)
    assert not report.ok
    ids = {i.id for i in report.errors}
    assert "addon_name_invalid_chars" in ids


def test_missing_steamcmd_is_error(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    cfg.steamcmd_path = "/totally/fake/steamcmd"
    report = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)
    assert not report.ok
    ids = {i.id for i in report.errors}
    assert "tool_not_on_disk_steamcmd_path" in ids


def test_unset_steamcmd_is_error(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    cfg.steamcmd_path = None
    report = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)
    ids = {i.id for i in report.errors}
    assert "tool_missing_steamcmd_path" in ids


def test_addon_collision_blocks_by_default(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    existing = Path(cfg.cs2_addons_path) / "preexisting_addon"
    existing.mkdir()
    report = preflight.run_preflight(cfg, addon="preexisting_addon", skip_import=False)
    ids = {i.id for i in report.errors}
    assert "addon_already_exists" in ids


def test_addon_collision_allowed_with_overwrite(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    existing = Path(cfg.cs2_addons_path) / "preexisting_addon"
    existing.mkdir()
    report = preflight.run_preflight(
        cfg, addon="preexisting_addon", skip_import=False, overwrite=True
    )
    ids = {i.id for i in report.errors}
    assert "addon_already_exists" not in ids


def test_missing_addons_dir_is_error(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    cfg.cs2_addons_path = str(tmp_path / "does-not-exist")
    report = preflight.run_preflight(cfg, addon="my_addon", skip_import=False)
    ids = {i.id for i in report.errors}
    assert "cs2_addons_path_missing" in ids


def test_workspace_with_space_is_error(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    bad = tmp_path / "spaced workspace"
    bad.mkdir()
    cfg.workspace_dir = str(bad)
    report = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)
    ids = {i.id for i in report.errors}
    assert "workspace_has_space" in ids


def test_skip_import_ignores_addons_dir(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    cfg.cs2_addons_path = None
    report = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)
    # cs2_addons_path warnings only fire when we're actually importing
    ids = {i.id for i in report.issues}
    assert "cs2_addons_path_unset" not in ids


def test_format_report_renders_passes_when_empty() -> None:
    rep = preflight.PreflightReport()
    text = preflight.format_report(rep)
    assert "passed" in text.lower()


def test_format_report_renders_issues(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    cfg.steamcmd_path = None
    rep = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)
    text = preflight.format_report(rep)
    assert "tool_missing_steamcmd_path" in text
    assert "ERROR" in text or "error" in text


def test_is_skip_requested_from_env(monkeypatch) -> None:
    monkeypatch.delenv("CSGO2CS2_SKIP_PREFLIGHT", raising=False)
    assert preflight.is_skip_requested() is False
    monkeypatch.setenv("CSGO2CS2_SKIP_PREFLIGHT", "1")
    assert preflight.is_skip_requested() is True


# ---- interactive auto-fix ---------------------------------------------------


def test_autofix_returns_false_when_no_fixable_error(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    # workspace is fine -> the report has no fixable errors
    report = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)
    assert preflight.try_autofix_interactive(
        cfg, None, report, prompt_fn=lambda _p: ""
    ) is False


def test_autofix_relocates_workspace_when_user_accepts_default(tmp_path: Path) -> None:
    """The canonical use case: workspace_dir contains a space, user
    presses Enter to accept the suggested path. Config gets re-written
    and the next preflight pass will see the new workspace."""
    cfg = _baseline_cfg(tmp_path)
    spaced = tmp_path / "has space"
    spaced.mkdir()
    cfg.workspace_dir = str(spaced)
    cfg_path = tmp_path / "cfg.json"
    from csgo2cs2.config import save_config

    save_config(cfg, str(cfg_path))

    report = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)
    assert any(i.id == "workspace_has_space" for i in report.errors)

    # accept the suggestion by typing an empty response. Override the
    # suggested default so we don't actually mkdir into C:\csgo2cs2.
    override = tmp_path / "csgo2cs2" / "workspace"
    monkeypatched: list[Path] = []

    import csgo2cs2.utils.preflight as pf

    pf_default = pf._default_safe_workspace
    pf._default_safe_workspace = lambda: override  # type: ignore[assignment]
    try:
        applied = pf.try_autofix_interactive(
            cfg, str(cfg_path), report, prompt_fn=lambda _p: ""
        )
    finally:
        pf._default_safe_workspace = pf_default  # type: ignore[assignment]

    assert applied is True
    assert cfg.workspace_dir == str(override)
    assert override.exists()
    # re-running preflight on the mutated cfg should clear the issue
    report2 = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)
    assert not any(i.id == "workspace_has_space" for i in report2.errors)
    # the persisted config on disk should also reflect the new path
    from csgo2cs2.config import load_config

    on_disk = load_config(str(cfg_path))
    assert on_disk.workspace_dir == str(override)
    # variable kept to silence unused-checker
    _ = monkeypatched


def test_autofix_rejects_user_typed_path_that_also_has_space(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    spaced = tmp_path / "with space"
    spaced.mkdir()
    cfg.workspace_dir = str(spaced)
    cfg_path = tmp_path / "cfg.json"
    from csgo2cs2.config import save_config

    save_config(cfg, str(cfg_path))
    report = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)

    bad = str(tmp_path / "also has space")
    applied = preflight.try_autofix_interactive(
        cfg, str(cfg_path), report, prompt_fn=lambda _p: bad
    )
    assert applied is False
    # original (unfixed) workspace remains
    assert cfg.workspace_dir == str(spaced)


def test_autofix_cancelled_by_keyboard_interrupt(tmp_path: Path) -> None:
    cfg = _baseline_cfg(tmp_path)
    spaced = tmp_path / "spc"
    spaced.mkdir()
    cfg.workspace_dir = str(tmp_path / "with space")  # nonexistent dir + space
    report = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)
    # workspace_dir parent (tmp_path) exists & is writable; the "with
    # space" leaf doesn't matter for the space check.
    if not any(i.id == "workspace_has_space" for i in report.errors):
        # baseline config's workspace exists; tweak so the space check fires.
        cfg.workspace_dir = str(tmp_path / "ohno space")
        report = preflight.run_preflight(cfg, addon="my_addon", skip_import=True)

    def cancel(_p: str) -> str:
        raise KeyboardInterrupt

    applied = preflight.try_autofix_interactive(cfg, None, report, prompt_fn=cancel)
    assert applied is False
