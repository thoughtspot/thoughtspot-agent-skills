"""check_skill_versions --staged must require a version bump when a SKILL.md body
changes (audit F2). Previously the gate only checked that *a* changelog row existed —
never that it was bumped relative to HEAD, so a body edit with a stale version passed."""
import subprocess
from pathlib import Path

CHECKER = Path(__file__).resolve().parents[1] / "check_skill_versions.py"

SKILL_TEMPLATE = """\
---
name: ts-demo
description: demo skill
---

# Demo skill

{body}

## Changelog

| Version | Date | Summary |
|---|---|---|
{rows}
"""


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def _write_skill(repo, body, rows):
    skill = repo / "agents" / "cli" / "ts-demo" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(SKILL_TEMPLATE.format(body=body, rows=rows))
    return skill


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    skill = _write_skill(repo, "Original body line.", "| 1.0.0 | 2026-01-01 | initial |")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo, skill


def _run_checker(repo):
    return subprocess.run(
        ["python3", str(CHECKER), "--root", str(repo), "--staged"],
        cwd=repo, capture_output=True, text=True,
    )


def test_body_edit_without_new_row_fails(tmp_path):
    repo, skill = _make_repo(tmp_path)
    _write_skill(repo, "Edited body line — new behavior.", "| 1.0.0 | 2026-01-01 | initial |")
    _git(repo, "add", "-A")
    res = _run_checker(repo)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "body changed but top changelog row still" in res.stdout, res.stdout


def test_body_edit_with_new_top_row_passes(tmp_path):
    repo, skill = _make_repo(tmp_path)
    _write_skill(
        repo, "Edited body line — new behavior.",
        "| 1.0.1 | 2026-02-02 | fix |\n| 1.0.0 | 2026-01-01 | initial |",
    )
    _git(repo, "add", "-A")
    res = _run_checker(repo)
    assert res.returncode == 0, res.stdout + res.stderr


def test_changelog_only_edit_passes(tmp_path):
    repo, skill = _make_repo(tmp_path)
    # Body unchanged; only a new changelog row added.
    _write_skill(
        repo, "Original body line.",
        "| 1.0.1 | 2026-02-02 | docs |\n| 1.0.0 | 2026-01-01 | initial |",
    )
    _git(repo, "add", "-A")
    res = _run_checker(repo)
    assert res.returncode == 0, res.stdout + res.stderr


def test_full_path_in_output(tmp_path):
    repo, skill = _make_repo(tmp_path)
    _write_skill(repo, "Edited body.", "| 1.0.0 | 2026-01-01 | initial |")
    _git(repo, "add", "-A")
    res = _run_checker(repo)
    assert "agents/cli/ts-demo/SKILL.md" in res.stdout, res.stdout


# ── suggest_repo_changelog.py --check : per-commit, not per-day (audit F2) ────

CHANGELOG_CHECKER = Path(__file__).resolve().parents[1] / "suggest_repo_changelog.py"


def _run_changelog_check(repo):
    return subprocess.run(
        ["python3", str(CHANGELOG_CHECKER), "--root", str(repo), "--check"],
        cwd=repo, capture_output=True, text=True,
    )


def _make_repo_with_changelog(tmp_path, today_section):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n---\n\n" + today_section
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def test_significant_change_without_staged_changelog_fails_even_if_today_section_exists(tmp_path):
    from datetime import date
    today = str(date.today())
    # CHANGELOG already has a today section from a PRIOR commit.
    repo = _make_repo_with_changelog(tmp_path, f"## {today}\n- earlier change\n")
    # Now stage a NEW skill (significant) without touching CHANGELOG.md.
    skill = repo / "agents" / "cli" / "ts-new" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("# new\n\n## Changelog\n\n| 1.0.0 | 2026-01-01 | initial |\n")
    _git(repo, "add", "agents")
    res = _run_changelog_check(repo)
    assert res.returncode != 0, res.stdout + res.stderr


def test_significant_change_with_staged_changelog_passes(tmp_path):
    from datetime import date
    today = str(date.today())
    repo = _make_repo_with_changelog(tmp_path, f"## {today}\n- earlier change\n")
    skill = repo / "agents" / "cli" / "ts-new" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("# new\n\n## Changelog\n\n| 1.0.0 | 2026-01-01 | initial |\n")
    # Also stage a CHANGELOG.md edit this commit.
    (repo / "CHANGELOG.md").write_text(
        f"# Changelog\n\n---\n\n## {today}\n- feat: add ts-new skill\n- earlier change\n"
    )
    _git(repo, "add", "-A")
    res = _run_changelog_check(repo)
    assert res.returncode == 0, res.stdout + res.stderr
