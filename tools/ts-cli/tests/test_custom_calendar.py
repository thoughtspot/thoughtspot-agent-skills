# tools/ts-cli/tests/test_custom_calendar.py
import pytest
from ts_cli.custom_calendar.spec import (
    CalendarSpec, LabelSpec, CalendarSet, parse_day_of_week,
    validate_spec, validate_labels, PATTERNS, QUARTER_LAYOUT,
)


def _spec(**kw):
    base = dict(start_month=2, start_day_of_week=1, pattern="4-5-4",
                anchor_rule="nearest", first_year=2015, last_year=2026)
    base.update(kw)
    return CalendarSpec(**base)


def test_parse_day_of_week_is_sunday_based():
    assert parse_day_of_week("Sunday") == 0
    assert parse_day_of_week("Monday") == 1
    assert parse_day_of_week("Saturday") == 6
    with pytest.raises(ValueError):
        parse_day_of_week("Funday")


def test_patterns_all_sum_to_52_weeks():
    for name, weeks in PATTERNS.items():
        assert sum(weeks) == 52, name
        assert len(weeks) in QUARTER_LAYOUT


def test_thirteen_period_quarter_layout_is_3_3_3_4():
    assert QUARTER_LAYOUT[13] == (3, 3, 3, 4)
    assert QUARTER_LAYOUT[12] == (3, 3, 3, 3)


def test_validate_spec_rejects_unknown_pattern():
    with pytest.raises(ValueError, match="pattern"):
        validate_spec(_spec(pattern="6-6-1"))


def test_validate_spec_rejects_leap_period_out_of_range():
    with pytest.raises(ValueError, match="leap_week_period"):
        validate_spec(_spec(leap_week_period=13))       # 4-5-4 has 12 periods


def test_validate_spec_accepts_leap_period_13_for_13x4():
    validate_spec(_spec(pattern="13x4", leap_week_period=13))


def test_validate_labels_rejects_wrong_month_name_count():
    with pytest.raises(ValueError, match="month_names"):
        validate_labels(LabelSpec(month_names=("Jan", "Feb")), periods_per_year=12)


def test_calendar_set_holds_labels_at_set_level():
    s = CalendarSet(labels=LabelSpec(), variants=(("tsCal1", _spec()),))
    assert s.discriminator_column == "TS_CALENDAR_GROUP"
    assert s.materialisation == "view"


from datetime import date
from ts_cli.custom_calendar.anchors import (
    sunday_index, anchor_nearest, anchor_first, anchor_fixed52, resolve_anchor,
)

MONDAY = 1
FEB = 2

# Verified against CUSTOM_CALENDAR.PUBLIC.LULULEMON on 2026-09-15.
LULULEMON_STARTS = {
    2015: date(2015, 2, 2), 2016: date(2016, 2, 1), 2017: date(2017, 1, 30),
    2018: date(2018, 1, 29), 2019: date(2019, 2, 4), 2020: date(2020, 2, 3),
    2021: date(2021, 2, 1), 2022: date(2022, 1, 31), 2023: date(2023, 1, 30),
    2024: date(2024, 1, 29), 2025: date(2025, 2, 3), 2026: date(2026, 2, 2),
}


def test_sunday_index_conversion():
    assert sunday_index(date(2026, 9, 13)) == 0   # Sunday
    assert sunday_index(date(2026, 9, 14)) == 1   # Monday
    assert sunday_index(date(2026, 9, 19)) == 6   # Saturday


@pytest.mark.parametrize("year,expected", sorted(LULULEMON_STARTS.items()))
def test_anchor_nearest_reproduces_lululemon(year, expected):
    assert anchor_nearest(year, FEB, MONDAY) == expected


def test_nearest_yields_52_or_53_week_years_only():
    for year in range(2015, 2026):
        span = (anchor_nearest(year + 1, FEB, MONDAY)
                - anchor_nearest(year, FEB, MONDAY)).days
        assert span % 7 == 0
        assert span in (364, 371)


def test_lululemon_leap_years_are_2018_and_2024():
    leap = [y for y in range(2015, 2026)
            if (anchor_nearest(y + 1, FEB, MONDAY)
                - anchor_nearest(y, FEB, MONDAY)).days == 371]
    assert leap == [2018, 2024]


def test_anchor_first_differs_from_nearest_from_2017():
    # Both rules agree while drift is under half a week, then part company.
    assert anchor_first(2015, FEB, MONDAY) == date(2015, 2, 2)
    assert anchor_first(2016, FEB, MONDAY) == date(2016, 2, 1)
    assert anchor_first(2017, FEB, MONDAY) == date(2017, 2, 6)   # nearest gives Jan 30
    assert anchor_nearest(2017, FEB, MONDAY) == date(2017, 1, 30)


def test_anchor_first_also_tiles_in_whole_weeks():
    for year in range(2015, 2030):
        span = (anchor_first(year + 1, FEB, MONDAY)
                - anchor_first(year, FEB, MONDAY)).days
        assert span % 7 == 0


def test_fixed52_is_always_364_days():
    prev = None
    for year in range(2015, 2026):
        got = anchor_fixed52(year, FEB, MONDAY, first_year=2015)
        if prev is not None:
            assert (got - prev).days == 364
        prev = got


