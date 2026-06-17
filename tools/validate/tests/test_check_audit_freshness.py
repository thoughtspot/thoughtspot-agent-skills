"""Unit tests for check_audit_freshness — the date/age/activity logic (git-free)."""
from datetime import date
from pathlib import Path

import check_audit_freshness as af


def test_report_dates_parses_and_sorts(tmp_path):
    (tmp_path / "2026-06-17-full.md").write_text("x")
    (tmp_path / "2026-01-02-full.md").write_text("x")
    (tmp_path / "2026-06-10-external.md").write_text("x")  # different kind
    dates = af._report_dates(tmp_path, "full")
    assert dates == [date(2026, 1, 2), date(2026, 6, 17)]


def test_report_dates_ignores_other_kinds_and_junk(tmp_path):
    (tmp_path / "notes.md").write_text("x")
    (tmp_path / "2026-13-40-full.md").write_text("x")  # invalid date → skipped
    assert af._report_dates(tmp_path, "full") == []


def test_report_dates_missing_dir():
    assert af._report_dates(Path("/no/such/dir"), "full") == []


def test_is_due_when_no_prior_report():
    assert af._is_due(None, 7, date(2026, 6, 17)) is True


def test_is_due_when_older_than_max():
    assert af._is_due(date(2026, 6, 1), 7, date(2026, 6, 17)) is True


def test_not_due_when_within_max():
    assert af._is_due(date(2026, 6, 14), 7, date(2026, 6, 17)) is False


def test_age_days():
    assert af._age_days(date(2026, 6, 1), date(2026, 6, 17)) == 16


def test_activity_reasons_only_lists_crossed_thresholds():
    counts = {"new_skills": 2, "new_runtimes": 0, "new_shared": 0,
              "ts_cli_bumps": 0, "commits": 5}
    reasons = af._activity_reasons(counts)
    assert reasons == ["2 new skill(s)"]


def test_activity_reasons_empty_when_below_all():
    counts = {"new_skills": 0, "new_runtimes": 0, "new_shared": 1,
              "ts_cli_bumps": 0, "commits": 3}
    assert af._activity_reasons(counts) == []


def test_activity_reasons_multiple():
    counts = {"new_skills": 1, "new_runtimes": 1, "new_shared": 2,
              "ts_cli_bumps": 1, "commits": 99}
    assert len(af._activity_reasons(counts)) == 5
