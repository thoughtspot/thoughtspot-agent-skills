"""Unit tests for check_backlog_integrity's Rule 4 — BL-279.

Rule 1 enforces uniqueness *within one tree*, which is what BL-171 asked for. It
cannot see an id that is unique here and already taken on the base, because each
branch passes in isolation and the two additions land in different places in the
file, so a three-way merge has no reason to object.

Demonstrated on #484 vs #516: `main`'s highest id was BL-274, both branches
allocated BL-275 for unrelated defects, and simulating the merge produced two
index rows and two full entries under one id with no conflict.

The three-point comparison is the whole rule. Two points are not enough: an id
present on both the branch and the base is usually just an item the branch
inherited, and only counts as a collision when the branch *introduced* it — i.e.
it is absent at the merge base.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_backlog_integrity as cbi  # noqa: E402


# --- the pure rule ---------------------------------------------------------

def test_id_introduced_here_and_present_on_base_is_a_collision():
    # The #484/#516 shape: merge base has up to BL-274, this branch adds BL-275,
    # and the base has since gained a *different* BL-275.
    out = cbi.novel_id_collisions(
        head_ids={"BL-274", "BL-275"},
        merge_base_ids={"BL-274"},
        base_ids={"BL-274", "BL-275"},
    )
    assert out == ["BL-275"]


def test_inherited_id_is_not_a_collision():
    # Present on branch AND base, but also at the merge base — the branch did not
    # introduce it, it just carries it. Two-point comparison would flag this.
    out = cbi.novel_id_collisions(
        head_ids={"BL-274", "BL-275"},
        merge_base_ids={"BL-274", "BL-275"},
        base_ids={"BL-274", "BL-275"},
    )
    assert out == []


def test_genuinely_new_id_passes():
    out = cbi.novel_id_collisions(
        head_ids={"BL-274", "BL-280"},
        merge_base_ids={"BL-274"},
        base_ids={"BL-274", "BL-275"},
    )
    assert out == []


def test_several_collisions_are_all_reported_sorted():
    out = cbi.novel_id_collisions(
        head_ids={"BL-275", "BL-276", "BL-277"},
        merge_base_ids=set(),
        base_ids={"BL-276", "BL-275"},
    )
    assert out == ["BL-275", "BL-276"]


def test_base_moving_ahead_alone_is_not_a_collision():
    # The base gained items the branch has never seen. That is ordinary drift and
    # must not fail — only ids the branch itself introduces are in scope.
    out = cbi.novel_id_collisions(
        head_ids={"BL-274"},
        merge_base_ids={"BL-274"},
        base_ids={"BL-274", "BL-275", "BL-276"},
    )
    assert out == []


# --- the git wiring --------------------------------------------------------

def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _backlog(repo, ids):
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "backlog.md").write_text(
        "".join(f"## {i} — item {i} `Tier 3`\n\nbody\n\n" for i in ids), encoding="utf-8")
    (repo / "docs" / "backlog-archive.md").write_text("# archive\n", encoding="utf-8")


def test_wiring_flags_the_484_vs_516_shape(tmp_path):
    repo = tmp_path / "r"
    (repo / "docs").mkdir(parents=True)
    _backlog(repo, ["BL-274"])
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "merge base")

    # base branch gains its own BL-275
    _git(repo, "branch", "base-ref")
    _git(repo, "checkout", "-q", "base-ref")
    _backlog(repo, ["BL-274", "BL-275"])
    _git(repo, "commit", "-qam", "base adds BL-275 (one defect)")

    # feature branch independently adds a different BL-275
    _git(repo, "checkout", "-q", "master" if _has(repo, "master") else "main")
    _backlog(repo, ["BL-274", "BL-275"])
    _git(repo, "commit", "-qam", "branch adds BL-275 (unrelated defect)")

    assert cbi.id_novelty_violations(repo, "base-ref") == ["BL-275"]


def test_wiring_passes_when_the_new_id_is_free(tmp_path):
    repo = tmp_path / "r"
    (repo / "docs").mkdir(parents=True)
    _backlog(repo, ["BL-274"])
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "merge base")
    _git(repo, "branch", "base-ref")
    _git(repo, "checkout", "-q", "base-ref")
    _backlog(repo, ["BL-274", "BL-275"])
    _git(repo, "commit", "-qam", "base adds BL-275")
    _git(repo, "checkout", "-q", "master" if _has(repo, "master") else "main")
    _backlog(repo, ["BL-274", "BL-280"])
    _git(repo, "commit", "-qam", "branch adds BL-280")

    assert cbi.id_novelty_violations(repo, "base-ref") == []


def test_unresolvable_base_raises_rather_than_passing(tmp_path):
    # A gate that returns "no violations" when it cannot read its base is
    # decorative. The module's contract is exit 2 = could not run, NOT a pass.
    repo = tmp_path / "r"
    (repo / "docs").mkdir(parents=True)
    _backlog(repo, ["BL-274"])
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "base")

    try:
        cbi.id_novelty_violations(repo, "origin/nope")
    except cbi.GitUnavailable:
        return
    raise AssertionError("unresolvable base must raise GitUnavailable, not pass")


def _has(repo, branch):
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", branch],
                       capture_output=True, text=True)
    return r.returncode == 0
