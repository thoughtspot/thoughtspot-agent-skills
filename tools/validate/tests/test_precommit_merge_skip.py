"""The pre-commit hook skips the unit suites only on a merge OF MAIN whose staged .py
files are all main's (2026-11-26). Drives the hook's real `py_needing_tests`, extracted
between its markers, in scratch repos."""
import re
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[3] / "scripts" / "pre-commit.sh"


def _fn() -> str:
    text = HOOK.read_text(encoding="utf-8")
    m = re.search(r"# BEGIN py-needing-tests\n(.*?)# END py-needing-tests", text, re.S)
    assert m, "markers missing from pre-commit.sh"
    return m.group(1)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   text=True)


def _needing(repo) -> str:
    script = _fn() + '\npy_needing_tests "$(git diff --cached --name-only)"\n'
    r = subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("a\n")
    (repo / "b.py").write_text("b\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "checkout", "-qb", "feat")
    (repo / "b.py").write_text("b\nfeat\n")
    _git(repo, "commit", "-qam", "feat")
    return repo


def _advance(repo, branch, path, text):
    _git(repo, "checkout", "-q", branch)
    (repo / path).write_text(text)
    _git(repo, "commit", "-qam", branch)
    _git(repo, "checkout", "-q", "feat")


def test_a_clean_merge_of_main_needs_no_tests(tmp_path):
    repo = _repo(tmp_path)
    _advance(repo, "main", "a.py", "a\nmain\n")
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")
    _git(repo, "merge", "-q", "--no-commit", "main")
    assert _needing(repo) == ""


def test_a_conflict_resolved_in_a_py_file_is_tested(tmp_path):
    repo = _repo(tmp_path)
    _advance(repo, "main", "b.py", "b\nmain\n")
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")
    subprocess.run(["git", "-C", str(repo), "merge", "-q", "--no-commit", "main"],
                   capture_output=True)
    (repo / "b.py").write_text("b\nresolved\n")
    _git(repo, "add", "b.py")
    assert _needing(repo) == "b.py"


def test_a_merge_of_another_branch_is_tested(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "branch", "side", "main")
    _advance(repo, "side", "a.py", "a\nside\n")
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")
    _git(repo, "merge", "-q", "--no-commit", "side")
    assert _needing(repo) == "a.py"


def test_no_main_ref_means_tested(tmp_path):
    repo = _repo(tmp_path)
    _advance(repo, "main", "a.py", "a\nmain\n")
    _git(repo, "merge", "-q", "--no-commit", "main")
    assert _needing(repo) == "a.py"


def test_a_normal_commit_is_tested(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.py").write_text("a\nedit\n")
    _git(repo, "add", "a.py")
    assert _needing(repo) == "a.py"


def test_the_skip_is_counted_in_the_summary():
    text = HOOK.read_text(encoding="utf-8")
    block = text[text.index('PY_STAGED="$(py_needing_tests'):]
    block = block[:block.index("\nfi\n")]
    assert "SKIPPED=$((SKIPPED + 1))" in block
    assert "SKIPPED_LABELS=" in block
