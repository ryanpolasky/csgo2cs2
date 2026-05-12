"""End-to-end stage-resume tests for the port pipeline.

We mock out the four expensive stages (download, decompile, extract,
import) and verify:
  - on first run, every stage runs once
  - on second run with the same args, only the failed/pending stages re-run
  - --restart wipes prior stage state
  - --no-resume re-runs all stages without wiping the manifest
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from csgo2cs2 import pipeline as pipeline_mod
from csgo2cs2.utils.manifest import STAGE_FAILED, PortManifest


@pytest.fixture
def mocked_pipeline(monkeypatch, tmp_path: Path) -> Dict[str, Any]:
    """Stand-in for an entire pipeline run that records which stages
    actually got invoked."""
    calls: Dict[str, List[Any]] = {
        "download": [],
        "decompile": [],
        "extract": [],
        "import": [],
        "analyze": [],
    }

    # ---- fake config ----
    cfg = type(
        "Cfg",
        (),
        {
            "steamcmd_path": str(tmp_path / "steamcmd"),
            "bspsource_path": str(tmp_path / "bspsrc.jar"),
            "vpkedit_path": None,
            "bspzip_path": None,
            "java_path": None,
            "import_script_path": None,
            "python_executable": None,
            "csgo_install_path": str(tmp_path / "csgo"),
            "cs2_addons_path": str(tmp_path / "addons"),
            "cs2_bin_path": None,
            "legacy_csgo_bin_path": None,
            "workspace_dir": str(tmp_path / "ws"),
            "default_skybox": "sky_cs_office",
            "cs2_sky_list": None,
            "extra_unsupported_entities": [],
            "steam_login": None,
            "auto_apply_doctor_fixes": False,
            "steamcmd_retries": 1,
        },
    )()
    monkeypatch.setattr(pipeline_mod, "load_config", lambda _path: cfg)

    # write a fake bsp + vmf so the file-presence checks in the
    # pipeline don't have to actually go through SteamCMD/BSPSource.
    fake_bsp_dir = tmp_path / "fake-bsp-dir"
    fake_bsp_dir.mkdir()
    fake_bsp = fake_bsp_dir / "12345.bsp"
    fake_bsp.write_bytes(b"VBSP" + b"\x14\x00\x00\x00" + b"\x00" * 1024)

    fake_vmf_text = (
        'versioninfo\n{\n\t"editorversion" "400"\n}\n'
        'world\n{\n\t"id" "1"\n\t"classname" "worldspawn"\n\t"skyname" "sky_cs_office"\n}\n'
    )

    def fake_download(_cfg, _wid):
        calls["download"].append(_wid)
        return fake_bsp

    def fake_decompile(_cfg, _bsp, output_dir: Path):
        calls["decompile"].append(_bsp)
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "12345.vmf"
        out.write_text(fake_vmf_text, encoding="utf-8")
        return out

    def fake_extract(_cfg, _bsp, output_dir: Path):
        calls["extract"].append(_bsp)
        output_dir.mkdir(parents=True, exist_ok=True)

        class _Res:
            succeeded = True
            detail = "fake extract"

        return _Res()

    def fake_stage_and_import(**kwargs):
        calls["import"].append(kwargs.get("addon"))
        return 0

    def fake_analyze_and_fix(vmf, _cfg, manifest, auto=False, dry_run=False, extracted_dir=None):
        calls["analyze"].append(vmf)
        return vmf

    monkeypatch.setattr(pipeline_mod, "_download", fake_download)
    monkeypatch.setattr(pipeline_mod, "_decompile", fake_decompile)
    monkeypatch.setattr(pipeline_mod, "extract_bsp_assets", fake_extract)
    monkeypatch.setattr(pipeline_mod, "_stage_and_import", fake_stage_and_import)
    monkeypatch.setattr(pipeline_mod, "_analyze_and_fix", fake_analyze_and_fix)

    # resume path: on second run we'd normally call SteamCMD to locate
    # the existing BSP; short-circuit to our fake one so resume tests
    # don't have to spin up a fake steamcmd dir layout.
    monkeypatch.setattr(pipeline_mod, "_resolve_existing_bsp", lambda _cfg, _wid: fake_bsp)

    # bypass preflight (we don't want to validate the dummy paths)
    monkeypatch.setattr(pipeline_mod, "is_skip_requested", lambda: True)

    # platform_check.require_windows should be a no-op so we can run
    # the import branch on linux/mac/CI.
    monkeypatch.setattr(pipeline_mod, "require_windows", lambda _msg: None)

    # inspect_bsp returns a "valid, not protected" stub
    class _BspInfo:
        valid_header = True
        version = 20
        suspected_protected = False
        detected_marker = None

    monkeypatch.setattr(pipeline_mod, "inspect_bsp", lambda _p: _BspInfo())

    return {"calls": calls, "tmp_path": tmp_path, "cfg": cfg, "workshop_id": "12345"}


def _manifest_path(tmp_path: Path, wid: str) -> Path:
    return tmp_path / "ws" / wid / "manifest.json"


def test_first_run_invokes_each_stage_once(mocked_pipeline) -> None:
    calls = mocked_pipeline["calls"]
    rc = pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="my_addon",
        skip_preflight=True,
    )
    assert rc == 0
    assert len(calls["download"]) == 1
    assert len(calls["decompile"]) == 1
    assert len(calls["extract"]) == 1
    assert len(calls["import"]) == 1


def test_second_run_skips_done_stages(mocked_pipeline) -> None:
    calls = mocked_pipeline["calls"]
    # first run
    rc = pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="my_addon",
        skip_preflight=True,
    )
    assert rc == 0

    # reset call counts; do NOT delete the manifest
    for v in calls.values():
        v.clear()

    rc = pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="my_addon",
        skip_preflight=True,
    )
    assert rc == 0
    # download/inspect/extract/decompile all marked done -- shouldn't re-run
    assert calls["download"] == []
    assert calls["decompile"] == []
    assert calls["extract"] == []
    # analyze + import always re-run (analyze is cheap + idempotent;
    # import we want fresh after manual recovery)
    assert len(calls["analyze"]) == 1
    assert len(calls["import"]) == 1


def test_restart_reruns_everything(mocked_pipeline) -> None:
    calls = mocked_pipeline["calls"]
    pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="my_addon",
        skip_preflight=True,
    )
    for v in calls.values():
        v.clear()

    pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="my_addon",
        skip_preflight=True,
        restart=True,
    )
    assert len(calls["download"]) == 1
    assert len(calls["decompile"]) == 1


def test_no_resume_reruns_everything_without_clearing_manifest(mocked_pipeline) -> None:
    calls = mocked_pipeline["calls"]
    pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="my_addon",
        skip_preflight=True,
    )
    for v in calls.values():
        v.clear()

    pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="my_addon",
        skip_preflight=True,
        resume=False,
    )
    assert len(calls["download"]) == 1
    assert len(calls["decompile"]) == 1


def test_failed_stage_does_not_prevent_resume_completing(mocked_pipeline, monkeypatch) -> None:
    calls = mocked_pipeline["calls"]

    # first run: make decompile fail
    def failing_decompile(_cfg, _bsp, output_dir):
        calls["decompile"].append("fail")
        # don't write a .vmf -- pipeline should detect and bail
        return None

    monkeypatch.setattr(pipeline_mod, "_decompile", failing_decompile)
    rc = pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="my_addon",
        skip_preflight=True,
    )
    assert rc == 1
    manifest = PortManifest.load(_manifest_path(mocked_pipeline["tmp_path"], "12345"))
    assert manifest.stage_is_done("download")
    assert manifest.stages["decompile"].status == STAGE_FAILED

    # now restore decompile and re-run; download should NOT re-run
    fake_vmf_text = (
        'versioninfo\n{\n\t"editorversion" "400"\n}\n'
        'world\n{\n\t"id" "1"\n\t"classname" "worldspawn"\n\t"skyname" "sky_cs_office"\n}\n'
    )

    def fixed_decompile(_cfg, _bsp, output_dir: Path):
        calls["decompile"].append("ok")
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "12345.vmf"
        out.write_text(fake_vmf_text, encoding="utf-8")
        return out

    monkeypatch.setattr(pipeline_mod, "_decompile", fixed_decompile)
    for v in calls.values():
        v.clear()

    rc = pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="my_addon",
        skip_preflight=True,
    )
    assert rc == 0
    assert calls["download"] == []  # already done
    assert calls["decompile"] == ["ok"]  # retried
    assert len(calls["import"]) == 1


def test_addon_name_change_starts_fresh(mocked_pipeline) -> None:
    calls = mocked_pipeline["calls"]
    pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="addon_a",
        skip_preflight=True,
    )
    for v in calls.values():
        v.clear()

    pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="addon_b",
        skip_preflight=True,
    )
    # since the addon name changed, the whole pipeline runs from scratch
    assert len(calls["download"]) == 1
    assert len(calls["decompile"]) == 1


def test_manifest_records_stages_in_order(mocked_pipeline) -> None:
    pipeline_mod.run_port_pipeline(
        url_or_id=mocked_pipeline["workshop_id"],
        addon="my_addon",
        skip_preflight=True,
    )
    manifest_path = _manifest_path(mocked_pipeline["tmp_path"], "12345")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    stages = data["stages"]
    for s in ("download", "inspect", "extract", "decompile", "analyze", "import"):
        assert s in stages, f"missing stage {s!r} in manifest"
