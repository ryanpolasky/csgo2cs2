# tests for `csgo2cs2 status <id>` surfacing workshop metadata when
# present in the manifest. exercises the manifest schema's
# back-compat (older manifests without workshop_meta still load) and
# the status renderer.

from __future__ import annotations

from pathlib import Path

from csgo2cs2.cli import build_parser
from csgo2cs2.config import Config, save_config
from csgo2cs2.utils.manifest import PortManifest, WorkshopMeta


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = Config(workspace_dir=str(ws))
    cfg_path = tmp_path / "cfg.json"
    save_config(cfg, str(cfg_path))
    return cfg_path


def _make_manifest(ws: Path, workshop_id: str, *, with_meta: bool) -> Path:
    target = ws / workshop_id / "manifest.json"
    m = PortManifest(workshop_id=workshop_id, addon_name="test_addon")
    if with_meta:
        m.record_workshop_meta(
            WorkshopMeta(
                title="My Custom Map",
                description="A map for serious enthusiasts.",
                creator="76561198000000000",
                tags=["hostage", "casual"],
                preview_url="https://example.com/preview.jpg",
                time_created=1700000000,
                time_updated=1700000100,
                fetched_at=1700000200.0,
            )
        )
    m.save(target)
    return target


def test_status_renders_workshop_metadata_when_present(tmp_path: Path, capsys) -> None:
    cfg_path = _ws(tmp_path)
    ws = tmp_path / "ws"
    _make_manifest(ws, "12345", with_meta=True)

    parser = build_parser()
    args = parser.parse_args(["status", "12345"])
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 0

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "Workshop metadata" in out
    assert "My Custom Map" in out
    assert "76561198000000000" in out
    assert "hostage" in out
    assert "preview.jpg" in out


def test_status_skips_metadata_section_when_absent(tmp_path: Path, capsys) -> None:
    cfg_path = _ws(tmp_path)
    ws = tmp_path / "ws"
    _make_manifest(ws, "67890", with_meta=False)

    parser = build_parser()
    args = parser.parse_args(["status", "67890"])
    args.config = str(cfg_path)
    rc = args.func(args)
    assert rc == 0
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "Workshop metadata" not in out


def test_manifest_loads_old_format_without_workshop_meta(tmp_path: Path) -> None:
    """older manifests written before workshop_meta was added should
    still load cleanly (back-compat guard)."""
    p = tmp_path / "old.json"
    p.write_text(
        '{"workshop_id": "111", "addon_name": "x", "copied_files": [],'
        ' "patched_files": [], "renamed_files": []}\n',
        encoding="utf-8",
    )
    m = PortManifest.load(p)
    assert m.workshop_id == "111"
    assert m.workshop_meta is None


def test_manifest_round_trip_preserves_workshop_meta(tmp_path: Path) -> None:
    p = tmp_path / "rt.json"
    m = PortManifest(workshop_id="222", addon_name="y")
    m.record_workshop_meta(WorkshopMeta(title="t", description="d", tags=["a", "b"]))
    m.save(p)
    m2 = PortManifest.load(p)
    assert m2.workshop_meta is not None
    assert m2.workshop_meta.title == "t"
    assert m2.workshop_meta.tags == ["a", "b"]
