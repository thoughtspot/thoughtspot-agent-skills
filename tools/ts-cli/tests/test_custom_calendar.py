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
