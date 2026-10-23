"""`check_audit_catalog.py --merge-base-with REF` when no merge base can be computed.

Pre-commit runs the rule-id history check against `git merge-base HEAD origin/main`,
offline. A missing `origin/main` already skips with a NOTE. A merge base git cannot
compute — histories with no common ancestor, an unborn HEAD on an orphan branch, a
shallow clone whose fork point is past its boundary — must skip the same way, never
block the commit: the hook cannot be bypassed in this repo.
"""
from __future__ import annotations

import subprocess
import sys

from test_check_audit_catalog import SCRIPT, _commit, _edit_rules, _git, _git_repo

_ID = ["-c", "user.email=t@example.com", "-c", "user.name=t"]


def _run_merge_base(root, ref="origin/main") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root),
                           "--merge-base-with", ref], capture_output=True, text=True)


def _drop_p18(root):
    _edit_rules(root, "perf.yaml", lambda rules: [r for r in rules if r["id"] != "P18"])


def _assert_skipped(res):
    assert res.returncode == 0, res.stdout + res.stderr
    assert "NOTE  audit catalog: rule-id history not checked — no merge base of HEAD " \
           "and origin/main" in res.stdout, res.stdout
    assert "FAIL" not in res.stdout


def test_unrelated_histories_skip_with_a_notice(tmp_path):
    root = _git_repo(tmp_path)
    # origin/main: a root commit with no ancestor in common with HEAD
    tree = _git(root, "write-tree").strip()
    orphan = _git(root, *_ID, "commit-tree", tree, "-m", "unrelated").strip()
    _git(root, "update-ref", "refs/remotes/origin/main", orphan)
    _drop_p18(root)   # would be "removed since" against a real base
    _assert_skipped(_run_merge_base(root))


def test_unborn_head_skips_with_a_notice(tmp_path):
    root = _git_repo(tmp_path)
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/orphan-branch")  # HEAD now unborn
    _drop_p18(root)
    res = _run_merge_base(root)
    _assert_skipped(res)
    assert "HEAD" in res.stdout.split("origin/main", 1)[1], res.stdout  # git's reason


def test_shallow_clone_past_the_fork_point_skips_with_a_notice(tmp_path):
    origin = _git_repo(tmp_path)                       # base commit B0 on the default branch
    base = _git(origin, "rev-parse", "HEAD").strip()
    _git(origin, "branch", "feature", base)
    (origin / "main-only.txt").write_text("M1\n")
    _commit(origin, "M1 on main")
    main_branch = _git(origin, "rev-parse", "--abbrev-ref", "HEAD").strip()
    _git(origin, "update-ref", "refs/heads/feature",
         _git(origin, *_ID, "commit-tree", _git(origin, "rev-parse", f"{base}^{{tree}}").strip(),
              "-p", base, "-m", "F1 on feature").strip())
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", "feature",
                    f"file://{origin}", str(clone)], check=True, capture_output=True)
    _git(clone, "fetch", "-q", "--depth", "1", "origin",
         f"{main_branch}:refs/remotes/origin/main")
    _drop_p18(clone)
    _assert_skipped(_run_merge_base(clone))


def test_a_real_merge_base_still_holds_ids_to_it(tmp_path):
    """The skip is only for a merge base git cannot compute: with one, a removed id
    still fails, as before."""
    root = _git_repo(tmp_path)
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _drop_p18(root)
    res = _run_merge_base(root)
    assert res.returncode == 1 and "P18: removed since" in res.stdout, res.stdout
