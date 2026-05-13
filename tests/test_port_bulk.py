"""Tests for `csgo2cs2 port-bulk`. We stub out the per-map runner and
the downloader so the suite is fast + platform-independent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List

import pytest

from csgo2cs2.cli import build_parser
from csgo2cs2.commands import port_bulk
from csgo2cs2.config import Config, save_config


def _cfg(tmp_path: Path, *, with_addons: bool = False) -> Path:
    """Write a minimal config under tmp_path and return its path."""
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True)
    addons = tmp_path / "addons"
    if with_addons:
        addons.mkdir(parents=True)
    cfg = Config(
        workspace_dir=str(workspace),
        cs2_addons_path=str(addons) if with_addons else None,
    )
    cfg_path = tmp_path / "cfg.json"
    save_config(cfg, str(cfg_path))
    return cfg_path


def _seed_bsp(tmp_path: Path, workshop_id: str, map_name: str) -> Path:
    """Place a fake .bsp where the pipeline would have downloaded one
    so _resolve_addon_for can find it without invoking SteamCMD."""
    bsp_dir = tmp_path / "ws" / workshop_id / "unwrap" / workshop_id
    bsp_dir.mkdir(parents=True, exist_ok=True)
    bsp = bsp_dir / f"{map_name}.bsp"
    bsp.write_bytes(b"VBSP\x15\x00\x00\x00")
    return bsp


# parsing --------------------------------------------------


def test_parse_from_file_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text(
        "# header comment\n"
        "\n"
        "419404847\n"
        "1129516277  # jungle\n"
        "\n"
        "https://steamcommunity.com/sharedfiles/filedetails/?id=12345\n",
        encoding="utf-8",
    )
    ids = port_bulk._parse_from_file(f)
    assert ids == [
        "419404847",
        "1129516277",
        "https://steamcommunity.com/sharedfiles/filedetails/?id=12345",
    ]


def test_collect_inputs_deduplicates_by_workshop_id(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("419404847\nhttps://steamcommunity.com/?id=419404847\n", encoding="utf-8")
    # positional adds the same ID a third time
    out = port_bulk._collect_inputs(["419404847"], f)
    assert len(out) == 1


def test_collect_inputs_keeps_invalid_entries_for_failure_reporting(tmp_path: Path) -> None:
    out = port_bulk._collect_inputs(["not-an-id", "419404847"], None)
    assert "not-an-id" in out
    assert "419404847" in out


# addon resolution -----------------------------------------


def test_resolve_addon_with_workshop_id_template(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)
    cfg = port_bulk.load_config(str(cfg_path))
    addon, map_name = port_bulk._resolve_addon_for("419404847", "ws_{workshop_id}", cfg)
    assert addon == "ws_419404847"
    assert map_name is None  # not looked up because template doesn't need it


def test_resolve_addon_uses_existing_bsp_without_calling_downloader(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)
    cfg = port_bulk.load_config(str(cfg_path))
    _seed_bsp(tmp_path, "419404847", "recoil_master")

    def boom_downloader(*args, **kwargs):
        raise AssertionError("downloader should not be called when BSP already on disk")

    addon, map_name = port_bulk._resolve_addon_for(
        "419404847", "{map_name}", cfg, downloader=boom_downloader
    )
    assert addon == "recoil_master"
    assert map_name == "recoil_master"


def test_resolve_addon_invokes_downloader_when_no_bsp(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)
    cfg = port_bulk.load_config(str(cfg_path))
    called: List[str] = []

    def stub_downloader(cfg: Config, workshop_id: str) -> Path:
        called.append(workshop_id)
        return _seed_bsp(tmp_path, workshop_id, "jungle")

    addon, map_name = port_bulk._resolve_addon_for(
        "1129516277", "{map_name}", cfg, downloader=stub_downloader
    )
    assert called == ["1129516277"]
    assert map_name == "jungle"
    assert addon == "jungle"


def test_resolve_addon_rejects_unknown_template_keys(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)
    cfg = port_bulk.load_config(str(cfg_path))
    with pytest.raises(RuntimeError, match="bad --addon-template"):
        port_bulk._resolve_addon_for("419404847", "{nope}", cfg)


# already-ported probe -------------------------------------


def test_already_ported_false_without_addons_path(tmp_path: Path) -> None:
    cfg = Config()  # cs2_addons_path is None
    assert port_bulk._already_ported(cfg, "x", "x") is False


def test_already_ported_false_without_map_name(tmp_path: Path) -> None:
    cfg = Config(cs2_addons_path=str(tmp_path))
    assert port_bulk._already_ported(cfg, "x", None) is False


def test_already_ported_true_when_vmap_exists(tmp_path: Path) -> None:
    addons = tmp_path / "addons"
    vmap = addons / "jungle" / "maps" / "jungle.vmap"
    vmap.parent.mkdir(parents=True)
    vmap.write_text("vmap", encoding="utf-8")
    cfg = Config(cs2_addons_path=str(addons))
    assert port_bulk._already_ported(cfg, "jungle", "jungle") is True


# end-to-end via run_bulk ----------------------------------


def _make_runner(returns: dict[str, int]) -> Callable[..., int]:
    """Return a runner stub that maps workshop_id -> return code."""
    calls: list[dict] = []

    def runner(**kwargs) -> int:
        calls.append(kwargs)
        wid = kwargs.get("url_or_id", "")
        for key, rc in returns.items():
            if key in str(wid):
                return rc
        return 0

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def test_run_bulk_succeeds_for_all_ids(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)
    _seed_bsp(tmp_path, "419404847", "recoil_master")
    _seed_bsp(tmp_path, "1129516277", "jungle")
    runner = _make_runner({})

    rc = port_bulk.run_bulk(
        positional=["419404847", "1129516277"],
        from_file=None,
        addon_template="{map_name}",
        continue_on_failure=False,
        overwrite=False,
        auto=True,
        skip_import=False,
        debug=False,
        dry_run=False,
        manifest_path=None,
        config_path=str(cfg_path),
        downloader=None,
        runner=runner,
    )
    assert rc == 0
    assert len(runner.calls) == 2  # type: ignore[attr-defined]
    assert runner.calls[0]["addon"] == "recoil_master"  # type: ignore[attr-defined]
    assert runner.calls[1]["addon"] == "jungle"  # type: ignore[attr-defined]


def test_run_bulk_stops_on_first_failure_by_default(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)
    _seed_bsp(tmp_path, "111", "alpha")
    _seed_bsp(tmp_path, "222", "beta")
    _seed_bsp(tmp_path, "333", "gamma")
    runner = _make_runner({"222": 1})  # middle one fails

    rc = port_bulk.run_bulk(
        positional=["111", "222", "333"],
        from_file=None,
        addon_template="{map_name}",
        continue_on_failure=False,
        overwrite=False,
        auto=True,
        skip_import=False,
        debug=False,
        dry_run=False,
        manifest_path=None,
        config_path=str(cfg_path),
        downloader=None,
        runner=runner,
    )
    assert rc == 1
    # third map should not have been attempted
    attempted = [c["url_or_id"] for c in runner.calls]  # type: ignore[attr-defined]
    assert "333" not in attempted
    assert "222" in attempted


def test_run_bulk_continues_with_flag(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)
    _seed_bsp(tmp_path, "111", "alpha")
    _seed_bsp(tmp_path, "222", "beta")
    _seed_bsp(tmp_path, "333", "gamma")
    runner = _make_runner({"222": 1})

    rc = port_bulk.run_bulk(
        positional=["111", "222", "333"],
        from_file=None,
        addon_template="{map_name}",
        continue_on_failure=True,
        overwrite=False,
        auto=True,
        skip_import=False,
        debug=False,
        dry_run=False,
        manifest_path=None,
        config_path=str(cfg_path),
        downloader=None,
        runner=runner,
    )
    assert rc == 1  # overall rc still failure
    attempted = [c["url_or_id"] for c in runner.calls]  # type: ignore[attr-defined]
    assert attempted == ["111", "222", "333"]


def test_run_bulk_skips_already_ported_unless_overwrite(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path, with_addons=True)
    _seed_bsp(tmp_path, "111", "alpha")
    # pre-populate the addon as already ported
    vmap = tmp_path / "addons" / "alpha" / "maps" / "alpha.vmap"
    vmap.parent.mkdir(parents=True)
    vmap.write_text("", encoding="utf-8")
    runner = _make_runner({})

    rc = port_bulk.run_bulk(
        positional=["111"],
        from_file=None,
        addon_template="{map_name}",
        continue_on_failure=False,
        overwrite=False,
        auto=True,
        skip_import=False,
        debug=False,
        dry_run=False,
        manifest_path=None,
        config_path=str(cfg_path),
        downloader=None,
        runner=runner,
    )
    assert rc == 0
    assert runner.calls == []  # type: ignore[attr-defined]


def test_run_bulk_overwrite_forces_reprocess(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path, with_addons=True)
    _seed_bsp(tmp_path, "111", "alpha")
    vmap = tmp_path / "addons" / "alpha" / "maps" / "alpha.vmap"
    vmap.parent.mkdir(parents=True)
    vmap.write_text("", encoding="utf-8")
    runner = _make_runner({})

    rc = port_bulk.run_bulk(
        positional=["111"],
        from_file=None,
        addon_template="{map_name}",
        continue_on_failure=False,
        overwrite=True,
        auto=True,
        skip_import=False,
        debug=False,
        dry_run=False,
        manifest_path=None,
        config_path=str(cfg_path),
        downloader=None,
        runner=runner,
    )
    assert rc == 0
    assert len(runner.calls) == 1  # type: ignore[attr-defined]


def test_run_bulk_dry_run_skips_runner_and_downloader(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)

    def boom_runner(**kwargs):
        raise AssertionError("runner should not be called in --dry-run")

    def boom_downloader(*args, **kwargs):
        raise AssertionError("downloader should not be called in --dry-run")

    # use a workshop_id template so we don't need a BSP
    rc = port_bulk.run_bulk(
        positional=["111", "222"],
        from_file=None,
        addon_template="dry_{workshop_id}",
        continue_on_failure=False,
        overwrite=False,
        auto=True,
        skip_import=False,
        debug=False,
        dry_run=True,
        manifest_path=None,
        config_path=str(cfg_path),
        downloader=boom_downloader,
        runner=boom_runner,
    )
    assert rc == 0


def test_run_bulk_writes_manifest(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)
    _seed_bsp(tmp_path, "111", "alpha")
    manifest_path = tmp_path / "bulk.json"
    runner = _make_runner({})

    rc = port_bulk.run_bulk(
        positional=["111"],
        from_file=None,
        addon_template="{map_name}",
        continue_on_failure=False,
        overwrite=False,
        auto=True,
        skip_import=False,
        debug=False,
        dry_run=False,
        manifest_path=manifest_path,
        config_path=str(cfg_path),
        downloader=None,
        runner=runner,
    )
    assert rc == 0
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["succeeded"] == 1
    assert payload["failed"] == 0
    assert payload["entries"][0]["workshop_id"] == "111"
    assert payload["entries"][0]["addon"] == "alpha"
    assert payload["entries"][0]["status"] == "ok"


def test_run_bulk_reports_invalid_workshop_id(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)
    runner = _make_runner({})

    rc = port_bulk.run_bulk(
        positional=["not-an-id"],
        from_file=None,
        addon_template="{workshop_id}",
        continue_on_failure=True,
        overwrite=False,
        auto=True,
        skip_import=False,
        debug=False,
        dry_run=False,
        manifest_path=None,
        config_path=str(cfg_path),
        downloader=None,
        runner=runner,
    )
    assert rc == 1
    assert runner.calls == []  # type: ignore[attr-defined]


def test_run_bulk_empty_input_returns_usage_error(tmp_path: Path) -> None:
    cfg_path = _cfg(tmp_path)
    rc = port_bulk.run_bulk(
        positional=[],
        from_file=None,
        addon_template="{map_name}",
        continue_on_failure=False,
        overwrite=False,
        auto=True,
        skip_import=False,
        debug=False,
        dry_run=False,
        manifest_path=None,
        config_path=str(cfg_path),
        downloader=None,
        runner=lambda **kwargs: 0,
    )
    assert rc == 2


# argparse integration -------------------------------------


def test_cli_register_creates_port_bulk_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "port-bulk",
            "419404847",
            "1129516277",
            "--addon-template",
            "{map_name}",
            "--continue-on-failure",
            "--dry-run",
        ]
    )
    assert args.command == "port-bulk"
    assert args.ids == ["419404847", "1129516277"]
    assert args.addon_template == "{map_name}"
    assert args.continue_on_failure is True
    assert args.dry_run is True
