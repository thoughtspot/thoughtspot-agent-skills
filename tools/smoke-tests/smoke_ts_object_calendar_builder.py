# tools/smoke-tests/smoke_ts_object_calendar_builder.py
"""Smoke test for ts-object-calendar-builder.

Tier: Pure — no live ThoughtSpot or Snowflake connection required, no `ts` on
PATH. Exercises the generator end to end against the LULULEMON oracle read from
CUSTOM_CALENDAR.PUBLIC on 2026-09-15.

Usage:
    python3 tools/smoke-tests/smoke_ts_object_calendar_builder.py
"""
from __future__ import annotations

import io
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "ts-cli"))

from ts_cli.custom_calendar.emit import write_csv  # noqa: E402
from ts_cli.custom_calendar.rows import COLUMNS_30, build_rows  # noqa: E402
from ts_cli.custom_calendar.spec import CalendarSpec, LabelSpec  # noqa: E402
from ts_cli.custom_calendar.validate import validate_rows, validate_set_labels  # noqa: E402

MONDAY, FEB = 1, 2

LULULEMON_STARTS = {
    2015: date(2015, 2, 2), 2016: date(2016, 2, 1), 2017: date(2017, 1, 30),
    2018: date(2018, 1, 29), 2019: date(2019, 2, 4), 2020: date(2020, 2, 3),
    2021: date(2021, 2, 1), 2022: date(2022, 1, 31), 2023: date(2023, 1, 30),
    2024: date(2024, 1, 29), 2025: date(2025, 2, 3), 2026: date(2026, 2, 2),
}


def _retail_spec(first=2015, last=2026):
    return CalendarSpec(start_month=FEB, start_day_of_week=MONDAY, pattern="4-5-4",
                        anchor_rule="nearest", first_year=first, last_year=last)


def test_reproduces_lululemon_year_starts():
    from ts_cli.custom_calendar.grid import build_years
    got = {fy.number: fy.start for fy in build_years(_retail_spec())}
    for year, expected in LULULEMON_STARTS.items():
        assert got[year] == expected, f"{year}: got {got[year]}, expected {expected}"
    print(f"  year starts match LULULEMON for {len(LULULEMON_STARTS)} years")


def test_leap_years_are_2018_and_2024():
    from ts_cli.custom_calendar.grid import build_years
    leap = [fy.number for fy in build_years(_retail_spec()) if fy.weeks == 53]
    assert leap == [2018, 2024], leap
    print("  53-week years: 2018, 2024")


def test_generated_calendar_validates_clean():
    rows = build_rows(_retail_spec(2017, 2019), LabelSpec())
    findings = validate_rows(rows, columns=COLUMNS_30)
    assert findings == [], findings
    print(f"  {len(rows)} rows validate clean")


def test_csv_round_trips():
    rows = build_rows(_retail_spec(2017, 2017), LabelSpec())
    buf = io.StringIO()
    write_csv(rows, COLUMNS_30, buf)
    lines = buf.getvalue().splitlines()
    assert len(lines) == 365, len(lines)
    assert lines[0] == ",".join(COLUMNS_30)
    print("  CSV header and row count correct")


def test_label_drift_is_caught_across_variants():
    a = build_rows(_retail_spec(2017, 2017), LabelSpec())
    b = build_rows(_retail_spec(2017, 2017),
                   LabelSpec(month_names=("FEB", "MAR", "APR", "MAY", "JUN", "JUL",
                                          "AUG", "SEP", "OCT", "NOV", "DEC", "JAN")))
    findings = validate_set_labels({"a": a, "b": b})
    assert any(f.code == "label-drift" and f.severity == "error" for f in findings)
    print("  cross-variant label drift detected")


if __name__ == "__main__":
    for fn in (test_reproduces_lululemon_year_starts,
               test_leap_years_are_2018_and_2024,
               test_generated_calendar_validates_clean,
               test_csv_round_trips,
               test_label_drift_is_caught_across_variants):
        print(f"{fn.__name__}:")
        fn()
    print("All smoke tests passed.")
