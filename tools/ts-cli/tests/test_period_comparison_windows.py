# tools/ts-cli/tests/test_period_comparison_windows.py
import dataclasses
import json
from datetime import date

import pytest

from ts_cli.period_comparison.windows import (
    PlanError,
    PlanSpec,
    Window,
    build_plan,
    comparison_step,
    load_custom_windows,
)

T = date(2026, 11, 18)


def test_black_friday_2025_prior_six():
    r = build_plan(PlanSpec("black-friday", years=(2025,)), T)
    y = r.years[0]
    assert y.event == Window(date(2025, 11, 28), date(2025, 12, 1))
    assert y.comparisons[0] == Window(date(2025, 11, 21), date(2025, 11, 24))
    assert y.comparisons[-1] == Window(date(2025, 10, 17), date(2025, 10, 20))
    assert r.step == 7 and len(y.comparisons) == 6


def test_step_rounds_to_weeks():
    assert [comparison_step(n) for n in (1, 7, 8, 14, 15)] == [7, 7, 14, 14, 21]


def test_window_crossing_new_year_is_error():
    with pytest.raises(PlanError, match="2025"):
        build_plan(PlanSpec("christmas", length=10, years=(2025,)), T)


def test_last_n_skips_unfinished_year():
    r = build_plan(PlanSpec("black-friday", last=3), T)
    assert [y.year for y in r.years] == [2023, 2024, 2025]


def test_explicit_unfinished_year_dropped():
    r = build_plan(PlanSpec("black-friday", years=(2025, 2026)), T)
    assert r.dropped_years == (2026,)


def test_boxing_day_clash_reported_then_skipped():
    spec = PlanSpec("boxing-day", years=(2025,))
    r = build_plan(spec, T)
    assert r.needs_clash_decision
    assert {c.event for c in r.clashes} >= {"black-friday", "cyber-monday"}
    r2 = build_plan(dataclasses.replace(spec, on_clash="skip"), T)
    y = r2.years[0]
    assert Window(date(2025, 11, 28), date(2025, 12, 1)) not in y.comparisons
    assert Window(date(2025, 11, 7), date(2025, 11, 10)) in y.comparisons and len(y.comparisons) == 6


def test_keep_leaves_clash():
    r = build_plan(PlanSpec("boxing-day", years=(2025,), on_clash="keep"), T)
    assert Window(date(2025, 11, 28), date(2025, 12, 1)) in r.years[0].comparisons


def test_custom_overlap_is_error():
    with pytest.raises(PlanError, match="overlap"):
        build_plan(PlanSpec("black-friday", years=(2025,), comparison="custom",
            custom_comparison={2025: [Window(date(2025, 11, 29), date(2025, 12, 3))]}), T)


def test_custom_missing_year_is_error():
    with pytest.raises(PlanError, match="2024"):
        build_plan(PlanSpec("custom", years=(2024, 2025),
            custom_event={2025: [Window(date(2025, 7, 8), date(2025, 7, 8))]}), T)


def test_length_zero_is_error():
    with pytest.raises(PlanError):
        build_plan(PlanSpec("black-friday", length=0, years=(2025,)), T)


