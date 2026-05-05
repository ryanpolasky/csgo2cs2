# post-fix structural safety check.
#
# fixers do anchored text replacements. that's safe in the typical case
# but a regex with too-greedy boundaries or a mis-encoded backslash
# could produce a vmf whose `{}` braces no longer balance, which means
# valve's import script will reject it without a clear error. before we
# write the patched text to disk, we re-tokenize it and confirm the
# structure looks plausible.
#
# we deliberately keep this *cheap*: a single linear pass over the
# string that ignores text inside `"..."` strings and `//`-style
# comments. it catches the kind of "i deleted a brace" mistake fixers
# could realistically make, without trying to be a full vmf parser.

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StructureSummary:
    open_braces: int
    close_braces: int
    quoted_strings: int
    balanced: bool


def summarize_structure(text: str) -> StructureSummary:
    open_count = 0
    close_count = 0
    quoted = 0

    in_string = False
    in_line_comment = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_string:
            if ch == "\\" and i + 1 < n:
                # skip escaped char
                i += 2
                continue
            if ch == '"':
                in_string = False
                quoted += 1
            i += 1
            continue
        # not in string, not in comment
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "{":
            open_count += 1
        elif ch == "}":
            close_count += 1
        i += 1

    return StructureSummary(
        open_braces=open_count,
        close_braces=close_count,
        quoted_strings=quoted,
        balanced=(open_count == close_count) and not in_string,
    )


@dataclass
class RoundTripResult:
    ok: bool
    reason: str
    before: StructureSummary
    after: StructureSummary


# verify the patched text is *no less structurally sound* than the
# input. callers that produce text with unbalanced quotes or braces in
# the input should still pass (we can't make a broken vmf worse), but a
# previously-balanced vmf that becomes unbalanced after --fix is a
# strict failure: that means a fixer produced a corrupted output.
def verify_roundtrip(before_text: str, after_text: str) -> RoundTripResult:
    before = summarize_structure(before_text)
    after = summarize_structure(after_text)

    if before.balanced and not after.balanced:
        return RoundTripResult(
            ok=False,
            reason=(
                f"brace balance broke during --fix: input had "
                f"{before.open_braces}/{before.close_braces}, output has "
                f"{after.open_braces}/{after.close_braces}"
            ),
            before=before,
            after=after,
        )
    # if input had unbalanced strings, output may legitimately have a
    # different odd-count; we only flag a regression that we caused.
    if before.balanced and after.quoted_strings % 2 != 0:
        return RoundTripResult(
            ok=False,
            reason="output has odd number of quote-delimited strings (likely truncated)",
            before=before,
            after=after,
        )
    return RoundTripResult(ok=True, reason="ok", before=before, after=after)
