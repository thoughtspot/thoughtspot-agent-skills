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


from ts_cli.custom_calendar.labels import render, fiscal_year_label


def _dec_year():
    """A December-start fiscal year — the case where fiscal and calendar years differ."""
    spec = CalendarSpec(start_month=12, start_day_of_week=MONDAY, pattern="4-4-5",
                        anchor_rule="first", first_year=2024, last_year=2025)
    return build_years(spec)[0]


# The Dec-2024 fiscal year runs 2024-12-02 .. 2025-11-30 (52 weeks). Its second
# period spans 2024-12-30 .. 2025-01-26, so the period START is still in 2024 —
# use an explicit mid-January date to exercise the fiscal-vs-gregorian split.
JAN_2025 = date(2025, 1, 15)


def test_fiscal_basis_reproduces_the_thoughtspot_defect():
    # ThoughtSpot emits monthly="January 2024" for dates in January 2025.
    fy = _dec_year()
    jan = fy.periods[1]
    assert jan.start <= JAN_2025 < jan.end_exclusive
    out = render(LabelSpec(), fy, jan, JAN_2025)
    assert out["year"] == "2024"
    assert out["monthly"].endswith("2024")     # ... for a date in 2025


def test_gregorian_basis_fixes_monthly_and_year():
    fy = _dec_year()
    jan = fy.periods[1]
    labels = LabelSpec(year_basis="gregorian", monthly_basis="gregorian")
    out = render(labels, fy, jan, JAN_2025)
    assert out["year"] == "2025"
    assert out["monthly"].endswith("2025")


def test_bases_are_independent_quarterly_can_stay_fiscal():
    # The motivating client case: year+monthly gregorian, quarterly left fiscal.
    fy = _dec_year()
    jan = fy.periods[1]
    labels = LabelSpec(year_basis="gregorian", monthly_basis="gregorian",
                       quarterly_basis="fiscal", year_prefix="FY", quarter_prefix="Q")
    out = render(labels, fy, jan, JAN_2025)
    assert out["year"] == "FY2025"
    assert out["quarterly"].endswith("FY2024")


def test_prefixes_apply_to_year_and_quarter():
    fy = _lulu_year_2017()
    p = fy.periods[0]
    out = render(LabelSpec(year_prefix="FY", quarter_prefix="Q"), fy, p, p.start)
    assert out["year"] == "FY2017"
    assert out["quarter"] == "Q1"
    assert out["quarterly"] == "Q1 FY2017"


def _lulu_year_2017():
    return {y.number: y for y in build_years(_lulu_spec())}[2017]


def test_month_names_drive_localization_abbreviation_and_period_labels():
    fy = _lulu_year_2017()
    p = fy.periods[0]
    abbrev = LabelSpec(month_names=("FEB", "MAR", "APR", "MAY", "JUN", "JUL",
                                    "AUG", "SEP", "OCT", "NOV", "DEC", "JAN"))
    assert render(abbrev, fy, p, p.start)["month"] == "FEB"

    periods = LabelSpec(month_names=tuple(f"Period {i}" for i in range(1, 13)))
    assert render(periods, fy, p, p.start)["month"] == "Period 1"

    jp = LabelSpec(month_names=tuple(f"{i}月" for i in range(1, 13)),
                   day_names=("日", "月", "火", "水", "木", "金", "土"))
    out = render(jp, fy, p, p.start)
    assert out["month"] == "1月"
    assert out["day_of_week"] == "月"     # 2017-01-30 is a Monday


def test_fiscal_year_number_end_convention():
    fy = _dec_year()
    assert fiscal_year_label(LabelSpec(), fy) == "2024"
    assert fiscal_year_label(LabelSpec(fiscal_year_number="end"), fy) == "2025"


def test_default_month_names_for_twelve_period_patterns():
    from ts_cli.custom_calendar.labels import default_month_names
    for pattern in ("4-4-5", "4-5-4", "5-4-4"):
        assert default_month_names(pattern)[0] == "January"
        assert len(default_month_names(pattern)) == 12


