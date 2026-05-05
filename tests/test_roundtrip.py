# tests for the round-trip safety check.

from __future__ import annotations

from csgo2cs2.analyzers.roundtrip import summarize_structure, verify_roundtrip


def test_balanced_minimal_vmf() -> None:
    text = 'world\n{\n\t"classname" "worldspawn"\n}\n'
    s = summarize_structure(text)
    assert s.balanced is True
    assert s.open_braces == 1
    assert s.close_braces == 1


def test_strings_with_braces_dont_count() -> None:
    text = '"key" "value with { in it }"\n'
    s = summarize_structure(text)
    assert s.open_braces == 0
    assert s.close_braces == 0


def test_line_comments_ignored() -> None:
    text = "world\n{\n\t// this is a } closing comment\n}\n"
    s = summarize_structure(text)
    assert s.open_braces == 1
    assert s.close_braces == 1


def test_unbalanced_input_marked_unbalanced() -> None:
    text = "world\n{\n\t{\n}\n"
    s = summarize_structure(text)
    assert s.balanced is False


def test_roundtrip_passes_when_balance_preserved() -> None:
    before = 'world\n{\n\t"classname" "worldspawn"\n}\n'
    after = 'world\n{\n\t"classname" "worldspawn"\n\t"skyname" "sky_de_dust2"\n}\n'
    rt = verify_roundtrip(before, after)
    assert rt.ok is True


def test_roundtrip_fails_when_balance_broken() -> None:
    before = 'world\n{\n\t"classname" "worldspawn"\n}\n'
    after = 'world\n{\n\t"classname" "worldspawn"\n'  # closing brace deleted
    rt = verify_roundtrip(before, after)
    assert rt.ok is False
    assert "brace balance" in rt.reason


def test_roundtrip_fails_on_unterminated_quote_after_fix() -> None:
    before = 'world\n{\n\t"classname" "worldspawn"\n}\n'
    after = 'world\n{\n\t"classname" "worldspawn\n}\n'  # missing closing quote
    rt = verify_roundtrip(before, after)
    assert rt.ok is False


def test_roundtrip_passes_when_input_already_unbalanced() -> None:
    # we don't make a broken vmf worse; we just guard against making a
    # good vmf bad. so an already-unbalanced input that stays unbalanced
    # is not flagged.
    before = "world\n{\n"
    after = "world\n{\n"
    rt = verify_roundtrip(before, after)
    assert rt.ok is True


def test_escaped_quotes_inside_strings_handled() -> None:
    text = '"key" "an \\"escaped\\" string"\n{\n}\n'
    s = summarize_structure(text)
    assert s.open_braces == 1
    assert s.close_braces == 1
