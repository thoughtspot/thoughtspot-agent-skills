"""Tests for evidence.py — the block pr-ready writes for a PR description.

The block is evidence, so these pin the things that would make it misdescribe what
ran: a dirty tree must say DIRTY (the head SHA alone would name code that was not
what got checked), a NOT RUN or SKIP must say why and never hide under PASS, and
nothing machine-local — a home directory path — may reach a public PR.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import evidence

HEAD = "a" * 40
BASE = "b" * 40


def _r(id, status="PASS", tail="ok", seconds=1.0, **extra):
    return {"id": id, "status": status, "seconds": seconds, "output_tail": tail, **extra}


def _render(**over):
    kwargs = dict(base_ref="upstream/main", base_sha=BASE, head_sha=HEAD, dirty=False,
                  behind=0, checks=[_r("secrets")], smokes=[_r("smoke_x")],
                  pytest=[_r("pytest tools/validate/tests/ -q")],
                  not_reproduced=["CI's pytest matrix"], review=None)
    kwargs.update(over)
    return evidence.render(**kwargs)


def test_evidence_marks_dirty_tree():
    assert "DIRTY" in _render(dirty=True)
    assert "DIRTY" not in _render(dirty=False)


def test_header_records_both_shas_and_the_base_ref():
    text = _render()
    first = text.splitlines()[0]
    assert HEAD in first and BASE in first and "upstream/main" in first, first


def test_evidence_lists_not_run_with_reason():
    text = _render(checks=[_r("secrets"), _r("ossie-mapping-sync", "NOT RUN", "ossie-checkout", 0.0)])
    section = text.split("## NOT RUN and SKIP", 1)[1].split("\n## ", 1)[0]
    assert "ossie-mapping-sync" in section, section
    assert "prerequisite absent: ossie-checkout" in section, section


def test_an_explicit_reason_wins():
    text = _render(checks=[_r("quality-gates-pr", "NOT RUN", "", 0.0, reason="no source changed")])
    assert "quality-gates-pr" in text and "no source changed" in text


def test_skip_and_promoted_skip_are_listed_with_their_skip_line():
    promoted = "required on every PR, but skipped here (missing tool):\nSKIP  radon is not installed"
    text = _render(checks=[
        _r("module-health", "FAIL", promoted),
        _r("thing", "SKIP", "checked 0\nSKIP  nothing to check"),
    ])
    section = text.split("## NOT RUN and SKIP", 1)[1].split("\n## ", 1)[0]
    assert "module-health" in section and "radon is not installed" in section, section
    assert "counted as FAIL" in section, section
    assert "thing" in section and "SKIP  nothing to check" in section, section


def test_no_not_run_or_skip_says_none():
    section = _render().split("## NOT RUN and SKIP", 1)[1].split("\n## ", 1)[0]
    assert "None" in section, section


def test_results_table_has_every_result_and_its_status():
    text = _render(checks=[_r("secrets"), _r("tml", "FAIL", "FAIL  x")],
                   smokes=[_r("smoke_a", "PASS")], pytest=[_r("pytest a/ -q", "FAIL")])
    for row in ("| check | `secrets` | PASS |", "| check | `tml` | FAIL |",
                "| smoke | `smoke_a` | PASS |", "| pytest | `pytest a/ -q` | FAIL |"):
        assert row in text, (row, text)


def test_sections_in_order():
    text = _render()
    marks = ["head `", "Behind upstream", "## Results", "## NOT RUN and SKIP",
             "## Not reproduced locally", "## Review"]
    positions = [text.index(m) for m in marks]
    assert positions == sorted(positions), list(zip(marks, positions))


def test_behind_count_is_shown_and_not_ready():
    assert "Behind upstream main: 0 commits" in _render(behind=0)
    behind = _render(behind=3)
    assert "Behind upstream main: 3 commits" in behind
    assert "NOT READY" in behind


def test_verdict_ready_only_when_green_and_current():
    assert "READY" in _render() and "NOT READY" not in _render()
    assert "NOT READY" in _render(checks=[_r("tml", "FAIL")])
    # WARN, SKIP and NOT RUN do not block, matching run_checks.exit_code.
    assert "NOT READY" not in _render(checks=[_r("pr-size", "WARN"), _r("o", "NOT RUN", "x")])


def test_not_reproduced_items_are_listed():
    text = _render(not_reproduced=["matrix 3.10", "pip-audit absent"])
    section = text.split("## Not reproduced locally", 1)[1].split("\n## ", 1)[0]
    assert "- matrix 3.10" in section and "- pip-audit absent" in section, section


def test_review_placeholder_and_text():
    assert "Not run" in _render(review=None).split("## Review", 1)[1]
    assert "found nothing" in _render(review="I checked X and found nothing").split("## Review", 1)[1]


def test_evidence_has_no_absolute_home_paths():
    text = _render(
        checks=[_r("references", "SKIP", "SKIP  /Users/alice/Dev/repo/x.md missing"),
                _r("o", "NOT RUN", "/home/bob/ossie", 0.0)],
        not_reproduced=["interpreter /Users/alice/.local/bin/python3.12"],
        review="see /home/bob/notes.txt and C:\\Users\\carol\\x",
    )
    assert "/Users/" not in text and "/home/" not in text and "\\Users\\" not in text, text
    assert "alice" not in text and "bob" not in text and "carol" not in text, text


def test_write_goes_to_the_git_dir(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    path = evidence.write("hello\n", tmp_path)
    git_dir = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=tmp_path,
                             check=True, capture_output=True, text=True).stdout.strip()
    assert path == Path(git_dir) / "pr-ready" / "evidence.md"
    assert path.read_text(encoding="utf-8") == "hello\n"
    # Never in the work tree, so never tracked.
    assert not (tmp_path / "pr-ready").exists()


def test_a_soft_checks_promoted_skip_is_listed():
    promoted = f"{evidence.PROMOTED_PREFIX}\nSKIP  tool absent"
    section = _render(checks=[_r("soft-one", "WARN", promoted)]).split(
        "## NOT RUN and SKIP", 1)[1].split("\n## ", 1)[0]
    assert "soft-one" in section and "SKIP  tool absent" in section, section
    assert "WARN" in section, section


def test_skipped_tests_are_listed_with_missing_modules_marked():
    r = _r("pytest a/ -q", "FAIL", skips=["a/t.py:1: No module named 'x'", "a/u.py:2: $D unset"],
           missing=["a/t.py:1: No module named 'x'"])
    section = _render(pytest=[r]).split("## NOT RUN and SKIP", 1)[1].split("\n## ", 1)[0]
    assert "a/t.py:1: No module named 'x'; a missing module" in section, section
    assert "a/u.py:2: $D unset" in section and "a/u.py:2: $D unset;" not in section, section


def test_scrub_handles_windows_names_with_spaces_doubled_backslashes_and_root():
    for raw, name in (("C:\\Users\\Carol Ann\\Docs\\x", "Carol"),
                      (repr("C:\\Users\\dave\\x"), "dave"),
                      ("D:\\\\Users\\\\erin\\\\x", "erin"),
                      ("cache at /root/.cache/pip", "/root")):
        text = _render(review=raw)
        assert name not in text, (raw, text.split("## Review", 1)[1])
    assert "/rootfs/x" in _render(review="/rootfs/x")


@pytest.mark.parametrize("raw, name", [
    ("c:\\users\\carol\\docs", "carol"),
    ("built in C:\\Users\\Carol Ann", "Ann"),
    ("C:\\USERS\\Dave Smith\\x", "Smith"),
])
def test_scrub_any_case_and_a_trailing_name_with_a_space(raw, name):
    text = _render(review=raw)
    assert name not in text, text.split("## Review", 1)[1]


def test_unfinished_placeholder_is_not_ready():
    assert "NOT READY" in evidence.UNFINISHED
    assert "**READY**" not in evidence.UNFINISHED


def test_unverifiable_skips_are_listed_as_fail():
    r = _r("pytest a/ -q", "FAIL", problems=["pytest reported 4 skipped but its -rs report lists 0"])
    section = _render(pytest=[r]).split("## NOT RUN and SKIP", 1)[1].split("\n## ", 1)[0]
    assert "skips unverifiable" in section and "counted as FAIL" in section, section


# ------------------------------------------------- the pr-ready skill's review ---
#
# The skill runs the reviewer after pr-ready.sh and puts its findings in the Review
# section. Appending must not make the block lie: the review covers a diff, so it
# belongs only on a block for the same head, and only on a block whose checks ran
# on that head's committed code.

#: A minimal review that passes the closer rule.
DONE = "\n### What I checked and found nothing\n- everything: nothing\n"


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f").write_text("x\n")
    subprocess.run(["git", "add", "f"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "commit", "-qm", "c"], cwd=tmp_path, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_header_reads_back_what_render_wrote():
    head = evidence.header(_render(dirty=True))
    assert head == {"head_sha": HEAD, "base_ref": "upstream/main", "base_sha": BASE,
                    "dirty": True}
    assert evidence.header(_render())["dirty"] is False
    assert evidence.header(evidence.UNFINISHED) is None


def test_with_review_replaces_the_placeholder_and_keeps_the_rest():
    before = _render()
    after = evidence.with_review(before, "### Blocker\n- none\n" + DONE, head_sha=HEAD)
    assert before.split("## Review", 1)[0] == after.split("## Review", 1)[0]
    section = after.split("## Review", 1)[1]
    assert "Not run." not in section and "### Blocker" in section, section
    assert HEAD in section and "advisory" in section.lower(), section


def test_with_review_twice_replaces_rather_than_stacks():
    once = evidence.with_review(_render(), "first review" + DONE, head_sha=HEAD)
    twice = evidence.with_review(once, "second review" + DONE, head_sha=HEAD)
    assert "first review" not in twice and "second review" in twice
    assert twice.count("## Review") == 1


def test_with_review_refuses_another_head():
    with pytest.raises(ValueError, match="head"):
        evidence.with_review(_render(), "r" + DONE, head_sha="c" * 40)


def test_with_review_refuses_a_dirty_block():
    # Its checks ran on uncommitted code the reviewer's diff does not contain.
    with pytest.raises(ValueError, match="DIRTY"):
        evidence.with_review(_render(dirty=True), "r" + DONE, head_sha=HEAD)


def test_with_review_refuses_an_unfinished_block():
    with pytest.raises(ValueError, match="finish"):
        evidence.with_review(evidence.UNFINISHED, "r" + DONE, head_sha=HEAD)


def test_with_review_scrubs_home_paths():
    out = evidence.with_review(_render(), "see /Users/alice/x.py:3" + DONE, head_sha=HEAD)
    assert "/Users/" not in out and "alice" not in out


def test_cli_range_prints_the_shas_the_evidence_names(tmp_path, capsys):
    head = _repo(tmp_path)
    evidence.write(_render(head_sha=head), tmp_path)
    assert evidence.main(["range"], repo_root=tmp_path) == 0
    assert capsys.readouterr().out.strip() == f"{BASE}...{head}"


def test_cli_append_review_writes_into_the_evidence_file(tmp_path):
    head = _repo(tmp_path)
    path = evidence.write(_render(head_sha=head), tmp_path)
    review = tmp_path.parent / f"{tmp_path.name}-review.md"
    review.write_text("### Nit\n- f:1 something\n" + DONE, encoding="utf-8")
    assert evidence.main(["append-review", "--file", str(review)], repo_root=tmp_path) == 0
    assert "### Nit" in path.read_text(encoding="utf-8").split("## Review", 1)[1]


def test_cli_append_review_refuses_when_head_moved(tmp_path, capsys):
    _repo(tmp_path)
    path = evidence.write(_render(), tmp_path)        # names HEAD = "a" * 40
    review = tmp_path.parent / f"{tmp_path.name}-review.md"
    review.write_text("r\n" + DONE, encoding="utf-8")
    assert evidence.main(["append-review", "--file", str(review)], repo_root=tmp_path) == 1
    assert "Not run." in path.read_text(encoding="utf-8")
    assert "head" in capsys.readouterr().err


def test_cli_append_review_can_target_a_copy(tmp_path):
    head = _repo(tmp_path)
    copy = tmp_path.parent / f"{tmp_path.name}-copy.md"
    copy.write_text(_render(head_sha=head), encoding="utf-8")
    review = tmp_path.parent / f"{tmp_path.name}-review.md"
    review.write_text("sample\n" + DONE, encoding="utf-8")
    assert evidence.main(["append-review", "--file", str(review), "--evidence", str(copy)],
                         repo_root=tmp_path) == 0
    assert "sample" in copy.read_text(encoding="utf-8")
    assert not evidence.evidence_path(tmp_path).exists()


def test_with_review_refuses_a_blank_review():
    # A blank review would stamp the block "reviewed" with nothing behind it.
    for blank in ("", "   \n\t\n"):
        with pytest.raises(ValueError, match="empty"):
            evidence.with_review(_render(), blank, head_sha=HEAD)


def test_with_review_refuses_a_review_without_its_closer():
    # The closer is what shows a review ran: without it, nothing says what was tried.
    with pytest.raises(ValueError, match="What I checked and found nothing"):
        evidence.with_review(_render(), "### Blocker\nNone.\n", head_sha=HEAD)


def test_with_review_refuses_a_not_ready_block():
    failing = _render(checks=[_r("secrets", "FAIL", "boom")])
    with pytest.raises(ValueError, match="NOT READY"):
        evidence.with_review(failing, "r" + DONE, head_sha=HEAD)
    with pytest.raises(ValueError, match="NOT READY"):
        evidence.with_review(_render(behind=2), "r" + DONE, head_sha=HEAD)


def test_cli_append_review_refuses_a_blank_file(tmp_path, capsys):
    head = _repo(tmp_path)
    path = evidence.write(_render(head_sha=head), tmp_path)
    review = tmp_path.parent / f"{tmp_path.name}-review.md"
    review.write_text("\n", encoding="utf-8")
    assert evidence.main(["append-review", "--file", str(review)], repo_root=tmp_path) == 1
    assert "Not run." in path.read_text(encoding="utf-8")
    assert "empty" in capsys.readouterr().err


@pytest.mark.parametrize("raw,name", [
    # Claude Code's project and scratchpad folders: the path with `/` as `-`.
    ("/private/tmp/claude-501/-Users-alice-Dev-x/scratchpad/a.md", "alice"),
    ("~/.claude/projects/-home-bob-Dev-repo/memory.md", "bob"),
    ("cited `-Users-carol-ann-Dev-repo` here", "carol"),
    ("C--Users-dave-proj", "dave"),
])
def test_scrub_dash_encoded_home_paths(raw, name):
    assert name not in evidence.scrub(raw)


def test_scrub_leaves_ordinary_hyphenated_words():
    assert evidence.scrub("take-home-pay and pre-Users-x") == "take-home-pay and pre-Users-x"