def test_load_custom_windows(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("2025: '2025-07-08'\n2024: [['2024-07-16','2024-07-17']]\n")
    w = load_custom_windows(p)
    assert w[2024] == [Window(date(2024, 7, 16), date(2024, 7, 17))]
    assert w[2025] == date(2025, 7, 8)


# --- edges the rules imply ---

def test_window_days_and_overlaps():
    a = Window(date(2025, 1, 1), date(2025, 1, 4))
    assert a.days == 4
    assert a.overlaps(Window(date(2025, 1, 4), date(2025, 1, 9)))
    assert not a.overlaps(Window(date(2025, 1, 5), date(2025, 1, 9)))


def test_window_end_before_start_is_error():
    with pytest.raises(PlanError, match="2025-01-04"):
        Window(date(2025, 1, 4), date(2025, 1, 1))


def test_skip_records_substitution_and_keeps_clash_list():
    r = build_plan(PlanSpec("boxing-day", years=(2025,), on_clash="skip"), T)
    y = r.years[0]
    assert y.substitutions == ((Window(date(2025, 11, 28), date(2025, 12, 1)),
                                Window(date(2025, 11, 7), date(2025, 11, 10))),)
    assert not r.needs_clash_decision
    assert {c.event for c in r.clashes} == {"black-friday", "cyber-monday"}
    starts = [w.start for w in y.comparisons]
    assert starts == sorted(starts, reverse=True)


def test_undecided_clash_leaves_windows_unchanged():
    r = build_plan(PlanSpec("boxing-day", years=(2025,)), T)
    assert Window(date(2025, 11, 28), date(2025, 12, 1)) in r.years[0].comparisons
    assert r.years[0].substitutions == ()


def test_analysed_event_is_not_a_clash_with_itself():
    # Cyber Monday's own comparison windows never reach Black Friday's anchor inside
    # the same window, but Black Friday analysed alone must not clash with itself.
    r = build_plan(PlanSpec("black-friday", years=(2025,)), T)
    assert r.clashes == () and not r.needs_clash_decision


def test_prior_window_crossing_new_year_is_error():
    # Easter 2024 is 31 March; 13 prior weeks reach 31 December 2023.
    with pytest.raises(PlanError, match="2023-12-31"):
        build_plan(PlanSpec("easter", years=(2024,), prior_weeks=13), T)


def test_skip_replacement_crossing_new_year_is_error():
    # Boxing Day 2025, 51 prior weeks: k=4 clashes (Black Friday) and k=36 clashes
    # (Easter, 20 April). Window 51 starts 3 January; the second replacement (k=53)
    # would start 27 December 2024.
    spec = PlanSpec("boxing-day", years=(2025,), prior_weeks=51)
    assert len(build_plan(dataclasses.replace(spec, on_clash="keep"), T).years[0].comparisons) == 51
    with pytest.raises(PlanError, match="2024-12-27"):
        build_plan(dataclasses.replace(spec, on_clash="skip"), T)


def test_custom_event_start_date_expands_with_offset_and_length():
    r = build_plan(PlanSpec("custom", years=(2025,), offset=-1, length=3,
                            custom_event={2025: date(2025, 7, 8)}), T)
    assert r.years[0].event == Window(date(2025, 7, 7), date(2025, 7, 9))


def test_custom_event_range_used_as_given_and_sets_step():
    r = build_plan(PlanSpec("custom", years=(2025,),
                            custom_event={2025: [Window(date(2025, 7, 1), date(2025, 7, 10))]}), T)
    assert r.years[0].event == Window(date(2025, 7, 1), date(2025, 7, 10))
    assert r.step == 14
    assert r.years[0].comparisons[0] == Window(date(2025, 6, 17), date(2025, 6, 26))


def test_custom_comparison_used_as_given():
    cmp_ = [Window(date(2025, 11, 1), date(2025, 11, 4)), Window(date(2025, 10, 1), date(2025, 10, 4))]
    r = build_plan(PlanSpec("black-friday", years=(2025,), comparison="custom",
                            custom_comparison={2025: cmp_}), T)
    assert r.years[0].comparisons == tuple(cmp_)


def test_custom_comparisons_overlapping_each_other_is_error():
    cmp_ = [Window(date(2025, 11, 1), date(2025, 11, 4)), Window(date(2025, 11, 4), date(2025, 11, 6))]
    with pytest.raises(PlanError, match="overlap"):
        build_plan(PlanSpec("black-friday", years=(2025,), comparison="custom",
                            custom_comparison={2025: cmp_}), T)


def test_last_n_with_custom_event_uses_supplied_years():
    ev = {y: date(y, 7, 8) for y in (2022, 2023, 2024, 2025, 2026)}
    r = build_plan(PlanSpec("custom", last=2, custom_event=ev), date(2026, 7, 1))
    assert [y.year for y in r.years] == [2024, 2025]
    assert r.dropped_years == (2026,)


def test_last_n_not_enough_years_is_error():
    with pytest.raises(PlanError):
        build_plan(PlanSpec("custom", last=3, custom_event={2025: date(2025, 7, 8)}), T)


def test_years_and_last_together_is_error():
    with pytest.raises(PlanError):
        build_plan(PlanSpec("black-friday", years=(2025,), last=2), T)


def test_unknown_event_is_error():
    with pytest.raises(PlanError, match="diwali"):
        build_plan(PlanSpec("diwali", years=(2025,)), T)


def test_load_custom_windows_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"2025": [["2025-11-01", "2025-11-04"], ["2025-10-01", "2025-10-04"]]}))
    w = load_custom_windows(p)
    assert w == {2025: [Window(date(2025, 11, 1), date(2025, 11, 4)),
                        Window(date(2025, 10, 1), date(2025, 10, 4))]}


