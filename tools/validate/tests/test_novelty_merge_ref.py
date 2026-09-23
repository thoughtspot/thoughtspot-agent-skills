"""`_novelty` on GitHub's merge ref — 2026-09-22 audit finding 17.2.

The novelty rule is `(head_ids - merge_base_ids) & base_ids`. On a `pull_request`
event the checkout is `refs/pull/N/merge`, so HEAD already contains the base and
`merge_base_ids == base_ids`, which makes the expression empty for every input.
The gate could not fire on the event it exists for.
"""
import subprocess

import pytest

import _novelty
from _novelty import effective_head, merge_base_with_head, novel_id_collisions


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """main with two commits; `feature` forked after the first."""
    git(tmp_path, "init", "-q", "-b", "main", ".")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "f").write_text("1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "c1")
    fork = git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    git(tmp_path, "checkout", "-q", "-b", "feature")
    (tmp_path / "g").write_text("x\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "feat")
    pr_head = git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    git(tmp_path, "checkout", "-q", "main")
    (tmp_path / "f").write_text("2\n")
    git(tmp_path, "commit", "-qam", "c2")
    main_tip = git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    return tmp_path, fork, pr_head, main_tip


def make_merge_ref(d, main_tip):
    """GitHub's shape: base tip as FIRST parent, PR head as second."""
    git(d, "checkout", "-q", "-b", "mergeref", main_tip)
    git(d, "merge", "-q", "--no-edit", "feature")


# ── the defect, stated as arithmetic ───────────────────────────────────────

def test_rule_is_empty_whenever_merge_base_equals_base():
    """(h - b) & b is empty for every h. This is why the merge ref defeats it."""
    # Neutral ids: `BL-N` here would read as real backlog citations to
    # check_backlog_integrity, which scans the tree for dangling ones.
    base = {"ID-1", "ID-2", "ID-3"}
    head = {"ID-1", "ID-2", "ID-3", "ID-4", "ID-99"}
    assert novel_id_collisions(head, base, base) == []
    # With the true fork point it fires as intended.
    assert novel_id_collisions(head, {"ID-1", "ID-2"}, base) == ["ID-3"]


# ── the fix ────────────────────────────────────────────────────────────────

def test_merge_ref_resolves_to_the_pr_head(repo):
    d, _fork, pr_head, main_tip = repo
    make_merge_ref(d, main_tip)
    assert effective_head(d, "main") == "HEAD^2"
    assert git(d, "rev-parse", "HEAD^2").stdout.strip() == pr_head


def test_merge_ref_merge_base_is_the_fork_point_not_the_base_tip(repo):
    d, fork, _pr_head, main_tip = repo
    make_merge_ref(d, main_tip)
    got = merge_base_with_head(d, "main")
    assert got == fork
    assert got != main_tip, "the base tip is exactly what made the rule vacuous"


def test_plain_branch_checkout_is_unaffected(repo):
    d, fork, _pr_head, _main_tip = repo
    git(d, "checkout", "-q", "feature")
    assert effective_head(d, "main") == "HEAD"
    assert merge_base_with_head(d, "main") == fork


def test_a_merge_that_is_not_the_base_tip_keeps_head(repo):
    """Only a merge whose FIRST parent is the base tip is the merge ref."""
    d, _fork, _pr_head, _main_tip = repo
    git(d, "checkout", "-q", "feature")
    git(d, "checkout", "-q", "-b", "other")
    (d / "h").write_text("y\n")
    git(d, "add", ".")
    git(d, "commit", "-qm", "other")
    git(d, "checkout", "-q", "feature")
    git(d, "merge", "-q", "--no-edit", "other")   # merge, but first parent != main tip
    assert effective_head(d, "main") == "HEAD"