def test_default_month_names_for_13x4_are_zero_padded():
    # Unpadded "Period 1".."Period 13" sort lexically as
    # Period 1, Period 10, Period 11, Period 12, Period 13, Period 2, ...
    # which scrambles any consumer that sorts the label instead of
    # month_number_of_year. Confirmed against FISCAL_CALENDAR_13_PERIOD.
    from ts_cli.custom_calendar.labels import default_month_names
    names = default_month_names("13x4")
    assert len(names) == 13
    assert names[0] == "Period 01"
    assert names[12] == "Period 13"
    assert list(names) == sorted(names)      # lexical order == numeric order


def test_render_day_of_week_agrees_with_sunday_index_across_a_week():
    # render() must not carry its own Monday->Sunday conversion — sunday_index()
    # in anchors.py is the only one. Pin agreement across a full week so the two
    # can't silently drift apart.
    from datetime import timedelta
    from ts_cli.custom_calendar.spec import DAYS_EN

    fy = _lulu_year_2017()
    p = fy.periods[0]
    for offset in range(7):
        d = p.start + timedelta(days=offset)
        out = render(LabelSpec(), fy, p, d)
        assert out["day_of_week"] == DAYS_EN[sunday_index(d)]


from ts_cli.custom_calendar.rows import build_rows, COLUMNS_10, COLUMNS_30, columns_for


def test_first_ten_columns_are_the_contract_in_order():
    assert COLUMNS_10 == (
        "date", "day_of_week", "month", "quarter", "year",
        "day_number_of_week", "week_number_of_month", "week_number_of_quarter",
        "week_number_of_year", "is_weekend",
    )
    assert COLUMNS_30[:10] == COLUMNS_10
    assert len(COLUMNS_30) == 30


def test_row_count_matches_the_grid():
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec())
    assert len(rows) == 364
    rows18 = build_rows(_lulu_spec(2018, 2018), LabelSpec())
    assert len(rows18) == 371


def test_start_day_moves_day_number_of_week_but_not_day_of_week_or_is_weekend():
    """The distinction the whole day-numbering design rests on.

    `day_number_of_week` is RELATIVE to the configured start day; `day_of_week`
    and `is_weekend` are ABSOLUTE calendar facts. Build the same dates under a
    Monday-start and a Sunday-start calendar and assert the first moves while
    the other two do not — an assertion that restates the implementation
    (`is_weekend == date.weekday() >= 5`) proves neither.
    """
    monday = {r["date"]: r
              for r in build_rows(_lulu_spec(2017, 2017), LabelSpec())}
    sunday = {r["date"]: r
              for r in build_rows(_lulu_spec(2017, 2017, start_day_of_week=0),
                                  LabelSpec())}
    common = sorted(set(monday) & set(sunday))
    assert len(common) == 364, "the two anchorings must overlap on a full year"

    for d in common:
        assert monday[d]["day_number_of_week"] != sunday[d]["day_number_of_week"], (
            f"{d}: day_number_of_week must follow the start day")
        assert monday[d]["day_of_week"] == sunday[d]["day_of_week"], (
            f"{d}: day_of_week is an absolute weekday, not a start-day offset")
        assert monday[d]["is_weekend"] == sunday[d]["is_weekend"], (
            f"{d}: is_weekend is Saturday/Sunday, not start-day relative")

    # Pin the absolute values so "identical" cannot be satisfied by both being wrong.
    first = monday[date(2017, 1, 30)]                 # a Monday
    assert first["day_number_of_week"] == 1
    assert sunday[date(2017, 1, 30)]["day_number_of_week"] == 2
    assert first["day_of_week"] == "Monday"
    assert first["is_weekend"] is False
    saturday = monday[date(2017, 2, 4)]
    assert saturday["day_of_week"] == "Saturday"
    assert saturday["is_weekend"] is True
    assert sunday[date(2017, 2, 4)]["is_weekend"] is True


def test_end_epochs_are_exclusive():
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec())
    first = rows[0]
    assert first["start_of_week_epoch"] == date(2017, 1, 30)
    assert first["end_of_week_epoch"] == date(2017, 2, 6)     # start of next week
    assert first["start_of_year_epoch"] == date(2017, 1, 30)
    assert first["end_of_year_epoch"] == date(2018, 1, 29)    # start of next year


