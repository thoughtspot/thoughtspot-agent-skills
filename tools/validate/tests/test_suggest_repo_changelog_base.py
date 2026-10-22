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


def _ts_cli_repo(tmp_path: Path) -> Path:
    repo = _init_repo(tmp_path)
    pkg = repo / "tools" / "ts-cli" / "ts_cli"
    pkg.mkdir(parents=True)
    (repo / "tools" / "ts-cli" / "pyproject.toml").write_text(
        '[project]\nname = "ts-cli"\nversion = "0.1.0"\n\n'
        '[tool.setuptools.package-data]\n"ts_cli" = ["a.html"]\n')
    (pkg / "__init__.py").write_text('__version__ = "0.1.0"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "ts-cli")
    return repo


def _changes_since(repo: Path, base: str) -> list:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    lines = src.get_staged_files(repo, base=base)
    return src.detect_significant_changes(lines, repo, new_ref="HEAD:", old_ref=f"{base}:")


def test_pyproject_edit_without_version_change_is_not_a_bump(tmp_path):
    # A package-data edit is not a release: it must not demand a CHANGELOG entry.
    repo = _ts_cli_repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    toml = repo / "tools" / "ts-cli" / "pyproject.toml"
    toml.write_text(toml.read_text().replace('["a.html"]', '["a.html", "b/*.yaml"]'))
    assert _changes_since(repo, base) == []


def test_version_change_is_a_bump(tmp_path):
    repo = _ts_cli_repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    toml = repo / "tools" / "ts-cli" / "pyproject.toml"
    toml.write_text(toml.read_text().replace('version = "0.1.0"', 'version = "0.2.0"'))
    init = repo / "tools" / "ts-cli" / "ts_cli" / "__init__.py"
    init.write_text('__version__ = "0.2.0"\n')
    changes = _changes_since(repo, base)
    assert changes == [("ts-cli-bump", "chore: bump ts-cli to v0.2.0")] * 2, changes
