"""Tests for the baseline PR metrics collector (tools/pr-metrics/collect.py).

The collector's load-bearing promises are that maintainer and external PRs are
reported separately, that a review round means a real reviewer asked for work, and
that no login reaches the committed report — the report is keyed by PR number only
(`.claude/rules/security.md`). Every login below is fake.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

_COLLECT = pathlib.Path(__file__).resolve().parents[1] / "collect.py"


def _load():
    # The directory name contains a hyphen, so it is not importable as a package;
    # load the module by path, as tools/ossie-roundtrip/tests does.
    spec = importlib.util.spec_from_file_location("_pr_metrics_collect", _COLLECT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


collect_mod = _load()

MAINTAINER = "fake-maintainer-login"
CONTRIBUTOR = "fake-contributor-login"
REVIEWER = "fake-reviewer-login"


def _pr(number, login, reviews=None, created="2026-08-01T10:00:00Z",
        merged="2026-08-03T10:00:00Z", additions=10, deletions=5):
    return {
        "number": number,
        "author": {"login": login, "is_bot": False, "name": "Fake Display Name"},
        "state": "MERGED" if merged else "OPEN",
        "createdAt": created,
        "mergedAt": merged,
        "closedAt": merged,
        "additions": additions,
        "deletions": deletions,
        "reviews": reviews or [],
    }


def _review(state, body="", login=REVIEWER, type_="User"):
    return {"state": state, "body": body, "login": login, "type": type_}


def _run(prs, attributions=None, overrides=None):
    return collect_mod.collect(prs, attributions or [], "2026-07-01", "2026-10-28",
                               maintainer=MAINTAINER, overrides=overrides)


def _attribution(**kw):
    entry = {"fix_pr": 3, "introduced_by_pr": 2, "introduced_on": "2026-08-01",
             "found_by": "audit", "note": "synthetic"}
    entry.update(kw)
    return entry


# --- grouping ----------------------------------------------------------------------

def test_collect_groups_by_maintainer():
    result = _run([_pr(1, MAINTAINER), _pr(2, CONTRIBUTOR)])
    assert result["groups"]["maintainer"]["pr_count"] == 1
    assert result["groups"]["external"]["pr_count"] == 1


def test_maintainer_match_is_case_insensitive():
    result = _run([_pr(1, MAINTAINER.upper())])
    assert result["groups"]["maintainer"]["pr_count"] == 1


def test_prs_outside_window_are_excluded():
    result = _run([_pr(1, MAINTAINER, created="2026-06-30T23:59:59Z"),
                   _pr(2, MAINTAINER, created="2026-10-28T23:00:00Z")])
    assert result["groups"]["maintainer"]["pr_count"] == 1


def test_bots_are_not_counted_as_external():
    bot = _pr(5, "app/fake-bot")
    bot["author"]["is_bot"] = True
    result = _run([bot, _pr(2, CONTRIBUTOR)])
    assert result["groups"]["external"]["pr_count"] == 1
    assert result["groups"]["bot"]["pr_count"] == 1


def test_open_prs_have_no_days_open():
    result = _run([_pr(1, MAINTAINER, merged=None),
                   _pr(2, MAINTAINER, created="2026-08-01T00:00:00Z",
                       merged="2026-08-05T00:00:00Z")])
    group = result["groups"]["maintainer"]
    assert group["merged_count"] == 1
    assert group["open_count"] == 1
    assert group["median_days_open"] == 4.0
    assert group["median_hours_open"] == 96.0


# --- maintainer from CODEOWNERS ----------------------------------------------------

def test_maintainer_from_codeowners_single_owner(tmp_path):
    path = tmp_path / "CODEOWNERS"
    path.write_text("# owners\n/a.py   @Fake-Owner\n/b/  @fake-owner  # same one\n")
    assert collect_mod.maintainer_from_codeowners(path.read_text()) == "fake-owner"


@pytest.mark.parametrize("text", ["# nobody\n", "/a @fake-one\n/b @fake-two\n"])
def test_maintainer_from_codeowners_rejects_zero_or_several(text):
    with pytest.raises(ValueError, match="pass --maintainer"):
        collect_mod.maintainer_from_codeowners(text)


def test_main_fails_without_maintainer_when_codeowners_ambiguous(tmp_path, capsys):
    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text("/a @fake-one\n/b @fake-two\n")
    rc = collect_mod.main(["--since", "2026-07-01", "--until", "2026-10-28",
                           "--codeowners", str(codeowners)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "pass --maintainer" in err
    assert "fake-one" not in err


def test_repo_codeowners_names_exactly_one_owner():
    # The default is derived, not spelled out; if CODEOWNERS ever gains a second
    # owner, the default stops resolving and this says so before a run does.
    text = collect_mod.DEFAULT_CODEOWNERS.read_text(encoding="utf-8")
    assert collect_mod.maintainer_from_codeowners(text)


# --- review rounds -----------------------------------------------------------------

def test_review_rounds_counts_changes_requested_and_long_comments():
    reviews = [
        _review("CHANGES_REQUESTED"),
        _review("COMMENTED", "x" * 250),
        _review("COMMENTED", "y" * 20),
    ]
    assert collect_mod.review_rounds(reviews) == 2
    result = _run([_pr(2, CONTRIBUTOR, reviews=reviews)])
    assert result["groups"]["external"]["median_review_rounds"] == 2


def test_review_round_body_boundary():
    assert collect_mod.review_rounds([_review("COMMENTED", "x" * 199)]) == 0
    assert collect_mod.review_rounds([_review("COMMENTED", "x" * 200)]) == 1


def test_review_rounds_skip_pr_author_and_bots():
    reviews = [
        _review("COMMENTED", "x" * 300, login=CONTRIBUTOR.upper()),  # the author's reply
        _review("CHANGES_REQUESTED", login="fake-bot", type_="Bot"),
        _review("CHANGES_REQUESTED", login="fake-app[bot]"),
        _review("CHANGES_REQUESTED"),
    ]
    result = _run([_pr(2, CONTRIBUTOR, reviews=reviews)])
    assert result["prs"][0]["review_rounds"] == 1


def test_override_replaces_computed_rounds_and_is_flagged():
    reviews = [_review("CHANGES_REQUESTED")]
    result = _run([_pr(2, CONTRIBUTOR, reviews=reviews), _pr(4, CONTRIBUTOR)],
                  overrides=[{"pr": 2, "rounds": 6, "note": "comment-posted reviews"}])
    row = result["prs"][0]
    assert (row["review_rounds"], row["review_rounds_auto"]) == (6, 1)
    assert row["rounds_overridden"] is True
    assert result["overridden_prs"] == [2]
    text = collect_mod.render_markdown(result)
    assert "| #2 | MERGED | 2 | 15 | 6 † (1) |" in text
    assert "| #4 | MERGED | 2 | 15 | 0 |" in text
    assert "Overridden here: #2." in text


def test_override_listing_a_pr_twice_is_rejected():
    with pytest.raises(ValueError, match="listed twice"):
        _run([_pr(2, CONTRIBUTOR)], overrides=[{"pr": 2, "rounds": 1}, {"pr": 2, "rounds": 2}])


def test_committed_overrides_file_is_valid():
    entries = collect_mod._load_yaml_list(collect_mod.DEFAULT_OVERRIDES, "rounds overrides")
    collect_mod._validate_overrides(entries)


# --- attributions ------------------------------------------------------------------

def test_attributions_join_by_introducing_pr():
    # PR 2 (external) introduced the defect; PR 3 (maintainer) fixed it. The defect
    # is counted by when and where it entered, so it lands on the external group.
    result = _run([_pr(1, MAINTAINER), _pr(2, CONTRIBUTOR), _pr(3, MAINTAINER)],
                  [_attribution()])
    assert result["groups"]["external"]["post_merge_defects"] == 1
    assert result["groups"]["maintainer"]["post_merge_defects"] == 0


def test_bad_found_by_is_rejected():
    with pytest.raises(ValueError, match="found_by"):
        _run([_pr(2, CONTRIBUTOR)], [_attribution(found_by="someone")])


def test_bad_introduced_on_is_rejected():
    with pytest.raises(ValueError, match="introduced_on"):
        _run([_pr(2, CONTRIBUTOR)], [_attribution(introduced_on="last tuesday")])


def test_missing_attributions_file_fails(tmp_path, capsys):
    rc = collect_mod.main(["--since", "2026-07-01", "--until", "2026-10-28",
                           "--maintainer", MAINTAINER,
                           "--attributions", str(tmp_path / "atributions.yaml")])
    assert rc == 2
    assert "attributions file not found" in capsys.readouterr().err


def test_empty_attributions_file_is_fine(tmp_path):
    path = tmp_path / "attributions.yaml"
    path.write_text("# nothing yet\n[]\n")
    assert collect_mod._load_yaml_list(path, "attributions") == []
    path.write_text("# comments only\n")
    assert collect_mod._load_yaml_list(path, "attributions") == []


# --- privacy -----------------------------------------------------------------------

def test_output_has_no_author_logins():
    prs = [_pr(1, MAINTAINER), _pr(2, CONTRIBUTOR, reviews=[_review("CHANGES_REQUESTED")])]
    result = _run(prs, overrides=[{"pr": 2, "rounds": 3, "note": "synthetic"}])
    text = collect_mod.render_markdown(result)
    for value in (MAINTAINER, CONTRIBUTOR, REVIEWER, "Fake Display Name"):
        assert value not in text


def _main_with_fakes(tmp_path, monkeypatch, note):
    attributions = tmp_path / "attributions.yaml"
    attributions.write_text(
        "- fix_pr: 3\n  introduced_by_pr: 2\n  introduced_on: 2026-08-01\n"
        f"  found_by: review\n  note: {note}\n")
    overrides = tmp_path / "rounds_overrides.yaml"
    overrides.write_text("[]\n")
    prs = [_pr(2, CONTRIBUTOR), _pr(3, MAINTAINER)]
    monkeypatch.setattr(collect_mod, "fetch_prs", lambda repo: prs)
    monkeypatch.setattr(collect_mod, "fetch_reviews",
                        lambda repo, n: [_review("CHANGES_REQUESTED")])
    out = tmp_path / "report.md"
    rc = collect_mod.main(["--since", "2026-07-01", "--until", "2026-10-28",
                           "--maintainer", MAINTAINER, "--attributions", str(attributions),
                           "--rounds-overrides", str(overrides), "--out", str(out)])
    return rc, out


@pytest.mark.parametrize("login", [CONTRIBUTOR, REVIEWER, MAINTAINER.upper()])
def test_leak_guard_refuses_a_login_in_an_attribution_note(tmp_path, monkeypatch, capsys,
                                                           login):
    rc, out = _main_with_fakes(tmp_path, monkeypatch, f"regressed by {login}")
    assert rc == 1
    assert not out.exists()
    assert login.lower() not in capsys.readouterr().err.lower()


def test_leak_guard_passes_a_clean_report(tmp_path, monkeypatch):
    rc, out = _main_with_fakes(tmp_path, monkeypatch, "synthetic note")
    assert rc == 0
    text = out.read_text()
    assert "collected at 20" in text
    assert "| #2 | 2026-08-01 | external | #3 | review | synthetic note |" in text


def test_identities_include_reviewers():
    prs = [_pr(2, CONTRIBUTOR, reviews=[_review("COMMENTED")])]
    assert {CONTRIBUTOR, REVIEWER, "Fake Display Name"} <= collect_mod.identities(prs)


# --- gh list limit -----------------------------------------------------------------

def test_fetch_prs_refuses_a_result_at_the_limit(monkeypatch):
    rows = [{"number": n} for n in range(collect_mod.PR_LIST_LIMIT)]
    monkeypatch.setattr(collect_mod, "_gh", lambda args: json.dumps(rows))
    with pytest.raises(RuntimeError, match="truncated"):
        collect_mod.fetch_prs("fake/repo")


def test_fetch_prs_accepts_a_result_under_the_limit(monkeypatch):
    rows = [{"number": n} for n in range(collect_mod.PR_LIST_LIMIT - 1)]
    monkeypatch.setattr(collect_mod, "_gh", lambda args: json.dumps(rows))
    assert len(collect_mod.fetch_prs("fake/repo")) == collect_mod.PR_LIST_LIMIT - 1