def test_week_number_of_year_reaches_53_in_a_leap_year():
    rows = build_rows(_lulu_spec(2018, 2018), LabelSpec())
    assert max(r["week_number_of_year"] for r in rows) == 53
    rows17 = build_rows(_lulu_spec(2017, 2017), LabelSpec())
    assert max(r["week_number_of_year"] for r in rows17) == 52


def test_ten_column_mode_emits_only_the_contract_columns():
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec(), columns=10)
    assert tuple(rows[0].keys()) == COLUMNS_10


def test_absolute_numbers_increase_across_years():
    rows = build_rows(_lulu_spec(2017, 2018), LabelSpec())
    assert rows[0]["absolute_year_number"] == 1
    assert rows[-1]["absolute_year_number"] == 2
    assert rows[-1]["absolute_month_number"] == 24


import io
from ts_cli.custom_calendar.emit import write_csv, snowflake_ddl, union_sql


def test_csv_header_matches_columns_and_dates_are_iso():
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec(), columns=10)
    buf = io.StringIO()
    write_csv(rows, COLUMNS_10, buf)
    lines = buf.getvalue().splitlines()
    assert lines[0] == ",".join(COLUMNS_10)
    assert lines[1].startswith("2017-01-30,Monday,")


def test_csv_appends_discriminator_column_when_given():
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec(), columns=10)
    buf = io.StringIO()
    write_csv(rows, COLUMNS_10, buf, discriminator=("TS_CALENDAR_GROUP", "tsCal1"))
    lines = buf.getvalue().splitlines()
    assert lines[0].endswith(",TS_CALENDAR_GROUP")
    assert lines[1].endswith(",tsCal1")


def test_snowflake_ddl_quotes_lowercase_identifiers():
    ddl = snowflake_ddl("MY_CAL", COLUMNS_10, database="CUSTOM_CALENDAR", schema="PUBLIC")
    assert 'CREATE OR REPLACE TABLE "CUSTOM_CALENDAR"."PUBLIC"."MY_CAL"' in ddl
    assert '"date" DATE' in ddl
    assert '"is_weekend" BOOLEAN' in ddl
    assert '"day_number_of_week" NUMBER' in ddl
    assert '"month" VARCHAR' in ddl


def test_snowflake_ddl_adds_discriminator_last():
    ddl = snowflake_ddl("MY_CAL", COLUMNS_10, database="D", schema="S",
                        discriminator="TS_CALENDAR_GROUP")
    body = ddl[ddl.index("("):]
    assert body.rstrip().rstrip(");").strip().endswith("TS_CALENDAR_GROUP VARCHAR")


def test_union_sql_matches_the_rlscalendar_shape():
    cset = CalendarSet(
        labels=LabelSpec(),
        variants=(("tsCalendar1", _lulu_spec()), ("tsCalendar2", _lulu_spec())),
    )
    sql = union_sql(cset, database="CUSTOM_CALENDAR", schema="PUBLIC",
                    target="rlscal", source_tables=("saturdaycalendar", "mondaycalendar"))
    assert "CREATE OR REPLACE VIEW" in sql
    assert "UNION ALL" in sql
    # Assert whole-line pairing, not scattered substrings — a mispaired
    # (variant, source_table) zip must fail this test.
    assert ('\'tsCalendar1\' AS TS_CALENDAR_GROUP FROM '
            '"CUSTOM_CALENDAR"."PUBLIC"."saturdaycalendar"') in sql
    assert ('\'tsCalendar2\' AS TS_CALENDAR_GROUP FROM '
            '"CUSTOM_CALENDAR"."PUBLIC"."mondaycalendar"') in sql
    # Reject the crossed pairings explicitly.
    assert ('\'tsCalendar1\' AS TS_CALENDAR_GROUP FROM '
            '"CUSTOM_CALENDAR"."PUBLIC"."mondaycalendar"') not in sql
    assert ('\'tsCalendar2\' AS TS_CALENDAR_GROUP FROM '
            '"CUSTOM_CALENDAR"."PUBLIC"."saturdaycalendar"') not in sql


