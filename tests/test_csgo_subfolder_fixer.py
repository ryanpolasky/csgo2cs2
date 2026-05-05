# tests for the PR5 asset_path_csgo_subfolder fixer.
#
# the fixer needs to:
# - rewrite every quoted-asset path under a `csgo/` segment to
#   `csgo_legacy/`, in a single pass, regardless of how many refs the
#   .vmf has;
# - leave unrelated identifiers alone (e.g. `csgo_warmup_xyz`, comments
#   that mention csgo, etc.);
# - co-operate with the pipeline rename of the staged content tree so
#   the rewritten paths still resolve against disk after `--fix`;
# - be idempotent: running --fix twice gives the same output as once.

from __future__ import annotations

from pathlib import Path

from csgo2cs2.analyzers.vmf import Finding, analyze_vmf
from csgo2cs2.fixers import apply_all  # noqa: F401  (registers fixers)
from csgo2cs2.fixers.asset_paths import fix_asset_path_csgo_subfolder
from csgo2cs2.pipeline import _rename_csgo_subdirs

_VMF_HEADER = (
    "world\n{\n"
    '\t"classname" "worldspawn"\n'
    '\t"skyname" "sky_cs_office"\n'
    "}\n"
    'entity { "classname" "info_player_terrorist" }\n'
    'entity { "classname" "info_player_counterterrorist" }\n'
)


def _csgo_extra(materials: list[str]) -> str:
    parts = ['entity\n{\n\t"classname" "func_brush"\n']
    for i, m in enumerate(materials):
        parts.append(f'\t"material{i}" "{m}"\n')
    parts.append("}\n")
    return "".join(parts)


def test_finding_is_now_fixable():
    text = _VMF_HEADER + _csgo_extra(["materials/csgo/foo.vmt"])
    a = analyze_vmf(text)
    sub = [f for f in a.findings if f.issue_id == "asset_path_csgo_subfolder"]
    assert len(sub) == 1
    assert sub[0].fixable is True


def test_fixer_rewrites_single_path():
    text = _VMF_HEADER + _csgo_extra(["materials/csgo/foo.vmt"])
    a = analyze_vmf(text)
    sub = next(f for f in a.findings if f.issue_id == "asset_path_csgo_subfolder")
    new_text, applied, detail = fix_asset_path_csgo_subfolder(text, sub)
    assert applied
    assert "materials/csgo_legacy/foo.vmt" in new_text
    assert "materials/csgo/foo.vmt" not in new_text
    assert "1 `csgo/` path segment" in detail


def test_fixer_rewrites_all_paths_in_one_pass():
    text = _VMF_HEADER + _csgo_extra(
        [
            "materials/csgo/foo.vmt",
            "models/csgo/de_dust2/wall.mdl",
            "sound/csgo/ambient.wav",
        ]
    )
    a = analyze_vmf(text)
    sub = next(f for f in a.findings if f.issue_id == "asset_path_csgo_subfolder")
    new_text, applied, detail = fix_asset_path_csgo_subfolder(text, sub)
    assert applied
    assert "materials/csgo_legacy/foo.vmt" in new_text
    assert "models/csgo_legacy/de_dust2/wall.mdl" in new_text
    assert "sound/csgo_legacy/ambient.wav" in new_text
    assert "/csgo/" not in new_text
    # detail mentions the count
    assert "3" in detail


def test_fixer_does_not_mangle_unrelated_csgo_identifiers():
    # `csgo_warmup_xyz` and `cs_go_props` should NOT be rewritten because
    # they aren't `csgo/` directory segments, just substrings.
    text = _VMF_HEADER + _csgo_extra(
        [
            "models/cs_go_props/wall.mdl",  # underscore, not slash
            "scripts/csgo_warmup_xyz.cfg",  # csgo_ prefix, not csgo/ segment
        ]
    )
    a = analyze_vmf(text)
    # the analyzer correctly does NOT flag this.
    assert not any(f.issue_id == "asset_path_csgo_subfolder" for f in a.findings)
    # but if a synthetic finding fires anyway, the fixer must be a safe no-op.
    fake = Finding(
        issue_id="asset_path_csgo_subfolder",
        severity="warn",
        message="forced",
        fixable=True,
        context={"path": "models/cs_go_props/wall.mdl"},
    )
    new_text, applied, _ = fix_asset_path_csgo_subfolder(text, fake)
    assert applied is False
    assert new_text == text


