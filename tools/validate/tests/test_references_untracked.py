"""check_references must flag links to files that exist locally but are untracked /
gitignored (audit 4.1) — those are dead links for anyone who clones the repo."""
import subprocess
from pathlib import Path

CHECKER = Path(__file__).resolve().parents[1] / "check_references.py"


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def _run_checker(repo):
    return subprocess.run(
        ["python3", str(CHECKER), "--root", str(repo)],
        cwd=repo, capture_output=True, text=True,
    )


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "agents" / "cli" / "ts-x").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    return repo


def test_link_to_untracked_existing_file_fails(tmp_path):
    repo = _make_repo(tmp_path)
    skill = repo / "agents" / "cli" / "ts-x" / "SKILL.md"
    skill.write_text("See [the doc](b.md).\n")
    # b.md exists on disk but is NOT tracked.
    (repo / "agents" / "cli" / "ts-x" / "b.md").write_text("body\n")
    _git(repo, "add", "agents/cli/ts-x/SKILL.md")
    _git(repo, "commit", "-q", "-m", "track skill only")
    res = _run_checker(repo)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "untracked" in res.stdout, res.stdout


def test_link_to_tracked_file_passes(tmp_path):
    repo = _make_repo(tmp_path)
    skill = repo / "agents" / "cli" / "ts-x" / "SKILL.md"
    skill.write_text("See [the doc](b.md).\n")
    (repo / "agents" / "cli" / "ts-x" / "b.md").write_text("body\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "track both")
    res = _run_checker(repo)
    assert res.returncode == 0, res.stdout + res.stderr
