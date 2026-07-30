"""Unit tests for check_backlog_integrity.py.

Rules 2 and 3 shell out to git, so tests build small real git repos under tmp_path
rather than mocking subprocess — same approach as test_check_repo_hygiene.py.

NOTE: conflict-marker strings are built by repetition ("<" * 7) and never written as
literals. A literal in this file would be picked up by Rule 3 scanning the repo's
own tracked files.

NOTE: the same trap applies to Rule 2. This file lives under tools/, which is inside
CITATION_SCOPE, so any literal, contiguous "BL" + dash + digits placeholder written
here for the dangling-citation tests below would itself become a real, unresolved
citation the moment this file is committed — a false positive baked into the
validator's own suite. The three placeholder ids used by those tests are therefore
built by concatenation, never written as a literal contiguous token.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import check_backlog_integrity as cbi

VALIDATE = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(root: Path) -> None:
    _git(["init", "-q"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _commit_all(root: Path) -> None:
    _git(["add", "-A"], root)
    _git(["commit", "-qm", "fixture"], root)


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE / "check_backlog_integrity.py"), "--root", str(root)],
        capture_output=True, text=True,
    )


CLEAN_BACKLOG = """# Backlog

## BL-001 -- First item `Tier 1`

**Status:** OPEN.

## BL-002 -- Second item `Tier 2`

