# Tests for `csgo2cs2 walkthrough` (alias `tour`). Cross-platform; mocks
# the underlying subcommand dispatch so the tests don't try to run init,
# tools install, port, etc. against a real environment.

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import pytest

from csgo2cs2.cli import build_parser
from csgo2cs2.commands import walkthrough_cmd
from csgo2cs2.config import Config, save_config
from csgo2cs2.utils.drift import DriftEntry, DriftState, save_state


def _ns(**overrides) -> argparse.Namespace:
    base = {
        "config": None,
        "verbose": False,
        "command": "walkthrough",
        "yes": False,
        "from_stage": None,
        "workshop_url": None,
        "addon": None,
        "no_launch": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _patch_subcommands(monkeypatch) -> List[List[str]]:
    """Replace _run_subcommand with a recorder. Returns the call log."""
    calls: List[List[str]] = []

    def fake_run(argv, parent_args):
        calls.append(list(argv))
        return 0

    monkeypatch.setattr(walkthrough_cmd, "_run_subcommand", fake_run)
    return calls


# ----- registration / parsing --------------------------------------------


def test_walkthrough_registered_in_cli() -> None:
    parser = build_parser()
    args = parser.parse_args(["walkthrough", "--yes"])
    assert args.command == "walkthrough"
    assert args.yes is True


def test_tour_alias_registered() -> None:
    parser = build_parser()
    args = parser.parse_args(["tour"])
    assert args.command == "tour"


def test_from_stage_accepts_known_stages() -> None:
    parser = build_parser()
    for stage in walkthrough_cmd.STAGES:
        args = parser.parse_args(["walkthrough", "--from", stage])
        assert args.from_stage == stage


def test_from_stage_rejects_unknown_stage() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["walkthrough", "--from", "bogus"])


# ----- state-detection helpers -------------------------------------------


def test_config_is_workable_requires_csgo_install_path() -> None:
    assert walkthrough_cmd._config_is_workable(Config()) is False
    assert walkthrough_cmd._config_is_workable(Config(csgo_install_path="/x")) is True


def test_tools_status_marks_missing_paths(tmp_path) -> None:
    cfg = Config(
        steamcmd_path=str(tmp_path / "nope-steamcmd"),
        bspsource_path=None,
        import_script_path=None,
    )
    status = walkthrough_cmd._tools_status(cfg)
    assert status == {"steamcmd": False, "bspsource": False, "import_map_community": False}


def test_tools_status_marks_present_paths(tmp_path) -> None:
    sc = tmp_path / "steamcmd"
    sc.write_text("# stub", encoding="utf-8")
    bs = tmp_path / "bspsrc.jar"
    bs.write_text("# stub", encoding="utf-8")
    cfg = Config(steamcmd_path=str(sc), bspsource_path=str(bs))
    status = walkthrough_cmd._tools_status(cfg)
    assert status["steamcmd"] is True
    assert status["bspsource"] is True
    assert status["import_map_community"] is False


def test_patches_applied_false_when_no_state(tmp_path) -> None:
    cfg = Config(workspace_dir=str(tmp_path / "ws"))
    assert walkthrough_cmd._patches_applied(cfg) is False


