from __future__ import annotations

from csgo2cs2.utils import known_errors


def test_match_steamcmd_login_denied() -> None:
    text = "ERROR! Login Failure: Account Logon Denied"
    hit = known_errors.match_error(text)
    assert hit is not None
    assert hit.id == "steam_login_denied"
    assert "steam guard" in hit.hint.lower()


def test_match_workshop_download_failure() -> None:
    text = "ERROR! Downloading item 12345..."
    hit = known_errors.match_error(text)
    assert hit is not None
    assert hit.id == "steam_workshop_download_failed"


def test_match_disk_full() -> None:
    text = "OSError: [Errno 28] No space left on device"
    hit = known_errors.match_error(text)
    assert hit is not None
    assert hit.id == "steam_disk_full"


def test_match_java_not_found() -> None:
    text = "'java' is not recognized as an internal or external command"
    hit = known_errors.match_error(text)
    assert hit is not None
    assert hit.id == "java_not_found"


def test_match_jvm_crash() -> None:
    text = "# A fatal error has been detected by the Java Runtime Environment:"
    hit = known_errors.match_error(text)
    assert hit is not None
    assert hit.id == "bspsource_jvm_crash"


def test_match_protected_bsp() -> None:
    text = "WARNING: this map appears to be protected by bspprotect"
    hit = known_errors.match_error(text)
    assert hit is not None
    assert hit.id == "bspsource_protected"


def test_match_importer_decode_error() -> None:
    text = "AttributeError: 'str' object has no attribute 'decode'"
    hit = known_errors.match_error(text)
    assert hit is not None
    assert hit.id == "importer_decode_error"


def test_match_vpk_signature() -> None:
    text = "FileNotFoundError: vpk.signatures.old"
    hit = known_errors.match_error(text)
    assert hit is not None
    assert hit.id == "importer_vpk_signature_missing"


def test_match_permission_denied() -> None:
    text = "PermissionError: [Errno 13] Permission denied: '/foo'"
    hit = known_errors.match_error(text)
    assert hit is not None
    assert hit.id == "fs_permission_denied"


def test_match_path_too_long() -> None:
    text = "[Errno 36] File name too long"
    hit = known_errors.match_error(text)
    assert hit is not None
    assert hit.id == "fs_path_too_long"


def test_match_returns_none_for_unknown_text() -> None:
    hit = known_errors.match_error("everything went fine and no errors occurred")
    assert hit is None


def test_match_returns_none_for_empty() -> None:
    assert known_errors.match_error("") is None
    assert known_errors.match_error(None) is None  # type: ignore[arg-type]


def test_match_all_returns_multiple() -> None:
    text = "Permission denied AND No space left on device"
    hits = known_errors.match_all(text)
    ids = {h.id for h in hits}
    assert "fs_permission_denied" in ids
    assert "steam_disk_full" in ids


def test_all_errors_iterable_is_nonempty() -> None:
    errs = list(known_errors.all_errors())
    assert len(errs) > 0
    # every entry has an id and a hint
    for e in errs:
        assert e.id
        assert e.hint


def test_each_id_is_unique() -> None:
    ids = [e.id for e in known_errors.all_errors()]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