def test_union_sql_can_materialise_as_a_table():
    cset = CalendarSet(
        labels=LabelSpec(),
        variants=(("a", _lulu_spec()), ("b", _lulu_spec())),
        materialisation="table",
    )
    sql = union_sql(cset, database="D", schema="S", target="t",
                    source_tables=("x", "y"))
    assert "CREATE OR REPLACE TABLE" in sql


def test_union_sql_rejects_variant_count_mismatch():
    cset = CalendarSet(labels=LabelSpec(), variants=(("a", _lulu_spec()),))
    with pytest.raises(ValueError, match="source_tables"):
        union_sql(cset, database="D", schema="S", target="t", source_tables=("x", "y"))


from ts_cli.custom_calendar.validate import Finding, validate_rows, validate_set_labels


def test_clean_calendar_has_no_findings():
    rows = build_rows(_lulu_spec(2017, 2018), LabelSpec())
    assert validate_rows(rows, columns=COLUMNS_30) == []


def test_missing_date_is_detected():
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec())
    del rows[10]
    codes = [f.code for f in validate_rows(rows, columns=COLUMNS_30)]
    assert "date-gap" in codes


def test_duplicate_date_is_detected():
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec())
    rows.append(dict(rows[0]))
    codes = [f.code for f in validate_rows(rows, columns=COLUMNS_30)]
    assert "duplicate-date" in codes


def test_wrong_column_set_is_detected():
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec())
    rows[0].pop("is_weekend")
    codes = [f.code for f in validate_rows(rows, columns=COLUMNS_30)]
    assert "column-contract" in codes


def test_week_number_above_53_is_detected():
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec())
    rows[0]["week_number_of_year"] = 54
    codes = [f.code for f in validate_rows(rows, columns=COLUMNS_30)]
    assert "week-number-range" in codes


def test_cross_variant_label_drift_fails_on_closed_vocabularies():
    base = build_rows(_lulu_spec(2017, 2017), LabelSpec())
    abbrev = build_rows(
        _lulu_spec(2017, 2017),
        LabelSpec(month_names=("FEB", "MAR", "APR", "MAY", "JUN", "JUL",
                               "AUG", "SEP", "OCT", "NOV", "DEC", "JAN")),
    )
    findings = validate_set_labels({"a": base, "b": abbrev})
    drift = [f for f in findings if f.code == "label-drift"]
    assert drift and drift[0].severity == "error"
    assert "month" in drift[0].message
    assert "February" in drift[0].message or "FEB" in drift[0].message


def test_allow_label_drift_downgrades_to_warning():
    base = build_rows(_lulu_spec(2017, 2017), LabelSpec())
    abbrev = build_rows(
        _lulu_spec(2017, 2017),
        LabelSpec(month_names=("FEB", "MAR", "APR", "MAY", "JUN", "JUL",
                               "AUG", "SEP", "OCT", "NOV", "DEC", "JAN")),
    )
    findings = validate_set_labels({"a": base, "b": abbrev}, allow_label_drift=True)
    drift = [f for f in findings if f.code == "label-drift"]
    assert drift, "expected label-drift findings to exist before checking severity"
    assert all(f.severity == "warning" for f in drift)


def test_identical_variants_produce_no_label_findings():
    a = build_rows(_lulu_spec(2017, 2017), LabelSpec())
    b = build_rows(
        CalendarSpec(start_month=FEB, start_day_of_week=6, pattern="4-5-4",
                     anchor_rule="nearest", first_year=2017, last_year=2017),
        LabelSpec(),
    )
    # Different start day (a genuine grid difference) but the same vocabulary.
    assert [f for f in validate_set_labels({"a": a, "b": b})
            if f.code == "label-drift"] == []


def test_year_prefix_drift_is_a_warning_not_an_error():
    a = build_rows(_lulu_spec(2017, 2017), LabelSpec(year_prefix="FY"))
    b = build_rows(_lulu_spec(2017, 2017), LabelSpec(year_prefix=""))
    findings = [f for f in validate_set_labels({"a": a, "b": b})
                if f.code == "label-format-drift"]
    assert findings and all(f.severity == "warning" for f in findings)


from ts_cli.custom_calendar.compare import (
    LABEL_DIMENSIONS, compare_labels, compare_anchors,
)