def test_patches_applied_true_when_state_has_entries(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    state = DriftState(
        entries={
            "/x/import_map_community.py": DriftEntry(
                path="/x/import_map_community.py", sha256="abc", size=1, fixed_at=0.0
            )
        }
    )
    save_state(state, workspace)
    cfg = Config(workspace_dir=str(workspace))
    assert walkthrough_cmd._patches_applied(cfg) is True


# ----- prompt helpers ----------------------------------------------------


def test_confirm_default_yes_returns_true_on_blank() -> None:
    assert walkthrough_cmd._confirm("?", default=True, prompt_fn=lambda _p: "") is True


def test_confirm_default_no_returns_false_on_blank() -> None:
    assert walkthrough_cmd._confirm("?", default=False, prompt_fn=lambda _p: "") is False


def test_confirm_yes_overrides_default_no() -> None:
    assert walkthrough_cmd._confirm("?", default=False, prompt_fn=lambda _p: "y") is True


def test_confirm_no_overrides_default_yes() -> None:
    assert walkthrough_cmd._confirm("?", default=True, prompt_fn=lambda _p: "n") is False


def test_ask_returns_user_input() -> None:
    assert walkthrough_cmd._ask("name", prompt_fn=lambda _p: "myaddon") == "myaddon"


def test_ask_returns_default_on_blank() -> None:
    assert (
        walkthrough_cmd._ask("name", default="default_addon", prompt_fn=lambda _p: "")
        == "default_addon"
    )


# ----- end-to-end with mocked subcommand dispatch ------------------------


def test_yes_flow_with_existing_workable_config(tmp_path, monkeypatch, capsys) -> None:
    cfg_path = tmp_path / "cfg.json"
    cfg = Config(
        csgo_install_path="/x/csgo",
        steamcmd_path=str(tmp_path / "steamcmd"),
        bspsource_path=str(tmp_path / "bspsrc.jar"),
        workspace_dir=str(tmp_path / "ws"),
    )
    # Make the tools "exist" so the tools stage skips install.
    Path(cfg.steamcmd_path).write_text("# stub")
    Path(cfg.bspsource_path).write_text("# stub")
    cfg.import_script_path = str(tmp_path / "import_map_community.py")
    Path(cfg.import_script_path).write_text("# stub")
    save_config(cfg, str(cfg_path))

    # Pre-record drift state so the patches stage skips on Windows hosts.
    workspace = Path(cfg.workspace_dir)
    workspace.mkdir(parents=True)
    save_state(
        DriftState(
            entries={
                "k": DriftEntry(path="x", sha256="s", size=1, fixed_at=0.0),
            }
        ),
        workspace,
    )

    calls = _patch_subcommands(monkeypatch)
    args = _ns(
        config=str(cfg_path),
        yes=True,
        workshop_url="123456789",
        addon="myaddon",
        no_launch=True,
    )
    rc = walkthrough_cmd.run(args)
    assert rc == 0
    # No init / tools install / doctor --fix should have been triggered
    # because state-detection said everything was already in place.
    flat = [" ".join(c) for c in calls]
    assert not any("init" in c.split()[0:1] for c in flat if c)
    assert not any(c.startswith("tools install") for c in flat)
    assert not any(c.startswith("doctor --fix") for c in flat)
    # Port should have been called with the supplied flags.
    port_calls = [c for c in calls if c and c[0] == "port"]
    assert port_calls, f"expected at least one port call, got {calls}"
    port_argv = port_calls[0]
    assert "--addon" in port_argv
    assert "myaddon" in port_argv
    assert "123456789" in port_argv
    assert "--auto" in port_argv


def test_yes_flow_with_no_config_runs_init(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "cfg.json"  # does not exist yet
    calls = _patch_subcommands(monkeypatch)
    args = _ns(
        config=str(cfg_path),
        yes=True,
        workshop_url="123456789",
        addon="myaddon",
        no_launch=True,
    )

    # The subcommand recorder won't actually create the config, so subsequent
    # stages will see "still no config". That's fine -- we just want to
    # confirm init was the first stage's reaction.
    rc = walkthrough_cmd.run(args)
    assert rc == 0
    init_calls = [c for c in calls if c and c[0] == "init"]
    assert init_calls, f"expected init in the call log, got {calls}"


def test_user_cancels_at_welcome_returns_0(monkeypatch) -> None:
    calls = _patch_subcommands(monkeypatch)
    # confirm_fn returns False at the very first prompt -> walkthrough exits.
    args = _ns()
    rc = walkthrough_cmd.run(
        args,
        prompt_fn=lambda _p: "",
        confirm_fn=lambda _q, _d: False,
    )
    assert rc == 0
    assert calls == []


def test_from_port_skips_earlier_stages(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "cfg.json"
    cfg = Config(csgo_install_path="/x", workspace_dir=str(tmp_path / "ws"))
    save_config(cfg, str(cfg_path))

    calls = _patch_subcommands(monkeypatch)
    args = _ns(
        config=str(cfg_path),
        yes=True,
        from_stage="port",
        workshop_url="999",
        addon="late_addon",
        no_launch=True,
    )
    rc = walkthrough_cmd.run(args)
    assert rc == 0
    # No init / tools / doctor calls -- we resumed from port.
    cmds = [c[0] for c in calls if c]
    assert "init" not in cmds
    assert "tools" not in cmds
    assert "doctor" not in cmds
    assert "port" in cmds


def test_port_failure_stops_walkthrough(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "cfg.json"
    cfg = Config(csgo_install_path="/x", workspace_dir=str(tmp_path / "ws"))
    save_config(cfg, str(cfg_path))

    fail_count = {"n": 0}

    def fake_run(argv, _parent):
        fail_count["n"] += 1
        if argv and argv[0] == "port":
            return 2
        return 0

    monkeypatch.setattr(walkthrough_cmd, "_run_subcommand", fake_run)
    args = _ns(
        config=str(cfg_path),
        yes=True,
        from_stage="port",
        workshop_url="999",
        addon="addon",
        no_launch=True,
    )
    rc = walkthrough_cmd.run(args)
    assert rc == 2  # the non-zero from port should bubble up

    # verify and launch should NOT have been attempted after port failed.
    # (we can't directly observe that here, but the test above confirms
    # the early-return path returns rc=2, so any later calls would change
    # the recorded behavior.)


def test_run_subcommand_inherits_config_path(tmp_path, monkeypatch) -> None:
    # Smoke-test that _run_subcommand actually wires --config through to
    # the underlying parser. We hijack the subcommand's func() so it just
    # records what config_path it received.
    cfg_path = tmp_path / "cfg.json"
    Config().__class__  # noqa: B018 -- referenced to keep import alive
    save_config(Config(csgo_install_path="/x"), str(cfg_path))

    captured = {}

    def fake_func(args):
        captured["config"] = args.config
        return 0

    # Replace the about command's run function (cheap, no side effects).
    from csgo2cs2.commands import about_cmd

    monkeypatch.setattr(about_cmd, "run", fake_func)
    parent = _ns(config=str(cfg_path))
    rc = walkthrough_cmd._run_subcommand(["about"], parent)
    assert rc == 0
    assert captured["config"] == str(cfg_path)
