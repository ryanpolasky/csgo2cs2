# tests for the http downloader. uses a local http server so we never hit
# the network in ci.

from __future__ import annotations

import hashlib
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from csgo2cs2.utils.downloader import DownloadError, fetch


@pytest.fixture
def http_server(tmp_path: Path):
    # keep the served dir separate from any download destination so we can
    # assert "dest does not exist after a failed download".
    serve_dir = tmp_path / "serve"
    serve_dir.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def make_handler(*a, **kw):
        return http.server.SimpleHTTPRequestHandler(*a, directory=str(serve_dir), **kw)

    server = socketserver.TCPServer(("127.0.0.1", 0), make_handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, serve_dir, out_dir, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def test_fetch_writes_file(http_server):
    _server, root, out_dir, port = http_server
    payload = b"hello world"
    (root / "x.bin").write_bytes(payload)
    dest = out_dir / "x.bin"
    result = fetch(f"http://127.0.0.1:{port}/x.bin", dest, progress=None)
    assert result == dest
    assert dest.read_bytes() == payload


def test_fetch_verifies_sha256(http_server):
    _server, root, out_dir, port = http_server
    payload = b"verify me"
    (root / "v.bin").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    dest = out_dir / "v.bin"
    fetch(f"http://127.0.0.1:{port}/v.bin", dest, sha256=digest, progress=None)
    assert dest.read_bytes() == payload


def test_fetch_rejects_sha256_mismatch(http_server):
    _server, root, out_dir, port = http_server
    (root / "bad.bin").write_bytes(b"abc")
    dest = out_dir / "bad.bin"
    with pytest.raises(DownloadError, match="sha256 mismatch"):
        fetch(
            f"http://127.0.0.1:{port}/bad.bin",
            dest,
            sha256="0" * 64,
            progress=None,
        )
    assert not (out_dir / "bad.bin.part").exists()
    assert not dest.exists()


def test_fetch_404_raises(http_server):
    _server, _root, out_dir, port = http_server
    with pytest.raises(DownloadError):
        fetch(
            f"http://127.0.0.1:{port}/missing.bin",
            out_dir / "missing.bin",
            progress=None,
        )
