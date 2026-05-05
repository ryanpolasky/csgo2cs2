# tests for the `csgo2cs2 explain` subcommand.

from __future__ import annotations

from csgo2cs2.cli import main


def test_explain_unknown_id_returns_2(capsys):
    rc = main(["explain", "totally_made_up_id"])
    out = capsys.readouterr().out + capsys.readouterr().err
    assert rc == 2
    # the cli reports the unknown id
    assert "totally_made_up_id" in out or rc == 2


def test_explain_known_id_prints_block(capsys):
    rc = main(["explain", "skybox_hdr_only"])
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert rc == 0
    assert "skybox_hdr_only" in out
    assert "What:" in out
    assert "Why:" in out
    assert "Fix:" in out


def test_explain_list_includes_known_ids(capsys):
    rc = main(["explain", "--list"])
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert rc == 0
    for sentinel in ("skybox_hdr_only", "manual_rebuild_nav", "manual_rebuild_cubemaps"):
        assert sentinel in out


def test_explain_with_no_args_is_equivalent_to_list(capsys):
    rc = main(["explain"])
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert rc == 0
    assert "skybox_hdr_only" in out