def _dec_spec():
    return CalendarSpec(start_month=12, start_day_of_week=MONDAY, pattern="4-4-5",
                        anchor_rule="first", first_year=2024, last_year=2024)


def _jan_spec():
    # FY2023 is the genuine zero case: 2023-01-02 .. 2023-12-31, 52 weeks, entirely
    # inside one Gregorian year. Most January-start week-aligned years DO spill —
    # FY2024 runs to 2025-01-05 (53 weeks) and yields 5 differing rows.
    return CalendarSpec(start_month=1, start_day_of_week=MONDAY, pattern="4-4-5",
                        anchor_rule="first", first_year=2023, last_year=2023)


def _jan_spilling_spec():
    # FY2024: 2024-01-01 .. 2025-01-05, 53 weeks — spills 5 days into 2025.
    return CalendarSpec(start_month=1, start_day_of_week=MONDAY, pattern="4-4-5",
                        anchor_rule="first", first_year=2024, last_year=2024)


def test_label_dimensions_cover_every_comparable_option():
    assert LABEL_DIMENSIONS["year-basis"] == ("fiscal", "gregorian")
    assert LABEL_DIMENSIONS["monthly-basis"] == ("fiscal", "gregorian")
    assert LABEL_DIMENSIONS["quarterly-basis"] == ("fiscal", "gregorian")
    assert LABEL_DIMENSIONS["fiscal-year-number"] == ("start", "end")


def test_december_calendar_has_differing_rows_for_year_basis():
    out = compare_labels(_dec_spec(), LabelSpec(), "year-basis")
    assert out["values"] == ["fiscal", "gregorian"]
    assert out["total_rows"] == 364
    assert out["differing_rows"] > 0
    sample = out["samples"][0]
    assert sample["fiscal"]["year"] != sample["gregorian"]["year"]


def test_a_fiscal_year_inside_one_gregorian_year_reports_zero_differing_rows():
    # A null result is the informative case: the choice is irrelevant for THIS
    # calendar. It is not a property of January starts in general — see the
    # spilling test below.
    out = compare_labels(_jan_spec(), LabelSpec(), "year-basis")
    assert out["total_rows"] == 364
    assert out["differing_rows"] == 0
    assert out["samples"] == []


def test_a_spilling_january_year_does_report_differing_rows():
    # The counterpart, and the reason `compare` earns its place: a week-aligned
    # January calendar usually DOES spill into the next Gregorian year, which a
    # user would not guess. FY2024 spills 5 days.
    out = compare_labels(_jan_spilling_spec(), LabelSpec(), "year-basis")
    assert out["differing_rows"] == 5
    assert out["samples"][0]["fiscal"]["year"] == "2024"
    assert out["samples"][0]["gregorian"]["year"] == "2025"


def test_compare_labels_rejects_unknown_dimension():
    with pytest.raises(ValueError, match="dimension"):
        compare_labels(_dec_spec(), LabelSpec(), "colour")


def test_compare_labels_caps_the_sample():
    out = compare_labels(_dec_spec(), LabelSpec(), "year-basis", max_samples=3)
    assert len(out["samples"]) <= 3


def test_compare_anchors_reports_first_divergence():
    spec = _lulu_spec(2015, 2026)
    out = compare_anchors(spec)
    assert out["values"] == ["nearest", "first", "fixed52"]
    by_year = {y["year"]: y for y in out["years"]}
    assert by_year[2015]["nearest"] == "2015-02-02"
    assert by_year[2017]["nearest"] == "2017-01-30"
    assert by_year[2017]["first"] == "2017-02-06"
    # nearest and fixed52 agree until the 2018 leap week pushes them apart.
    assert by_year[2019]["nearest"] == "2019-02-04"
    assert by_year[2019]["fixed52"] == "2019-01-28"
    assert out["first_divergence"] == 2017


def test_compare_anchors_flags_the_short_range_trap():
    out = compare_anchors(_lulu_spec(2015, 2026))
    assert out["nearest_vs_fixed52_first_divergence"] == 2019


