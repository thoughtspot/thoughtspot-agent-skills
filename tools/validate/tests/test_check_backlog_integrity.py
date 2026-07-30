"""Unit tests for check_backlog_integrity.py.

Rules 2 and 3 shell out to git, so tests build small real git repos under tmp_path
rather than mocking subprocess — same approach as test_check_repo_hygiene.py.

NOTE: conflict-marker strings are built by repetition ("<" * 7) and never written as
literals. A literal in this file would be picked up by Rule 3 scanning the repo's
own tracked files.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