def test_fixed52_drifts_away_from_lululemon():
    # This is the defect that justifies the whole skill.
    assert anchor_fixed52(2018, FEB, MONDAY, first_year=2015) == LULULEMON_STARTS[2018]
    assert anchor_fixed52(2019, FEB, MONDAY, first_year=2015) == date(2019, 1, 28)
    assert LULULEMON_STARTS[2019] == date(2019, 2, 4)


def test_resolve_anchor_dispatches_on_rule():
    common = dict(start_month=FEB, start_day_of_week=MONDAY,
                  pattern="4-5-4", first_year=2015, last_year=2026)
    assert resolve_anchor(CalendarSpec(anchor_rule="nearest", **common), 2017) == date(2017, 1, 30)
    assert resolve_anchor(CalendarSpec(anchor_rule="first", **common), 2017) == date(2017, 2, 6)
    assert resolve_anchor(CalendarSpec(anchor_rule="fixed52", **common), 2019) == date(2019, 1, 28)


from ts_cli.custom_calendar.grid import build_years, Period, FiscalYear, _period_weeks


def _lulu_spec(first=2015, last=2026, **kw):
    base = dict(start_month=FEB, start_day_of_week=MONDAY, pattern="4-5-4",
                anchor_rule="nearest", first_year=first, last_year=last)
    base.update(kw)
    return CalendarSpec(**base)


def test_normal_year_is_52_weeks_in_454_shape():
    fy = {y.number: y for y in build_years(_lulu_spec())}[2017]
    assert fy.weeks == 52
    assert [p.weeks for p in fy.periods] == [4, 5, 4] * 4
    assert [p.quarter for p in fy.periods] == [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]


def test_leap_week_lands_on_final_period_matching_lululemon_2018():
    fy = {y.number: y for y in build_years(_lulu_spec())}[2018]
    assert fy.weeks == 53
    # LULULEMON 2018: Q4 is 4-5-5, every other quarter unchanged.
    assert [p.weeks for p in fy.periods] == [4, 5, 4, 4, 5, 4, 4, 5, 4, 4, 5, 5]
    assert fy.start == date(2018, 1, 29)
    assert fy.end_exclusive == date(2019, 2, 4)


def test_lululemon_2018_period_boundaries_exact():
    # Read from CUSTOM_CALENDAR.PUBLIC.LULULEMON on 2026-09-15.
    expected = [
        (date(2018, 1, 29), date(2018, 2, 26)), (date(2018, 2, 26), date(2018, 4, 2)),
        (date(2018, 4, 2), date(2018, 4, 30)),  (date(2018, 4, 30), date(2018, 5, 28)),
        (date(2018, 5, 28), date(2018, 7, 2)),  (date(2018, 7, 2), date(2018, 7, 30)),
        (date(2018, 7, 30), date(2018, 8, 27)), (date(2018, 8, 27), date(2018, 10, 1)),
        (date(2018, 10, 1), date(2018, 10, 29)), (date(2018, 10, 29), date(2018, 11, 26)),
        (date(2018, 11, 26), date(2018, 12, 31)), (date(2018, 12, 31), date(2019, 2, 4)),
    ]
    fy = {y.number: y for y in build_years(_lulu_spec())}[2018]
    assert [(p.start, p.end_exclusive) for p in fy.periods] == expected


def test_leap_week_placement_is_configurable():
    fy = {y.number: y for y in build_years(_lulu_spec(leap_week_period=1))}[2018]
    assert [p.weeks for p in fy.periods] == [5, 5, 4, 4, 5, 4, 4, 5, 4, 4, 5, 4]


def _13x4_spec(first, last):
    return CalendarSpec(start_month=1, start_day_of_week=MONDAY, pattern="13x4",
                        anchor_rule="nearest", first_year=first, last_year=last)


def test_13x4_grid_is_thirteen_four_week_periods_in_3_3_3_4_quarters():
    # FY2021 (Jan/Monday/nearest) is a 52-week year: 2021-01-04 .. 2022-01-03.
    # Do NOT use FY2020 here — it spans 371 days, so one period holds 5 weeks.
    fy = build_years(_13x4_spec(2021, 2021))[0]
    assert fy.weeks == 52
    assert len(fy.periods) == 13
    assert [p.weeks for p in fy.periods] == [4] * 13
    assert [p.quarter for p in fy.periods] == [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 4]


def test_13x4_leap_year_puts_the_extra_week_on_the_last_period():
    # FY2020 is 371 days (2019-12-30 .. 2021-01-04) — a 53-week 13-period year.
    fy = build_years(_13x4_spec(2020, 2020))[0]
    assert fy.weeks == 53
    assert [p.weeks for p in fy.periods] == [4] * 12 + [5]
    assert fy.periods[-1].quarter == 4


def test_periods_tile_the_year_with_no_gaps():
    for fy in build_years(_lulu_spec()):
        assert fy.periods[0].start == fy.start
        assert fy.periods[-1].end_exclusive == fy.end_exclusive
        for a, b in zip(fy.periods, fy.periods[1:]):
            assert a.end_exclusive == b.start


def test_years_tile_with_no_gaps():
    years = build_years(_lulu_spec())
    for a, b in zip(years, years[1:]):
        assert a.end_exclusive == b.start


def test_period_weeks_rejects_out_of_range_surplus_instead_of_an_oversized_period():
    with pytest.raises(ValueError, match="54"):
        _period_weeks(_lulu_spec(), 54)


def test_period_weeks_rejects_negative_surplus_instead_of_a_negative_period():
    with pytest.raises(ValueError, match="47"):
        _period_weeks(_lulu_spec(), 47)
