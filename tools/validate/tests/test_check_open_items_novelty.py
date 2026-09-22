"""Unit tests for check_open_items' item-number novelty rule.

Two branches each appending the next free `## #N` to the same open-items.md merge
without a conflict — different hunks, no overlap. `parse_open_items` then dedups
by number ("most resolved wins"), so the merged index silently keeps one item and
drops the other: an open item disappears from the cross-skill triage view.

The no-fire cases carry the weight. `#N` is scoped per file, so two skills both
having a `#3` is normal. And `ts-audit/references/open-items.md` deliberately
carries a VERIFIED block above an UNVERIFIED one with #1-#4 and #8 in both — the
same item re-verified later, which is what the dedup exists for. Both are present
at the merge base, so the three-point rule treats them as inherited. A rule that
fired on either would be switched off the day it landed.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_open_items as coi  # noqa: E402
from _novelty import BaseUnavailable  # noqa: E402


# --- header parsing --------------------------------------------------------

def test_item_numbers_accepts_two_and_three_hash_headers():
    # ts-audit uses `###` throughout. The rule borrows the index generator's
    # pattern so the two cannot drift apart again — see the depth test below.
    text = (
        "## #3 — two hashes — VERIFIED\n"
        "### #4 — three hashes — OPEN\n"
        "## Item 5 — the `Item N` spelling — VERIFIED\n"
    )
    assert coi._item_numbers(text) == {"3", "4", "5"}


def test_item_numbers_ignores_prose_mentioning_a_number():
    text = "## #3 — real — OPEN\n\nSee #4 and item 5 for context.\n"
    assert coi._item_numbers(text) == {"3"}


# --- the wiring ------------------------------------------------------------

def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _setup(tmp_path, files: dict[str, str]):
    repo = tmp_path / "r"
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "merge base")
    _git(repo, "branch", "base-ref")
    return repo


A = "agents/cli/ts-a/references/open-items.md"
B = "agents/cli/ts-b/references/open-items.md"


def test_both_branches_claiming_the_same_number_is_flagged(tmp_path):
    repo = _setup(tmp_path, {A: "## #1 — existing — VERIFIED\n"})
    # base gains its own #2
    _git(repo, "checkout", "-q", "base-ref")
    (repo / A).write_text("## #1 — existing — VERIFIED\n## #2 — base item — VERIFIED\n",
                          encoding="utf-8")
    _git(repo, "commit", "-qam", "base claims #2")
    # our branch independently adds a different #2
    _git(repo, "checkout", "-q", "-")
    (repo / A).write_text("## #1 — existing — VERIFIED\n## #2 — our item — VERIFIED\n",
                          encoding="utf-8")

    out = coi.item_novelty_violations(repo, "base-ref", [repo / A])
    assert out == [f"{A}: #2"]


def test_same_number_in_a_different_file_is_not_a_collision(tmp_path):
    # `#N` is scoped per open-items.md. Two skills both having a #2 is ordinary.
    repo = _setup(tmp_path, {A: "## #1 — a — VERIFIED\n", B: "## #1 — b — VERIFIED\n"})
    _git(repo, "checkout", "-q", "base-ref")
    (repo / A).write_text("## #1 — a — VERIFIED\n## #2 — base item — VERIFIED\n",
                          encoding="utf-8")
    _git(repo, "commit", "-qam", "base adds #2 to file A")
    _git(repo, "checkout", "-q", "-")
    (repo / B).write_text("## #1 — b — VERIFIED\n## #2 — our item — VERIFIED\n",
                          encoding="utf-8")

    out = coi.item_novelty_violations(repo, "base-ref", [repo / A, repo / B])
    assert out == []


def test_a_number_present_at_the_merge_base_is_inherited_not_a_collision(tmp_path):
    # The ts-audit shape: the same number appears twice in a file that both sides
    # already had. Nobody introduced it here.
    repo = _setup(tmp_path, {A: "### #1 — x — VERIFIED\n### #1 — x — UNVERIFIED\n"})
    _git(repo, "checkout", "-q", "base-ref")
    (repo / A).write_text("### #1 — x — VERIFIED\n### #1 — x — UNVERIFIED\n### #9 — new — OPEN\n",
                          encoding="utf-8")
    _git(repo, "commit", "-qam", "base moves on")
    _git(repo, "checkout", "-q", "-")

    out = coi.item_novelty_violations(repo, "base-ref", [repo / A])
    assert out == []


def test_a_brand_new_file_cannot_collide(tmp_path):
    # A new skill's open-items.md does not exist on the base, so read_at returns
    # "" and every number in it is novel.
    repo = _setup(tmp_path, {A: "## #1 — a — VERIFIED\n"})
    _git(repo, "checkout", "-q", "base-ref")
    (repo / A).write_text("## #1 — a — VERIFIED\n## #2 — base — VERIFIED\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "base adds #2")
    _git(repo, "checkout", "-q", "-")
    (repo / B).parent.mkdir(parents=True, exist_ok=True)
    (repo / B).write_text("## #2 — new skill's own numbering — VERIFIED\n", encoding="utf-8")

    out = coi.item_novelty_violations(repo, "base-ref", [repo / A, repo / B])
    assert out == []


def test_unresolvable_base_raises(tmp_path):
    repo = _setup(tmp_path, {A: "## #1 — a — VERIFIED\n"})
    try:
        coi.item_novelty_violations(repo, "origin/nope", [repo / A])
    except BaseUnavailable:
        return
    raise AssertionError("unresolvable base must raise, not return no violations")


# --- the header-depth bug this rule surfaced -------------------------------

def test_the_checker_sees_three_hash_items(tmp_path):
    # `_ITEM_HEADER` was `##`-only while the index generator accepted `##` and
    # `###`. ts-audit/references/open-items.md uses `###` for all 20 of its items,
    # so the gate saw ZERO of them — including 10 UNVERIFIED ones it exists to
    # surface — while the index listed all 20. The two patterns must agree.
    f = tmp_path / "open-items.md"
    f.write_text(
        "### #1 — three-hash, unresolved — UNVERIFIED\n\nbody\n"
        "## #2 — two-hash, unresolved — UNVERIFIED\n\nbody\n",
        encoding="utf-8",
    )
    found = coi.check_open_items_file(f)
    assert len(found) == 2, f"both depths must be seen, got {found}"
    assert {n.split(" ")[0] for n, _ in found} == {"#1", "#2"}