# --- the skill's reference SQL is a second copy of the column contract -------
# Two .sql files under agents/cli/ts-object-calendar-builder/references/ name
# all 30 contract columns by hand. They are executed by CoCo-less runtimes via
# `ts snowflake exec`, so nothing else checks them against COLUMNS_30. A column
# added to the contract and not to these files would produce a table that
# imports nowhere and whose failure the API never explains (it returns the same
# CONNECTION_METADATA_FETCH_ERROR for every contract violation — open item 4).

import re as _re
from pathlib import Path as _Path

from ts_cli.custom_calendar.emit import _sql_type
from ts_cli.custom_calendar.rows import COLUMNS_30 as _COLUMNS_30

_REFERENCES = (_Path(__file__).resolve().parents[3]
               / "agents" / "cli" / "ts-object-calendar-builder" / "references")
_ALIAS_RE = _re.compile(r'AS "([a-z_]+)"')


@pytest.mark.parametrize("name", ["fix-column-case.sql", "relabel-calendar.sql"])
def test_reference_sql_selects_every_contract_column_in_order(name):
    body = (_REFERENCES / name).read_text(encoding="utf-8")
    # Columns carried through unchanged appear as a bare quoted name, the
    # rewritten/cast ones as `... AS "name"`. Take the select list as written.
    select_list = body.split("SELECT", 1)[1].split("FROM", 1)[0]
    selected = []
    for line in select_list.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        alias = _ALIAS_RE.search(line)
        selected.append(alias.group(1) if alias
                        else line.strip('"').split('"')[0])
    assert selected == list(_COLUMNS_30)


def test_fix_column_case_sql_reads_upper_case_and_casts_to_contract_types():
    body = (_REFERENCES / "fix-column-case.sql").read_text(encoding="utf-8")
    for column in _COLUMNS_30:
        assert f'"{column.upper()}"::{_sql_type(column)}' in body, column


def test_fix_column_case_sql_has_no_placeholder_outside_the_four_vars():
    # `ts snowflake exec` scans the WHOLE file, comments included, and aborts on
    # any placeholder it cannot fill — so an illustrative {token} in the header
    # comment would make the documented command fail before it reaches Snowflake.
    body = (_REFERENCES / "fix-column-case.sql").read_text(encoding="utf-8")
    found = set(_re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", body))
    assert found == {"source_db", "source_schema", "source_table", "target_table"}


# --- Filter-widget limitations (open item 6) ----------------------------------
# Provenance: ThoughtSpot product knowledge confirmed at PR review 2026-09-16,
# NOT an automated probe. Warnings only — such calendars are legitimate, just
# constrained in the typed-value filter components.

def test_non_month_period_labels_warn_they_cannot_be_filter_selected():
    from ts_cli.custom_calendar.labels import default_month_names
    rows = build_rows(_13x4_spec(2021, 2021),
                      LabelSpec(month_names=default_month_names("13x4")))
    findings = [f for f in validate_rows(rows, columns=COLUMNS_30)
                if f.code == "month-label-not-filter-selectable"]
    assert findings and findings[0].severity == "warning"
    assert "Period 01" in findings[0].message


def test_year_prefix_warns_the_year_filter_takes_four_digits_only():
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec(year_prefix="FY"))
    findings = [f for f in validate_rows(rows, columns=COLUMNS_30)
                if f.code == "year-label-not-filter-typeable"]
    assert findings and findings[0].severity == "warning"
    assert "FY2017" in findings[0].message


def test_quarter_prefix_alone_raises_no_filter_warning():
    # Q1 IS selectable in the filter widget — the YYYY-only rule is specific to
    # the YEAR filter. Warning here would cost a capability for no reason.
    rows = build_rows(_lulu_spec(2017, 2017), LabelSpec(quarter_prefix="Q"))
    assert validate_rows(rows, columns=COLUMNS_30) == []


def test_abbreviated_english_months_raise_no_filter_warning():
    # The corpus ships FEB alongside April; both are month names to the widget.
    rows = build_rows(_lulu_spec(2017, 2017),
                      LabelSpec(month_names=("FEB", "MAR", "APR", "MAY", "JUN", "JUL",
                                             "AUG", "SEP", "OCT", "NOV", "DEC", "JAN")))
    assert validate_rows(rows, columns=COLUMNS_30) == []
