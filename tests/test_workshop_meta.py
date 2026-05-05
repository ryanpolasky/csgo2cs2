# tests for the workshop metadata fetcher + exporter.
#
# never hits the live Steam api. we monkeypatch
# `urllib.request.build_opener` (via the `_opener` injection point on
# fetch_metadata) and the http downloader the exporter uses, so the
# tests run offline and deterministically.

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from csgo2cs2.utils import workshop_meta

# --- helpers ---------------------------------------------------------------


def _fake_steam_response(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_a) -> None:
        pass

    def read(self) -> bytes:
        return self._body


class _FakeOpener:
    def __init__(self, body: bytes, *, raise_oserror: bool = False) -> None:
        self.body = body
        self.last_request = None
        self.raise_oserror = raise_oserror

    def open(self, request, timeout=None):  # noqa: A002 (mimic urllib api)
        self.last_request = request
        if self.raise_oserror:
            raise OSError("connection refused")
        return _FakeResponse(self.body)


# --- fetch_metadata --------------------------------------------------------


def test_fetch_metadata_parses_steam_payload():
    payload = {
        "response": {
            "result": 1,
            "publishedfiledetails": [
                {
                    "publishedfileid": "12345",
                    "result": 1,
                    "title": "My Awesome Map",
                    "description": "A great map.",
                    "preview_url": "https://steamuser-akamai/foo.jpg",
                    "file_url": "https://steamuser-akamai/foo.bsp",
                    "creator": "76561198000000000",
                    "tags": [
                        {"tag": "Hostage"},
                        {"tag": "Custom"},
                    ],
                    "time_created": 1700000000,
                    "time_updated": 1700100000,
                }
            ],
        }
    }
    opener = _FakeOpener(_fake_steam_response(payload))
    meta = workshop_meta.fetch_metadata("12345", _opener=opener)
    assert meta.workshop_id == "12345"
    assert meta.title == "My Awesome Map"
    assert meta.preview_url == "https://steamuser-akamai/foo.jpg"
    assert meta.tags == ["Hostage", "Custom"]
    assert meta.time_created == 1700000000
    # the post body must contain the workshop id.
    assert opener.last_request.data is not None
    body = opener.last_request.data.decode("utf-8")
    assert "publishedfileids%5B0%5D=12345" in body


def test_fetch_metadata_raises_on_empty_details():
    payload = {"response": {"result": 1, "publishedfiledetails": []}}
    opener = _FakeOpener(_fake_steam_response(payload))
    with pytest.raises(workshop_meta.WorkshopMetadataError):
        workshop_meta.fetch_metadata("12345", _opener=opener)


def test_fetch_metadata_raises_on_non_success_result():
    payload = {
        "response": {
            "result": 1,
            "publishedfiledetails": [
                {"publishedfileid": "12345", "result": 9},  # 9 == file not found
            ],
        }
    }
    opener = _FakeOpener(_fake_steam_response(payload))
    with pytest.raises(workshop_meta.WorkshopMetadataError) as exc_info:
        workshop_meta.fetch_metadata("12345", _opener=opener)
    assert "result code 9" in str(exc_info.value)


def test_fetch_metadata_raises_on_non_json_body():
    opener = _FakeOpener(b"<html>oops</html>")
    with pytest.raises(workshop_meta.WorkshopMetadataError) as exc_info:
        workshop_meta.fetch_metadata("12345", _opener=opener)
    assert "non-json" in str(exc_info.value).lower()


def test_fetch_metadata_raises_on_network_oserror():
    opener = _FakeOpener(b"", raise_oserror=True)
    with pytest.raises(workshop_meta.WorkshopMetadataError):
        workshop_meta.fetch_metadata("12345", _opener=opener)


# --- export_to -------------------------------------------------------------


def _meta(**overrides) -> workshop_meta.WorkshopMetadata:
    base = {
        "workshop_id": "12345",
        "title": "My Map",
        "description": "Desc.",
        "preview_url": "https://steamuser-akamai/foo.jpg?token=abc",
        "tags": ["Hostage"],
    }
    base.update(overrides)
    return workshop_meta.WorkshopMetadata(**base)


def test_export_to_writes_metadata_json(tmp_path: Path) -> None:
    meta = _meta()

    # short-circuit the http download by patching `fetch` in the module.
    def fake_fetch(url, dest, **_kw):
        Path(dest).write_bytes(b"\xff\xd8\xff fake jpg")
        return Path(dest)

    with patch.object(workshop_meta, "fetch", fake_fetch):
        target = workshop_meta.export_to(meta, tmp_path)

    assert target == tmp_path / "12345"
    md = json.loads((target / "metadata.json").read_text())
    assert md["title"] == "My Map"
    assert md["tags"] == ["Hostage"]
    assert (target / "preview.jpg").read_bytes().startswith(b"\xff\xd8\xff")


def test_export_to_skips_preview_when_disabled(tmp_path: Path) -> None:
    meta = _meta()
    target = workshop_meta.export_to(meta, tmp_path, download_preview=False)
    assert (target / "metadata.json").is_file()
    assert not (target / "preview.jpg").exists()


def test_export_to_handles_missing_preview_url(tmp_path: Path) -> None:
    meta = _meta(preview_url=None)
    target = workshop_meta.export_to(meta, tmp_path)
    assert (target / "metadata.json").is_file()
    # no preview was attempted
    assert not (target / "preview.jpg").exists()


def test_export_to_handles_unexpected_extension(tmp_path: Path) -> None:
    meta = _meta(preview_url="https://steamuser-akamai/foo.bin?token=x")

    def fake_fetch(url, dest, **_kw):
        Path(dest).write_bytes(b"data")
        return Path(dest)

    with patch.object(workshop_meta, "fetch", fake_fetch):
        target = workshop_meta.export_to(meta, tmp_path)
    # falls back to .jpg for unfamiliar extensions
    assert (target / "preview.jpg").exists()


def test_export_to_propagates_download_error(tmp_path: Path) -> None:
    meta = _meta()

    def fake_fetch(url, dest, **_kw):
        from csgo2cs2.utils.downloader import DownloadError

        raise DownloadError("boom")

    with patch.object(workshop_meta, "fetch", fake_fetch):
        with pytest.raises(workshop_meta.WorkshopMetadataError):
            workshop_meta.export_to(meta, tmp_path)
    # metadata.json was still written even though preview failed
    assert (tmp_path / "12345" / "metadata.json").is_file()


# --- helpers ---------------------------------------------------------------


def test_preview_filename_strips_query():
    out = workshop_meta._preview_filename("https://steamuser-akamai/AAAA/BBBB.JPG?token=xyz")
    assert out == "preview.jpg"


def test_to_json_dict_round_trips():
    m = _meta()
    d = m.to_json_dict()
    assert d["workshop_id"] == "12345"
    assert "raw" not in d  # raw payload is intentionally omitted
