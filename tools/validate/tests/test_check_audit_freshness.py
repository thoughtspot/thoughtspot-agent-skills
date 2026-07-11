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


# --- External cadence is satisfied by a full audit (a full audit covers the
#     external angles 13/14/16) ---------------------------------------------------

def test_full_audit_resets_external_clock():
    # The exact bug: a recent full audit but an older external-only report. The
    # external cadence must measure from the full audit, not the stale external file.
    latest_ext = date(2026, 6, 28)   # last external-only sweep
    latest_full = date(2026, 7, 11)  # more recent full audit
    eff = af._effective_external_date(latest_ext, latest_full)
    assert eff == date(2026, 7, 11)
    assert af._is_due(eff, af.EXTERNAL_MAX_AGE_DAYS, date(2026, 7, 12)) is False


def test_external_only_used_when_more_recent_than_full():
    eff = af._effective_external_date(date(2026, 7, 10), date(2026, 7, 1))
    assert eff == date(2026, 7, 10)


def test_effective_external_date_with_only_full():
    assert af._effective_external_date(None, date(2026, 7, 11)) == date(2026, 7, 11)


def test_effective_external_date_with_only_external():
    assert af._effective_external_date(date(2026, 7, 11), None) == date(2026, 7, 11)


def test_effective_external_date_none_when_neither_run():
    assert af._effective_external_date(None, None) is None


# --- Activity counting from a git-log block (baseline = commit SHA, not date) ------
# Input mirrors `git log <sha>..HEAD --name-status --pretty=format:%x00%H`: each commit
# is a NUL-prefixed header line followed by its name-status rows.

def _commit(sha: str, *rows: str) -> str:
    return "\x00" + sha + "\n" + "\n".join(rows)


def test_ts_cli_bump_touching_both_version_files_counts_once():
    # The double-count bug: one bump edits pyproject.toml AND __init__.py — one commit,
    # one bump, not two.
    log = _commit(
        "a" * 40,
        "M\ttools/ts-cli/pyproject.toml",
        "M\ttools/ts-cli/ts_cli/__init__.py",
    )
    counts = af._parse_activity(log)
    assert counts["ts_cli_bumps"] == 1
    assert counts["commits"] == 1


def test_two_separate_bump_commits_count_twice():
    log = "\n".join([
        _commit("a" * 40, "M\ttools/ts-cli/pyproject.toml", "M\ttools/ts-cli/ts_cli/__init__.py"),
        _commit("b" * 40, "M\ttools/ts-cli/pyproject.toml", "M\ttools/ts-cli/ts_cli/__init__.py"),
    ])
    counts = af._parse_activity(log)
    assert counts["ts_cli_bumps"] == 2
    assert counts["commits"] == 2


def test_new_skill_and_runtime_and_shared_counted():
    log = "\n".join([
        _commit("a" * 40, "A\tagents/cli/ts-new/SKILL.md"),
        _commit("b" * 40, "A\tagents/shared/schemas/foo.md", "A\tagents/shared/mappings/bar.md"),
    ])
    counts = af._parse_activity(log)
    assert counts["new_skills"] == 1
    assert counts["new_runtimes"] == 1   # "cli"
    assert counts["new_shared"] == 2
    assert counts["commits"] == 2


def test_modified_skill_is_not_a_new_skill():
    log = _commit("a" * 40, "M\tagents/cli/ts-existing/SKILL.md")
    assert af._parse_activity(log)["new_skills"] == 0


def test_empty_log_is_all_zeros():
    counts = af._parse_activity("")
    assert counts == {"new_skills": 0, "new_runtimes": 0, "new_shared": 0,
                      "ts_cli_bumps": 0, "commits": 0}