def test_fixer_is_idempotent():
    text = _VMF_HEADER + _csgo_extra(["materials/csgo/foo.vmt"])
    a = analyze_vmf(text)
    sub = next(f for f in a.findings if f.issue_id == "asset_path_csgo_subfolder")
    once, _, _ = fix_asset_path_csgo_subfolder(text, sub)
    twice, applied2, _ = fix_asset_path_csgo_subfolder(once, sub)
    # second pass should be a no-op (no `csgo/` segments left).
    assert applied2 is False
    assert once == twice


def test_apply_all_handles_csgo_subfolder():
    text = _VMF_HEADER + _csgo_extra(["materials/csgo/foo.vmt", "models/csgo/bar.mdl"])
    a = analyze_vmf(text)
    new_text, results = apply_all(text, a.findings)
    applied_ids = {r.issue_id for r in results if r.applied}
    assert "asset_path_csgo_subfolder" in applied_ids
    assert "/csgo/" not in new_text


# --- pipeline staged-tree rename -------------------------------------------


def test_pipeline_rename_simple(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    (staged / "materials" / "csgo" / "deep").mkdir(parents=True)
    (staged / "materials" / "csgo" / "foo.vmt").write_text("# vmt", encoding="utf-8")
    (staged / "materials" / "csgo" / "deep" / "bar.vmt").write_text("# vmt", encoding="utf-8")
    (staged / "models").mkdir()  # bucket without csgo/ -> skipped

    touched = _rename_csgo_subdirs(staged)
    assert touched == 1
    assert (staged / "materials" / "csgo_legacy" / "foo.vmt").is_file()
    assert (staged / "materials" / "csgo_legacy" / "deep" / "bar.vmt").is_file()
    assert not (staged / "materials" / "csgo").exists()


def test_pipeline_rename_multiple_buckets(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    for bucket in ("materials", "models", "sound"):
        (staged / bucket / "csgo").mkdir(parents=True)
        (staged / bucket / "csgo" / "x.bin").write_bytes(b"data")
    touched = _rename_csgo_subdirs(staged)
    assert touched == 3
    for bucket in ("materials", "models", "sound"):
        assert (staged / bucket / "csgo_legacy" / "x.bin").is_file()
        assert not (staged / bucket / "csgo").exists()


def test_pipeline_rename_merges_when_target_exists(tmp_path: Path) -> None:
    # users may re-run port; csgo_legacy/ already exists with one file,
    # csgo/ has another. expect a clean merge.
    staged = tmp_path / "staged"
    (staged / "materials" / "csgo_legacy").mkdir(parents=True)
    (staged / "materials" / "csgo_legacy" / "old.vmt").write_text("old", encoding="utf-8")
    (staged / "materials" / "csgo").mkdir(parents=True)
    (staged / "materials" / "csgo" / "new.vmt").write_text("new", encoding="utf-8")

    touched = _rename_csgo_subdirs(staged)
    assert touched == 1
    assert (staged / "materials" / "csgo_legacy" / "old.vmt").is_file()
    assert (staged / "materials" / "csgo_legacy" / "new.vmt").is_file()
    assert not (staged / "materials" / "csgo").exists()


def test_pipeline_rename_is_a_noop_when_no_csgo_subdirs(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    (staged / "materials" / "de_dust2").mkdir(parents=True)
    touched = _rename_csgo_subdirs(staged)
    assert touched == 0
    assert (staged / "materials" / "de_dust2").is_dir()


def test_pipeline_rename_handles_missing_staged_root(tmp_path: Path) -> None:
    # nothing staged yet -> 0 buckets touched, no crash.
    touched = _rename_csgo_subdirs(tmp_path / "does_not_exist")
    assert touched == 0
