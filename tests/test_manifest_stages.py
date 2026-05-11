from __future__ import annotations

from pathlib import Path

from csgo2cs2.utils.manifest import (
    PORT_STAGES,
    STAGE_DONE,
    STAGE_FAILED,
    STAGE_SKIPPED,
    PortManifest,
)


def test_port_stages_in_canonical_order() -> None:
    # we must always have the 6 documented stages, in order.
    assert PORT_STAGES == (
        "download",
        "inspect",
        "extract",
        "decompile",
        "analyze",
        "import",
    )


def test_start_and_finish_stage_records_timestamps() -> None:
    m = PortManifest(workshop_id="123", addon_name="my_addon")
    rec = m.start_stage("download")
    assert rec.status == "running"
    assert rec.started_at is not None
    m.finish_stage("download", STAGE_DONE)
    assert m.stages["download"].status == STAGE_DONE
    assert m.stages["download"].ended_at is not None
    assert m.stage_is_done("download")


def test_finish_stage_failed_records_detail() -> None:
    m = PortManifest(workshop_id="123", addon_name="my_addon")
    m.start_stage("decompile")
    m.finish_stage("decompile", STAGE_FAILED, "no .vmf produced")
    rec = m.stages["decompile"]
    assert rec.status == STAGE_FAILED
    assert rec.detail == "no .vmf produced"


def test_stage_is_done_false_for_unstarted() -> None:
    m = PortManifest(workshop_id="123", addon_name="my_addon")
    assert not m.stage_is_done("download")


def test_save_and_load_round_trips_stages(tmp_path: Path) -> None:
    m = PortManifest(workshop_id="123", addon_name="my_addon")
    m.start_stage("download")
    m.finish_stage("download", STAGE_DONE, "ok")
    m.start_stage("inspect")
    m.finish_stage("inspect", STAGE_SKIPPED, "local --bsp")
    m.last_args = {"auto": True}

    path = tmp_path / "manifest.json"
    m.save(path)

    loaded = PortManifest.load(path)
    assert loaded.workshop_id == "123"
    assert loaded.addon_name == "my_addon"
    assert loaded.last_args == {"auto": True}
    assert loaded.stage_is_done("download")
    assert loaded.stages["inspect"].status == STAGE_SKIPPED
    assert loaded.stages["inspect"].detail == "local --bsp"


def test_load_backward_compat_no_stages(tmp_path: Path) -> None:
    # manifest written by an older version (no `stages` or `last_args`).
    legacy = {
        "workshop_id": "123",
        "addon_name": "my_addon",
        "copied_files": [],
        "patched_files": [],
        "renamed_files": [],
    }
    import json as _json

    path = tmp_path / "manifest.json"
    path.write_text(_json.dumps(legacy), encoding="utf-8")
    loaded = PortManifest.load(path)
    assert loaded.workshop_id == "123"
    assert loaded.stages == {}
    assert loaded.last_args == {}
    # stage_is_done remains a safe no-op
    assert not loaded.stage_is_done("download")


def test_stage_elapsed_is_a_number_after_finish() -> None:
    m = PortManifest(workshop_id="123", addon_name="my_addon")
    m.start_stage("download")
    m.finish_stage("download", STAGE_DONE)
    rec = m.stages["download"]
    assert rec.elapsed is not None
    assert rec.elapsed >= 0


def test_restart_workflow_overwrites_status() -> None:
    m = PortManifest(workshop_id="123", addon_name="my_addon")
    m.start_stage("download")
    m.finish_stage("download", STAGE_FAILED, "first attempt")
    assert m.stages["download"].status == STAGE_FAILED

    # restart that stage
    m.start_stage("download")
    assert m.stages["download"].status == "running"
    m.finish_stage("download", STAGE_DONE, "retry succeeded")
    assert m.stages["download"].status == STAGE_DONE
    assert m.stages["download"].detail == "retry succeeded"
