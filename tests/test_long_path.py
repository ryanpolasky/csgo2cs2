from __future__ import annotations

from csgo2cs2.utils import long_path


def test_is_too_long_short_path() -> None:
    short = "C:\\x.txt"
    # short path: not too long on any platform
    assert not long_path.is_too_long(short, budget=100)


def test_is_too_long_long_path_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(long_path, "is_windows", lambda: True)
    long = "C:\\" + ("x" * 300)
    assert long_path.is_too_long(long, budget=200)


def test_is_too_long_long_path_on_unix(monkeypatch) -> None:
    monkeypatch.setattr(long_path, "is_windows", lambda: False)
    long = "/tmp/" + ("x" * 300)
    # non-windows: NEVER flagged regardless of length
    assert not long_path.is_too_long(long, budget=200)


def test_extended_path_passes_through_on_unix(monkeypatch) -> None:
    monkeypatch.setattr(long_path, "is_windows", lambda: False)
    assert long_path.extended_path("/foo/bar") == "/foo/bar"


def test_extended_path_adds_prefix_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(long_path, "is_windows", lambda: True)
    out = long_path.extended_path("C:\\foo\\bar")
    assert out.startswith("\\\\?\\")
    assert out.endswith("foo\\bar")


def test_extended_path_unc_form(monkeypatch) -> None:
    monkeypatch.setattr(long_path, "is_windows", lambda: True)
    out = long_path.extended_path("\\\\server\\share\\file")
    assert "UNC" in out
    assert out.startswith("\\\\?\\")


def test_extended_path_already_extended(monkeypatch) -> None:
    monkeypatch.setattr(long_path, "is_windows", lambda: True)
    already = "\\\\?\\C:\\already\\extended"
    assert long_path.extended_path(already) == already


def test_shorten_for_display_short_path() -> None:
    out = long_path.shorten_for_display("/foo/bar", max_len=40)
    assert out == "/foo/bar"


def test_shorten_for_display_truncates() -> None:
    p = "/" + "x" * 200
    out = long_path.shorten_for_display(p, max_len=60)
    assert len(out) <= 60
    assert "..." in out
