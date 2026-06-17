"""Unit tests for suggest_repo_changelog --base (CI server-side enforcement).

The pre-commit gate diffs `git diff --cached`, which is empty in a CI checkout.
--base <ref> diffs <ref>...HEAD instead so the gate enforces on a PR's commits.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import suggest_repo_changelog as src  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.st")
    _git(repo, "config", "user.name", "t")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n---\n\n## 2026-01-01\n- seed\n")
    (repo / "README.md").write_text("seed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _add_new_skill(repo: Path) -> None:
    d = repo / "agents" / "cli" / "ts-object-thing-builder"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: ts-object-thing-builder\n---\n# Thing\n")


def test_base_mode_catches_new_skill_without_changelog(tmp_path):
    repo = _init_repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    _add_new_skill(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add skill, no changelog")

    lines = src.get_staged_files(repo, base=base)
    changes = src.detect_significant_changes(lines, repo, new_ref="HEAD:", old_ref=f"{base}:")
    assert any(t == "new-skill" for t, _ in changes), changes
    assert src.changelog_already_staged(lines) is False


def test_base_mode_passes_when_changelog_included(tmp_path):
    repo = _init_repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    _add_new_skill(repo)
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n---\n\n## 2026-02-02\n- feat: add ts-object-thing-builder\n\n## 2026-01-01\n- seed\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add skill + changelog")

    lines = src.get_staged_files(repo, base=base)
    # CHANGELOG.md is in the PR diff → gate is satisfied.
    assert src.changelog_already_staged(lines) is True


def test_base_mode_no_significant_change_passes(tmp_path):
    repo = _init_repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("edited prose\n")  # non-significant
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "docs tweak")

    lines = src.get_staged_files(repo, base=base)
    changes = src.detect_significant_changes(lines, repo, new_ref="HEAD:", old_ref=f"{base}:")
    assert changes == []
