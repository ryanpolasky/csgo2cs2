# tests for the PR5 `about` command.
#
# checks: command runs to exit 0 without config, prints version + author
# + repo, and exposes the same constants the README documents.

from __future__ import annotations

from csgo2cs2 import __version__
from csgo2cs2.cli import build_parser
from csgo2cs2.commands import about_cmd


def test_about_runs_clean_with_no_config(capsys) -> None:
    parser = build_parser()
    args = parser.parse_args(["about"])
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "csgo2cs2" in out
    assert __version__ in out
    assert about_cmd.AUTHOR in out
    assert about_cmd.AUTHOR_HANDLE in out
    assert about_cmd.REPO_URL in out


def test_about_lists_prior_art(capsys) -> None:
    parser = build_parser()
    args = parser.parse_args(["about"])
    args.func(args)
    out = capsys.readouterr().out
    for name, _blurb in about_cmd.PRIOR_ART:
        assert name in out


def test_about_constants_are_what_we_advertise() -> None:
    # the README and PR description reference these. lock them in so
    # someone changing the attribution has to do it consciously.
    assert about_cmd.AUTHOR == "Ryan Polasky"
    assert about_cmd.AUTHOR_HANDLE == "@ryanpolasky"
    assert about_cmd.REPO_URL == "https://github.com/ryanpolasky/csgo2cs2"
    assert len(about_cmd.PRIOR_ART) >= 3
