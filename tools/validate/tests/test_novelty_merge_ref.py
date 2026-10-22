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


def test_read_head_reads_the_pr_tip_on_the_merge_ref_and_the_tree_otherwise(repo):
    """Every novelty validator reads the branch's ids through read_head (check_backlog_integrity,
    check_open_items, check_coverage_matrix, check_lint_invariant_list)."""
    from _novelty import read_head
    d, fork, pr_head, main_tip = repo
    git(d, "checkout", "-q", "feature")
    (d / "g").write_text("uncommitted\n")
    assert read_head(d, "main", "g") == "uncommitted\n"            # a plain branch: the working tree
    git(d, "checkout", "-q", "--", "g")
    make_merge_ref(d, main_tip)
    assert read_head(d, "main", "f") == "1\n"                       # the merge ref: the PR's tip, not main's "2"
    assert read_head(d, "main", "g") == "x\n"
    assert read_head(d, "main", "missing") == ""


def test_a_merge_ref_built_before_the_base_moved_is_still_the_merge_ref(repo):
    """CI fetches the base again just before the novelty step, so the base may be ahead of the
    merge ref's first parent; the PR's tip is still HEAD^2."""
    d, fork, pr_head, main_tip = repo
    make_merge_ref(d, main_tip)
    git(d, "checkout", "-q", "main")
    (d / "f").write_text("3\n")
    git(d, "commit", "-qam", "c3: main moves on")
    git(d, "checkout", "-q", "mergeref")
    assert effective_head(d, "main") == "HEAD^2"


def test_a_branch_sitting_on_a_merge_commit_of_the_base_keeps_head(repo):
    """A branch created at (or fast-forwarded to) a merge commit already on main is not the merge
    ref: its second parent is in main, so the working tree stays the branch's copy."""
    d, fork, pr_head, main_tip = repo
    git(d, "checkout", "-q", "main")
    git(d, "merge", "-q", "--no-ff", "--no-edit", "feature")      # main now ends in a merge commit
    git(d, "checkout", "-q", "-b", "sitting", "main")
    assert effective_head(d, "main") == "HEAD"