**Status:** OPEN.
"""


def test_duplicate_heading_detected(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", (FIXTURES / "backlog_dup_bl171.md").read_text())
    _commit_all(tmp_path)

    dups = cbi.duplicate_headings(tmp_path)

    assert dups == [("docs/backlog.md:BL-171", 2)]


def test_clean_backlog_has_no_duplicates(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _commit_all(tmp_path)

    assert cbi.duplicate_headings(tmp_path) == []


def test_duplicate_heading_fails_cli_and_names_the_id(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", (FIXTURES / "backlog_dup_bl171.md").read_text())
    _commit_all(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "BL-171" in result.stdout


def test_id_sectioned_in_both_live_and_archive_is_flagged(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _write(tmp_path, "docs/backlog-archive.md", "# Archive\n\n## BL-002 -- Second item\n\nDone.\n")
    _commit_all(tmp_path)

    assert cbi.cross_file_duplicates(tmp_path) == ["BL-002"]


def test_suffixed_ids_stay_distinct(tmp_path):
    """BL-003, BL-003b, BL-003c and BL-003-UMBRELLA are four separate archived items.
    A `BL-\\d+` pattern prefix-matches all four to "BL-003" and manufactures a
    duplicate. This test fails against that regex and is the regression guard for it.
    """
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _write(
        tmp_path,
        "docs/backlog-archive.md",
        "# Archive\n\n"
        "## BL-003 -- Umbrella parent\n\nDone.\n\n"
        "## BL-003b -- Second part\n\nDone.\n\n"
        "## BL-003c -- Third part\n\nDone.\n\n"
        "## BL-003-UMBRELLA -- The umbrella\n\nDone.\n",
    )
    _commit_all(tmp_path)

    assert cbi.section_headings(
        cbi._read(tmp_path, "docs/backlog-archive.md")
    ) == ["BL-003", "BL-003b", "BL-003c", "BL-003-UMBRELLA"]
    assert cbi.duplicate_headings(tmp_path) == []


def test_heading_id_stops_before_trailing_punctuation(tmp_path):
    """A heading written as "## BL-171: Something" must resolve to the id "BL-171",
    not "BL-171:" — otherwise a genuine duplicate written with adjacent punctuation
    would evade Rule 1 entirely (the id would never collide with a plain "BL-171")."""
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", "# Backlog\n\n## BL-171: Something\n\nDone.\n")
    _commit_all(tmp_path)

    assert cbi.section_headings(cbi._read(tmp_path, "docs/backlog.md")) == ["BL-171"]


# Placeholder ids for the dangling-citation tests below. Built by concatenation
# (never as a literal contiguous "BL" + dash + digits token) — see the module
# docstring note on why a literal here would be a self-inflicted false positive.
_UNDEFINED_BL_A = "BL-" + "999"
_UNDEFINED_BL_B = "BL-" + "888"
_UNDEFINED_BL_C = "BL-" + "777"


def test_dangling_citation_detected(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _write(tmp_path, "agents/cli/demo/SKILL.md", f"Fixed under {_UNDEFINED_BL_A}.\n")
    _commit_all(tmp_path)

    dangling = cbi.dangling_citations(tmp_path)

    assert list(dangling) == [_UNDEFINED_BL_A]
    assert dangling[_UNDEFINED_BL_A] == ["agents/cli/demo/SKILL.md:1"]


def test_dangling_citation_two_ids_on_one_line_both_reported(tmp_path):
    """Docstring claim: dangling_citations() greps whole lines rather than using
    `git grep -o`, specifically so one line carrying two ids reports both. Pin it
    here — if the implementation ever collapsed to capturing only the first id per
    line (e.g. `.search()` instead of `.findall()` over the line body), this test
    fails while the single-id test above would still pass."""
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _write(
        tmp_path,
        "tools/demo/two_ids.md",
        f"Superseded {_UNDEFINED_BL_A} and also touches {_UNDEFINED_BL_B} here.\n",
    )
    _commit_all(tmp_path)

    dangling = cbi.dangling_citations(tmp_path)

    assert _UNDEFINED_BL_A in dangling
    assert _UNDEFINED_BL_B in dangling
    assert dangling[_UNDEFINED_BL_A] == ["tools/demo/two_ids.md:1"]
    assert dangling[_UNDEFINED_BL_B] == ["tools/demo/two_ids.md:1"]


def test_resolvable_citation_is_not_flagged(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _write(tmp_path, "tools/ts-cli/ts_cli/demo.py", "# See BL-001 for context.\n")
    _commit_all(tmp_path)

    assert cbi.dangling_citations(tmp_path) == {}


def test_citation_in_docs_is_out_of_scope(tmp_path):
    """docs/ is a point-in-time record — a spec citing a since-renumbered id is
    correct as history and must not fail the gate."""
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _write(
        tmp_path,
        "docs/superpowers/specs/2026-01-01-old-design.md",
        f"Filed as {_UNDEFINED_BL_B}.\n",
    )
    _commit_all(tmp_path)

    assert cbi.dangling_citations(tmp_path) == {}


def test_archive_index_row_counts_as_defined(tmp_path):
    """An archived item keeps its number and stays a legitimate citation target,
    even when it no longer owns a `## BL-NNN` section."""
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG + "\n- BL-003 — Archived thing — Done\n")
    _write(tmp_path, "agents/cli/demo/SKILL.md", "Historical: BL-003.\n")
    _commit_all(tmp_path)

    assert cbi.dangling_citations(tmp_path) == {}


def test_untracked_file_citation_is_ignored(tmp_path):
    """Rule 2 uses `git grep`, so it sees tracked content only — an uncommitted
    scratch file must not fail the gate."""
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _commit_all(tmp_path)
    _write(tmp_path, "agents/scratch.md", f"{_UNDEFINED_BL_C} notes\n")  # deliberately not committed

    assert cbi.dangling_citations(tmp_path) == {}


def test_git_lines_raises_on_non_repo_directory(tmp_path):
    """`git grep` exits 128 ("not a git repository") outside any repo — the exit-1
    "no matches" shortcut must not swallow that. Deliberately skips _init_repo: a
    fail-open here means the gate reports clean because it could not run at all,
    which is worse than reporting nothing."""
    with pytest.raises(cbi.GitUnavailable):
        cbi._git_lines(["grep", "-nI", "-e", "BL-[0-9]+", "--", "agents"], tmp_path)


def test_cli_exits_2_when_git_is_unavailable(tmp_path):
    """The CLI must fail loudly (exit 2), not silently report clean (exit 0), when
    run against a directory git refuses to operate on. This is the regression guard
    for the fail-open bug: against the old _git_lines (non-zero exit -> []), this
    same setup returns exit 0 with "Backlog integrity clean" — a validator reporting
    success because it could not run at all."""
    result = _run(tmp_path)  # tmp_path is not a git repo — no _init_repo call

    assert result.returncode == 2
    assert result.returncode != 0
    assert result.returncode != 1
    combined = result.stdout + result.stderr
    assert "could not run" in combined
    assert "not a git repository" in combined


# Built by repetition, never as literals — a literal here would be found by Rule 3
# when it scans this repo's own tracked files.
_OURS = "<" * 7
_THEIRS = ">" * 7
_SPLIT = "=" * 7


def test_conflict_markers_detected(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _write(
        tmp_path,
        "notes.md",
        f"intro\n{_OURS} HEAD\nmine\n{_SPLIT}\ntheirs\n{_THEIRS} origin/main\noutro\n",
    )
    _commit_all(tmp_path)

    hits = cbi.conflict_markers(tmp_path)

    assert hits == ["notes.md:2", "notes.md:4", "notes.md:6"]


def test_setext_underline_alone_is_not_a_conflict(tmp_path):
    """A bare 7-equals line is a legal Markdown setext h1 underline. It counts only
    when the same file also carries an ours/theirs marker."""
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _write(tmp_path, "readme.md", f"Title\n{_SPLIT}\n\nBody text.\n")
    _commit_all(tmp_path)

    assert cbi.conflict_markers(tmp_path) == []


def test_conflict_marker_fails_cli(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _write(tmp_path, "notes.md", f"{_OURS} HEAD\nmine\n")
    _commit_all(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "notes.md:1" in result.stdout


def test_binary_file_does_not_crash_the_scan(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    (tmp_path / "blob.bin").write_bytes(bytes(range(256)))
    _commit_all(tmp_path)

    assert cbi.conflict_markers(tmp_path) == []


def test_cli_exits_2_when_conflict_markers_rule_hits_git_unavailable(tmp_path, monkeypatch):
    """Regression guard for the widened guard itself. dangling_citations() is called
    first in main() and, against a plain non-repo directory, always raises before
    conflict_markers() is ever reached — so the plain non-repo scenario in
    test_cli_exits_2_when_git_is_unavailable above passes identically whether the
    try/except wraps both rules or only dangling_citations(). It cannot tell the two
    implementations apart.

    This test forces the discriminating case directly: dangling_citations() succeeds
    (real, valid repo) and conflict_markers() is the one that raises GitUnavailable.
    If the guard is scoped tightly around dangling_citations() only, this call escapes
    as an uncaught traceback instead of returning 2.
    """
    _init_repo(tmp_path)
    _write(tmp_path, "docs/backlog.md", CLEAN_BACKLOG)
    _commit_all(tmp_path)

    def _boom(root):
        raise cbi.GitUnavailable("simulated failure for the widened-guard test")

    monkeypatch.setattr(cbi, "conflict_markers", _boom)
    monkeypatch.setattr(sys, "argv", ["check_backlog_integrity.py", "--root", str(tmp_path)])

    assert cbi.main() == 2
