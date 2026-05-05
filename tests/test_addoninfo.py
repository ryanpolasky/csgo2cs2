# tests for the addoninfo writer + thumbnail copier.
#
# fully filesystem-based, no network. uses synthetic WorkshopMetadata
# instances to exercise the full set of "user-authored vs auto" cases.

from __future__ import annotations

import json
from pathlib import Path

from csgo2cs2.utils import addoninfo
from csgo2cs2.utils.workshop_meta import WorkshopMetadata


def _meta(**overrides) -> WorkshopMetadata:
    base = {
        "workshop_id": "12345",
        "title": "My Workshop Map",
        "description": "Cool description.",
        "preview_url": "https://akamai.steam/foo.jpg?token=abc",
        "tags": ["Hostage", "Custom"],
        "creator": "76561111",
        "time_created": 1000,
        "time_updated": 2000,
    }
    base.update(overrides)
    return WorkshopMetadata(**base)


# --- write_addoninfo --------------------------------------------------------


def test_write_addoninfo_writes_json_when_dir_is_empty(tmp_path: Path) -> None:
    target = addoninfo.write_addoninfo(_meta(), tmp_path)
    assert target is not None
    assert target.name == "addoninfo.json"
    payload = json.loads(target.read_text())
    assert payload["title"] == "My Workshop Map"
    assert payload["description"] == "Cool description."
    assert payload["tags"] == ["Hostage", "Custom"]
    assert payload["workshop_id"] == "12345"
    assert payload[addoninfo.SENTINEL_KEY] == addoninfo.SENTINEL_VALUE


def test_write_addoninfo_skips_user_authored(tmp_path: Path) -> None:
    user = tmp_path / "addoninfo.json"
    user.write_text('{"title": "USER VERSION", "description": "hand-edited."}\n')
    target = addoninfo.write_addoninfo(_meta(), tmp_path)
    assert target is None
    # user file untouched
    payload = json.loads(user.read_text())
    assert payload["title"] == "USER VERSION"


def test_write_addoninfo_skips_user_gi_file(tmp_path: Path) -> None:
    # .gi is keyvalues format -- we don't try to parse it; mere presence
    # is enough to leave the addon alone (don't write a .json next to a
    # .gi the user authored).
    user = tmp_path / "addoninfo.gi"
    user.write_text('"AddonInfo"\n{\n\t"title" "USER"\n}\n')
    target = addoninfo.write_addoninfo(_meta(), tmp_path)
    assert target is None
    assert not (tmp_path / "addoninfo.json").exists()


def test_write_addoninfo_overwrites_prior_auto_populated(tmp_path: Path) -> None:
    # first write
    addoninfo.write_addoninfo(_meta(title="V1"), tmp_path)
    # second write with new data
    target = addoninfo.write_addoninfo(_meta(title="V2"), tmp_path)
    assert target is not None
    payload = json.loads(target.read_text())
    assert payload["title"] == "V2"


def test_write_addoninfo_force_overrides_user_authored(tmp_path: Path) -> None:
    user = tmp_path / "addoninfo.json"
    user.write_text('{"title": "USER"}\n')
    target = addoninfo.write_addoninfo(_meta(), tmp_path, force=True)
    assert target is not None
    payload = json.loads(target.read_text())
    assert payload["title"] == "My Workshop Map"


def test_write_addoninfo_falls_back_to_workshop_id_when_no_title(tmp_path: Path) -> None:
    target = addoninfo.write_addoninfo(_meta(title=None), tmp_path)
    payload = json.loads(target.read_text())
    assert payload["title"] == "Workshop 12345"


# --- copy_thumbnail ---------------------------------------------------------


def test_copy_thumbnail_writes_jpg(tmp_path: Path) -> None:
    src = tmp_path / "preview.jpg"
    src.write_bytes(b"fake-jpeg")
    addon = tmp_path / "addon"
    addon.mkdir()
    target = addoninfo.copy_thumbnail(src, addon)
    assert target is not None
    assert target.name == "addonimage.jpg"
    assert target.read_bytes() == b"fake-jpeg"


def test_copy_thumbnail_writes_png_when_source_is_png(tmp_path: Path) -> None:
    src = tmp_path / "preview.png"
    src.write_bytes(b"fake-png")
    addon = tmp_path / "addon"
    addon.mkdir()
    target = addoninfo.copy_thumbnail(src, addon)
    assert target is not None
    assert target.name == "addonimage.png"


def test_copy_thumbnail_returns_none_when_source_missing(tmp_path: Path) -> None:
    addon = tmp_path / "addon"
    addon.mkdir()
    assert addoninfo.copy_thumbnail(None, addon) is None
    assert addoninfo.copy_thumbnail(tmp_path / "no-such.jpg", addon) is None


def test_copy_thumbnail_skips_existing_user_thumbnail(tmp_path: Path) -> None:
    addon = tmp_path / "addon"
    addon.mkdir()
    existing = addon / "addonimage.jpg"
    existing.write_bytes(b"USER-THUMB")
    src = tmp_path / "preview.jpg"
    src.write_bytes(b"FROM-WORKSHOP")
    target = addoninfo.copy_thumbnail(src, addon)
    assert target is None
    assert existing.read_bytes() == b"USER-THUMB"


def test_copy_thumbnail_force_replaces_existing(tmp_path: Path) -> None:
    addon = tmp_path / "addon"
    addon.mkdir()
    existing = addon / "addonimage.jpg"
    existing.write_bytes(b"USER-THUMB")
    src = tmp_path / "preview.jpg"
    src.write_bytes(b"FROM-WORKSHOP")
    target = addoninfo.copy_thumbnail(src, addon, force=True)
    assert target is not None
    assert target.read_bytes() == b"FROM-WORKSHOP"


def test_copy_thumbnail_normalizes_unknown_extension(tmp_path: Path) -> None:
    src = tmp_path / "preview.tiff"
    src.write_bytes(b"weird-image")
    addon = tmp_path / "addon"
    addon.mkdir()
    target = addoninfo.copy_thumbnail(src, addon)
    assert target is not None
    assert target.name == "addonimage.jpg"
