"""Unit tests for check_version_sync's novelty rules — BL-274.

Regression guard for the collision the existing gate cannot see: two branches that
bump to the *same* version change the same two lines to the same value, so git
auto-merges with no conflict and `check_version_sync` still passes, because the
invariant it checked was internal consistency (`__init__.py` == `pyproject.toml`)
and a collision preserves that perfectly.

Demonstrated twice before these rules existed: #511 vs #512 (both 0.139.0, the
filing case) and #484 vs #516 (both 0.141.0, caught by simulating the merge).
`test_the_484_vs_516_collision_is_flagged` reconstructs the second one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_version_sync as cvs  # noqa: E402


# --- pyproject parsing (pre-existing behaviour, pinned) ---------------------

def test_parse_pyproject_version_reads_project_table_only():
    # Regression on the 2026-08-26 audit finding 4.4: a version in another table
    # must never satisfy the lookup.
    content = '[tool.poetry]\nversion = "9.9.9"\n\n[project]\nname = "x"\nversion = "0.141.0"\n'
    assert cvs.parse_pyproject_version(content) == "0.141.0"


def test_parse_pyproject_version_ignores_subtables():
    content = '[project]\nname = "x"\n\n[project.optional-dependencies]\nversion = "8.8.8"\n'
    assert cvs.parse_pyproject_version(content) is None


# --- CHANGELOG release markers ---------------------------------------------

def test_changelog_bump_versions_extracts_release_markers():
    content = (
        "- chore: bump ts-cli to v0.140.0\n"
        "- chore: bump ts-cli to v0.141.0\n"
    )
    assert cvs.changelog_bump_versions(content) == ["0.140.0", "0.141.0"]


def test_changelog_bump_versions_ignores_prose_mentions():
    # `ts-cli v0.9.0` appears in prose 100+ times on main; only the `bump ... to v`
    # form marks a release, so a looser pattern would manufacture duplicates.
    content = (
        "- feat: something that shipped in ts-cli v0.9.0 and later\n"
        "- fix: see ts-cli 0.53.0 for context\n"
        "- chore: bump ts-cli to v0.141.0\n"
    )
    assert cvs.changelog_bump_versions(content) == ["0.141.0"]


def test_duplicate_bump_versions_empty_when_all_distinct():
    content = "- chore: bump ts-cli to v0.140.0\n- chore: bump ts-cli to v0.141.0\n"
    assert cvs.duplicate_bump_versions(content) == []


def test_duplicate_bump_versions_finds_the_post_merge_shape():
    # What the merged tree of two colliding PRs actually looks like: one bump line
    # per PR, under two different dated headings, same version.
    content = (
        "## 2026-09-21\n- chore: bump ts-cli to v0.141.0\n"
        "## 2026-09-10\n- chore: bump ts-cli to v0.141.0\n"
    )
    assert cvs.duplicate_bump_versions(content) == ["0.141.0"]


# --- the novelty rule ------------------------------------------------------

def _base(pyproject_version: str, released: list[str]) -> dict:
    return {
        "base_pyproject": f'[project]\nversion = "{pyproject_version}"\n',
        "base_changelog": "".join(f"- chore: bump ts-cli to v{v}\n" for v in released),
    }


def test_novel_version_passes():
    v = cvs.novelty_violations(
        branch_version="0.142.0", ts_cli_changed=True,
        **_base("0.141.0", ["0.140.0", "0.141.0"]),
    )
    assert v == []


def test_version_equal_to_base_pyproject_is_flagged():
    v = cvs.novelty_violations(
        branch_version="0.141.0", ts_cli_changed=True,
        **_base("0.141.0", ["0.140.0", "0.141.0"]),
    )
    assert len(v) >= 1
    assert any("0.141.0" in m for m in v)


def test_version_already_released_in_base_changelog_is_flagged():
    # The stronger half: main has moved past it, so comparing only against main's
    # *current* version would miss an already-published number.
    v = cvs.novelty_violations(
        branch_version="0.140.0", ts_cli_changed=True,
        **_base("0.141.0", ["0.140.0", "0.141.0"]),
    )
    assert any("0.140.0" in m for m in v)


def test_untouched_ts_cli_is_not_required_to_bump():
    # A docs-only or validator-only branch releases nothing, so reusing main's
    # version is correct rather than a collision. This validator's own PR is that
    # shape, and must not have to invent a version to land.
    v = cvs.novelty_violations(
        branch_version="0.141.0", ts_cli_changed=False,
        **_base("0.141.0", ["0.140.0", "0.141.0"]),
    )
    assert v == []


def test_the_484_vs_516_collision_is_flagged():
    # Reconstruction of the live near-miss. #516 merged as 0.141.0; #484 branched
    # from 0.140.0, also bumped to 0.141.0, changes ts_cli, and every gate was
    # green. Merging it would have left main on 0.141.0 carrying #484's work.
    v = cvs.novelty_violations(
        branch_version="0.141.0", ts_cli_changed=True,
        **_base("0.141.0", ["0.139.0", "0.140.0", "0.141.0"]),
    )
    assert v, "the collision that motivated BL-274 must not pass"


def test_missing_base_is_an_error_not_a_skip():
    # A gate that silently no-ops when it cannot read the base is decorative —
    # exactly the failure class this repo keeps finding. With --base requested and
    # the base unreadable, it must report rather than pass.
    v = cvs.novelty_violations(
        branch_version="0.142.0", ts_cli_changed=True,
        base_pyproject=None, base_changelog=None,
    )
    assert v, "unreadable base must be reported, never silently skipped"
