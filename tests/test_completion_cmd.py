# tests for `csgo2cs2 completion <shell>`.
# we don't try to evaluate the scripts in an actual shell -- just check
# that we emit something coherent for each supported shell.

from __future__ import annotations

import pytest

from csgo2cs2.cli import build_parser
from csgo2cs2.commands.completion_cmd import SUBCOMMANDS


def _run(shell: str, capsys) -> str:
    parser = build_parser()
    args = parser.parse_args(["completion", shell])
    args.config = None
    rc = args.func(args)
    assert rc == 0
    return capsys.readouterr().out


def test_bash_completion_includes_subcommands(capsys) -> None:
    out = _run("bash", capsys)
    assert "complete -F" in out
    for sub in SUBCOMMANDS:
        assert sub in out


def test_zsh_completion_uses_compdef(capsys) -> None:
    out = _run("zsh", capsys)
    assert "#compdef csgo2cs2" in out
    assert "_csgo2cs2" in out
    assert "ct" in out and "t" in out  # --fix-spawns sides
    for sub in SUBCOMMANDS:
        assert sub in out


def test_powershell_completion_uses_register_argumentcompleter(capsys) -> None:
    out = _run("powershell", capsys)
    assert "Register-ArgumentCompleter" in out
    for sub in SUBCOMMANDS:
        assert sub in out


def test_unknown_shell_rejected_by_argparse() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["completion", "fish"])
