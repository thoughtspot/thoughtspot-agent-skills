"""Tests for the baseline PR metrics collector (tools/pr-metrics/collect.py).

The collector's two load-bearing promises are that maintainer and external PRs are
reported separately, and that no author login reaches the committed report — the
report is keyed by PR number only (`.claude/rules/security.md`). Every login below is
fake.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

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


def _run(prs, attributions=None):
    return collect_mod.collect(prs, attributions or [], "2026-07-01", "2026-10-28",
                               maintainer=MAINTAINER)


def test_collect_groups_by_maintainer():
    result = _run([_pr(1, MAINTAINER), _pr(2, CONTRIBUTOR)])
    assert result["groups"]["maintainer"]["pr_count"] == 1
    assert result["groups"]["external"]["pr_count"] == 1


def test_output_has_no_author_logins():
    result = _run([_pr(1, MAINTAINER), _pr(2, CONTRIBUTOR)])
    text = collect_mod.render_markdown(result)
    assert MAINTAINER not in text
    assert CONTRIBUTOR not in text
    assert "Fake Display Name" not in text


def test_review_rounds_counts_changes_requested_and_long_comments():
    reviews = [
        {"state": "CHANGES_REQUESTED", "body": ""},
        {"state": "COMMENTED", "body": "x" * 250},
        {"state": "COMMENTED", "body": "y" * 20},
    ]
    assert collect_mod.review_rounds(reviews) == 2
    result = _run([_pr(2, CONTRIBUTOR, reviews=reviews)])
    assert result["groups"]["external"]["median_review_rounds"] == 2


def test_attributions_join_by_introducing_pr():
    # PR 2 (external) introduced the defect; PR 3 (maintainer) fixed it. The defect
    # is counted by when and where it entered, so it lands on the external group.
    attributions = [{
        "fix_pr": 3,
        "introduced_by_pr": 2,
        "introduced_on": "2026-08-01",
        "found_by": "audit",
        "note": "synthetic",
    }]
    result = _run([_pr(1, MAINTAINER), _pr(2, CONTRIBUTOR), _pr(3, MAINTAINER)],
                  attributions)
    assert result["groups"]["external"]["post_merge_defects"] == 1
    assert result["groups"]["maintainer"]["post_merge_defects"] == 0


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
    assert group["median_days_open"] == 4.0
    assert group["median_hours_open"] == 96.0


def test_bad_found_by_is_rejected():
    attributions = [{"fix_pr": 3, "introduced_by_pr": 2, "introduced_on": "2026-08-01",
                     "found_by": "someone", "note": "x"}]
    try:
        _run([_pr(2, CONTRIBUTOR)], attributions)
    except ValueError as exc:
        assert "found_by" in str(exc)
    else:
        raise AssertionError("an unknown found_by value must be rejected")
