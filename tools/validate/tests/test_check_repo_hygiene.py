"""Unit tests for check_repo_hygiene.py — tracked-but-ignored files (audit finding
1.2) and unexpected top-level tracked files (audit finding 1.1).

Both pure functions take a repo_root and shell out to `git`, so tests build small
real git repos under tmp_path rather than mocking subprocess — cheap at this scale
and exercises the actual `git ls-files` flags the validator relies on.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import check_repo_hygiene as crh

VALIDATE = Path(__file__).resolve().parents[1]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(root: Path) -> None:
    _git(["init", "-q"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE / "check_repo_hygiene.py"), "--root", str(root)],
        capture_output=True, text=True,
    )


# --- tracked_but_ignored() ----------------------------------------------------------

def test_tracked_but_ignored_empty_on_clean_repo(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)

    assert crh.tracked_but_ignored(tmp_path) == []


def test_tracked_but_ignored_flags_a_gitignored_tracked_file(tmp_path):
    # Mirrors the real finding: docs/superpowers/plans/ is gitignored, but a plan
    # file was force-added and committed anyway.
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("docs/superpowers/plans/\n")
    plans_dir = tmp_path / "docs" / "superpowers" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "some-plan.md").write_text("plan\n")
    _git(["add", "-A"], tmp_path)  # .gitignore itself
    _git(["add", "-f", "docs/superpowers/plans/some-plan.md"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)

    hits = crh.tracked_but_ignored(tmp_path)
    assert hits == ["docs/superpowers/plans/some-plan.md"]


def test_tracked_but_ignored_does_not_flag_untracked_ignored_file(tmp_path):
    # The file matches .gitignore but was never force-added — this is the NORMAL,
    # correct state, not a violation.
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("scratch/\n")
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    (scratch_dir / "note.md").write_text("note\n")
    (tmp_path / "README.md").write_text("hello\n")
    _git(["add", "README.md", ".gitignore"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)

    assert crh.tracked_but_ignored(tmp_path) == []


# --- unexpected_top_level_files() ----------------------------------------------------

def test_unexpected_top_level_files_empty_when_only_allowed(tmp_path):
    _init_repo(tmp_path)
    for name in ("README.md", "CLAUDE.md", "CHANGELOG.md", "LICENSE", ".gitignore", ".mcp.json"):
        (tmp_path / name).write_text("x\n")
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "inner.py").write_text("x = 1\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)

    assert crh.unexpected_top_level_files(tmp_path) == []


def test_unexpected_top_level_files_flags_stray_root_file(tmp_path):
    # Mirrors the real finding: err.txt, an accidentally-committed stderr capture.
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    (tmp_path / "err.txt").write_text("urllib3 stderr noise\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)

    assert crh.unexpected_top_level_files(tmp_path) == ["err.txt"]


def test_unexpected_top_level_files_ignores_directory_contents(tmp_path):
    # A file nested under a top-level directory has a "/" in its ls-files path and
    # must never be treated as a stray top-level file, regardless of its name.
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "err.txt").write_text("this is fine, it's nested\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)

    assert crh.unexpected_top_level_files(tmp_path) == []


# --- main() end-to-end ---------------------------------------------------------------

def test_main_passes_on_clean_repo(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)

    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr


def test_main_fails_on_stray_top_level_file(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    (tmp_path / "err.txt").write_text("oops\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)

    res = _run(tmp_path)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "err.txt" in res.stdout


def test_main_fails_on_tracked_but_ignored_file(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("docs/superpowers/plans/\n")
    plans_dir = tmp_path / "docs" / "superpowers" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "some-plan.md").write_text("plan\n")
    (tmp_path / "README.md").write_text("hello\n")
    _git(["add", "-A"], tmp_path)
    _git(["add", "-f", "docs/superpowers/plans/some-plan.md"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)

    res = _run(tmp_path)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "docs/superpowers/plans/some-plan.md" in res.stdout


def test_main_reports_both_finding_classes_together(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("docs/superpowers/plans/\n")
    plans_dir = tmp_path / "docs" / "superpowers" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "some-plan.md").write_text("plan\n")
    (tmp_path / "README.md").write_text("hello\n")
    (tmp_path / "err.txt").write_text("oops\n")
    _git(["add", "-A"], tmp_path)
    _git(["add", "-f", "docs/superpowers/plans/some-plan.md"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)

    res = _run(tmp_path)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "err.txt" in res.stdout
    assert "docs/superpowers/plans/some-plan.md" in res.stdout
    assert "finding 1.1" in res.stdout
    assert "finding 1.2" in res.stdout