def test_load_custom_windows_bad_year_is_error(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("twenty: '2025-07-08'\n")
    with pytest.raises(PlanError, match="twenty"):
        load_custom_windows(p)


def test_custom_comparison_given_as_single_date_is_error():
    with pytest.raises(PlanError, match="2025-11-01"):
        build_plan(PlanSpec("black-friday", years=(2025,), comparison="custom",
                            custom_comparison={2025: date(2025, 11, 1)}), T)


# --- years missing from a custom file; the event's own anchor as a clash ---

def test_last_n_custom_event_gap_is_error():
    ev = {2022: date(2022, 7, 8), 2023: date(2023, 7, 8), 2025: date(2025, 7, 8)}
    with pytest.raises(PlanError, match="2024"):
        build_plan(PlanSpec("custom", last=3, custom_event=ev), T)


def test_explicit_unfinished_year_missing_from_comparison_file_is_error():
    cmp_ = {2025: [Window(date(2025, 11, 1), date(2025, 11, 4))]}
    with pytest.raises(PlanError, match="2026"):
        build_plan(PlanSpec("black-friday", years=(2025, 2026), comparison="custom",
                            custom_comparison=cmp_), T)


def test_explicit_unfinished_year_missing_from_event_file_is_error():
    with pytest.raises(PlanError, match="2026"):
        build_plan(PlanSpec("custom", years=(2025, 2026),
                            custom_event={2025: date(2025, 7, 8)}), T)


def test_last_n_current_year_missing_from_event_file_is_dropped():
    ev = {y: date(y, 7, 8) for y in (2023, 2024, 2025)}
    r = build_plan(PlanSpec("custom", last=3, custom_event=ev), T)
    assert [y.year for y in r.years] == [2023, 2024, 2025]
    assert r.dropped_years == (2026,)


def test_last_n_current_year_missing_from_comparison_file_is_dropped():
    cmp_ = {y: [Window(date(y, 11, 1), date(y, 11, 4))] for y in (2024, 2025)}
    r = build_plan(PlanSpec("black-friday", last=2, comparison="custom",
                            custom_comparison=cmp_), T)
    assert [y.year for y in r.years] == [2024, 2025]
    assert r.dropped_years == (2026,)


def test_last_n_past_year_missing_from_comparison_file_is_error():
    cmp_ = {2025: [Window(date(2025, 11, 1), date(2025, 11, 4))]}
    with pytest.raises(PlanError, match="2024"):
        build_plan(PlanSpec("black-friday", last=2, comparison="custom",
                            custom_comparison=cmp_), T)


def test_own_anchor_in_comparison_window_is_a_clash():
    # Event window 5-8 Dec 2025; k=1 is 28 Nov-1 Dec, holding Black Friday itself
    # (28 Nov) and Cyber Monday (1 Dec).
    r = build_plan(PlanSpec("black-friday", offset=7, years=(2025,)), T)
    assert r.years[0].event == Window(date(2025, 12, 5), date(2025, 12, 8))
    assert {c.event for c in r.clashes} >= {"black-friday", "cyber-monday"}
    assert r.needs_clash_decision
    r2 = build_plan(PlanSpec("black-friday", offset=7, years=(2025,), on_clash="skip"), T)
    assert Window(date(2025, 11, 28), date(2025, 12, 1)) not in r2.years[0].comparisons
    assert len(r2.years[0].comparisons) == 6


# --- a current year missing from the comparison file under last=N ---

def _feb_ranges(years):
    return {y: [Window(date(y, 2, 1), date(y, 2, 4))] for y in years}


def test_last_n_ended_current_year_missing_from_comparison_file_is_error():
    # Easter 2026 (5-8 April) ended before the run date, so its comparison ranges
    # are knowable: leaving them out is an error, not a silent drop.
    spec = PlanSpec("easter", last=3, comparison="custom",
                    custom_comparison=_feb_ranges((2023, 2024, 2025)))
    with pytest.raises(PlanError, match="2026") as exc:
        build_plan(spec, T)
    assert "comparison" in str(exc.value)
    assert "2026-04-05 to 2026-04-08" in str(exc.value)


def test_last_n_unended_current_year_missing_from_comparison_file_is_dropped():
    # Run on 1 April 2026: Easter 2026 has not happened, so 2026 is dropped.
    spec = PlanSpec("easter", last=3, comparison="custom",
                    custom_comparison=_feb_ranges((2023, 2024, 2025)))
    r = build_plan(spec, date(2026, 4, 1))
    assert [y.year for y in r.years] == [2023, 2024, 2025]
    assert r.dropped_years == (2026,)
